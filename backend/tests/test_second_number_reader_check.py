"""The pre-push guard refuses a second number reader or text fold before CI does.

CI's `test_w2_number_parser` sent three PRs of one batch back (a figure comparer, an agent toolbox, a local second
opinion). `scripts/check_second_number_reader.py` runs that rule locally and the pre-push guard now runs it on every
push that changes Python. Nothing here touches the network, a model or the real app folder's files.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


check = _load(
    "check_second_number_reader", REPO / "scripts" / "check_second_number_reader.py"
)
guard = _load(
    "pre_push_guard_for_number_reader", REPO / "scripts" / "pre_push_guard.py"
)


def _app(tmp_path: Path, **files: str) -> Path:
    app = tmp_path / "app"
    app.mkdir(parents=True)
    for name, text in files.items():
        (app / f"{name}.py").write_text(text, encoding="utf-8")
    return app


def _run(app: Path, capsys) -> tuple[int, str]:
    code = check.main(["--app", str(app)])
    return code, capsys.readouterr().out


def test_a_private_number_pattern_is_refused_and_named(tmp_path, capsys):
    app = _app(tmp_path, figures='import re\n_NUMBER_TOKEN = re.compile(r"\\d+")\n')
    code, out = _run(app, capsys)
    assert code == 1
    assert "figures.py" in out and "_DIGIT_RUN" in out and "fold_compat" in out


def test_an_nfkc_text_fold_is_refused(tmp_path, capsys):
    app = _app(
        tmp_path,
        quotes='import unicodedata\nx = unicodedata.normalize("NFKC", "a")\n',
    )
    code, out = _run(app, capsys)
    assert code == 1 and "quotes.py" in out


def test_each_known_private_reader_name_is_refused(tmp_path, capsys):
    for i, line in enumerate(
        [
            "_ANY_NUMBER = 1",
            "_fold_numbers = 1",
            "def _normalise_number_text(t):\n    return t",
        ]
    ):
        code, _ = _run(_app(tmp_path / str(i), x=line + "\n"), capsys)
        assert code == 1, line


def test_a_clean_module_and_a_renamed_pattern_pass(tmp_path, capsys):
    app = _app(
        tmp_path,
        clean="x = 1\n",
        renamed='import re\n_DIGIT_RUN = re.compile(r"\\d+")\n',
        folded="from app.word_fold import fold_compat\n",
    )
    code, out = _run(app, capsys)
    assert code == 0 and out.startswith("OK")


def test_numparse_and_the_exempt_modules_may_fold(tmp_path, capsys):
    fold = 'import unicodedata\nx = unicodedata.normalize("NFKC", "a")\n'
    code, _ = _run(_app(tmp_path, numparse=fold, word_fold=fold), capsys)
    assert (
        code == 0
    )  # numparse is the parser; word_fold is in the CI test's own exemption list


def test_the_rules_are_taken_from_the_ci_test_not_copied():
    ci = _load("w2_ci_rules", REPO / "backend" / "tests" / "test_w2_number_parser.py")
    pattern, exempt = check.load_rules()
    assert pattern.pattern == ci._PRIVATE_PARSER.pattern
    assert exempt == set(ci._NOT_YET_MOVED)


def test_the_real_app_folder_passes_the_check(capsys):
    assert check.main([]) == 0
    assert capsys.readouterr().out.startswith("OK")


def test_a_python_push_runs_the_check_and_a_docs_push_does_not(tmp_path):
    names = lambda files: [s[0] for s in guard.plan(files, "py", tmp_path)]  # noqa: E731
    assert "no second number reader" in names(["backend/app/x.py"])
    assert "no second number reader" not in names(["README.md"])
    step = [
        s
        for s in guard.plan(["backend/app/x.py"], "py", tmp_path)
        if s[0] == "no second number reader"
    ][0]
    assert step[1][1].endswith("check_second_number_reader.py")
    assert "fold_compat" in step[3]
