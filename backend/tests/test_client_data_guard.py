"""The no-client-data block check: known data by keyed hash, on diff, tree and PR text.

Every token here is invented. The real list stays outside this public repository;
only its keyed hashes are tracked, so these tests build their own small list.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import build_client_data_list as builder  # noqa: E402
import check_client_identifiers as guard  # noqa: E402

SALT = b"invented-salt-16"
NAME = "Zorbaco Refining"
DOC_NUMBER = "QQ7777-RS-5"
SENTENCE = "the invented flange shall carry a purple stamp near each handle"
PUBLIC_SENTENCE = "the published standard wording shall stay free for every reader here"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


def _write_list(repo: Path) -> None:
    client = builder.runs(builder.words_of(SENTENCE))
    lengths, digests = builder.build([NAME, DOC_NUMBER], client, set(), set(), SALT)
    (repo / ".github").mkdir(exist_ok=True)
    head = [f"salt {SALT.hex()}", "lengths " + " ".join(map(str, lengths))]
    (repo / guard.HASH_FILE).write_text(
        "\n".join(head + digests) + "\n", encoding="utf-8"
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "feature")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "core.hooksPath", "/dev/null")
    _write_list(root)
    shutil.copy(REPO / guard.PATTERN_FILE, root / guard.PATTERN_FILE)
    (root / "old.txt").write_text("harmless\n")
    _commit(root, "base")
    return root


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", message)
    return _git(repo, "rev-parse", "HEAD")


def _run(repo: Path, *args: str, env: dict[str, str] | None = None):
    return subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "check_client_identifiers.py"),
            "--root",
            str(repo),
            *args,
        ],
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
    )


@pytest.mark.parametrize(
    "spelling",
    [
        NAME,
        NAME.upper(),
        "zorbaco_refining",
        "Zorbaco\tRefining",
        DOC_NUMBER,
        "qq7777 rs 5",
        "QQ7777/RS/5",
    ],
)
def test_a_listed_name_fails_the_tree_in_any_spelling_and_the_log_does_not_repeat_it(
    repo, spelling
):
    (repo / "note.md").write_text(f"see {spelling} here\n", encoding="utf-8")
    _commit(repo, "plant")
    done = _run(repo, "--tree")
    assert done.returncode == 1, done.stdout
    assert "note.md:1: known client data" in done.stdout
    assert spelling.lower() not in done.stdout.lower()


def test_a_clean_tree_passes_and_says_how_much_it_read(repo):
    done = _run(repo, "--tree")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "listed entries read" in done.stdout


def test_a_diff_adding_a_listed_name_fails_even_when_the_shape_is_unknown(repo):
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "old.txt").write_text(f"harmless\nnow {NAME}\n", encoding="utf-8")
    _commit(repo, "adds")
    done = _run(repo, "--base", base)
    assert done.returncode == 1
    assert "old.txt:2: known client data (2 words)" in done.stdout


def test_a_file_named_after_a_document_fails_the_diff_and_the_tree(repo):
    base = _git(repo, "rev-parse", "HEAD")
    (repo / f"{DOC_NUMBER}.txt").write_text("harmless\n", encoding="utf-8")
    _commit(repo, "adds")
    assert _run(repo, "--base", base).returncode == 1
    assert _run(repo, "--tree").returncode == 1


def test_eight_words_of_client_text_fail_even_across_a_line_break(repo):
    words = SENTENCE.split()
    (repo / "t.py").write_text(
        f"# {' '.join(words[:4])}\n# {' '.join(words[4:8])}\n", encoding="utf-8"
    )
    _commit(repo, "plant")
    done = _run(repo, "--tree")
    assert done.returncode == 1 and "t.py:1: known client data (8 words)" in done.stdout
    assert "purple" not in done.stdout


def test_seven_words_of_client_text_pass(repo):
    (repo / "t.md").write_text(" ".join(SENTENCE.split()[:7]) + "\n", encoding="utf-8")
    _commit(repo, "ok")
    assert _run(repo, "--tree").returncode == 0


def test_a_short_name_is_not_found_across_a_line_break(repo):
    (repo / "t.py").write_text("Zorbaco\nRefining\n", encoding="utf-8")
    _commit(repo, "ok")
    assert _run(repo, "--tree").returncode == 0


@pytest.mark.parametrize("var", ["PR_TITLE", "PR_BODY"])
def test_the_pr_title_and_body_are_read(repo, var):
    bad = _run(repo, "--tree", "--text-env", var, env={var: f"fix for {DOC_NUMBER}"})
    assert bad.returncode == 1
    assert f"{var}:1: known client data" in bad.stdout and DOC_NUMBER not in bad.stdout
    good = _run(repo, "--tree", "--text-env", var, env={var: "fix for Datasheet 1"})
    assert good.returncode == 0


def test_an_empty_pr_body_is_not_an_error(repo):
    assert (
        _run(repo, "--tree", "--text-env", "PR_BODY", env={"PR_BODY": ""}).returncode
        == 0
    )


def test_a_commit_message_is_read_only_when_asked(repo):
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "x.txt").write_text("harmless\n")
    _commit(repo, f"docs: about {NAME}")
    assert _run(repo, "--base", base).returncode == 0
    done = _run(repo, "--base", base, "--commits")
    assert done.returncode == 1 and "commit " in done.stdout and NAME not in done.stdout


def test_a_missing_list_refuses_rather_than_passes(repo):
    (repo / guard.HASH_FILE).unlink()
    done = _run(repo, "--tree")
    assert done.returncode == 2 and "vacuously" in done.stderr


def test_an_empty_list_refuses_rather_than_passes(repo):
    (repo / guard.HASH_FILE).write_text(
        f"salt {SALT.hex()}\nlengths 2\n", encoding="utf-8"
    )
    assert _run(repo, "--tree").returncode == 2


def test_an_exception_covers_only_its_own_file_and_entry(repo):
    code = guard.digest(SALT, ["zorbaco", "refining"])
    (repo / guard.EXCEPTION_FILE).write_text(
        f"# why\nkept.py {code}\n", encoding="utf-8"
    )
    (repo / "kept.py").write_text(f"{NAME}\n", encoding="utf-8")
    _commit(repo, "kept")
    assert _run(repo, "--tree").returncode == 0
    (repo / "kept.py").write_text(f"{NAME} {DOC_NUMBER}\n", encoding="utf-8")
    (repo / "other.py").write_text(f"{NAME}\n", encoding="utf-8")
    _commit(repo, "more")
    done = _run(repo, "--tree")
    assert "other.py:1: known client data (2 words)" in done.stdout
    assert "kept.py:1: known client data (3 words)" in done.stdout


def test_the_builder_drops_public_wording_and_number_runs():
    public = builder.runs(builder.words_of(PUBLIC_SENTENCE))
    numbers = builder.runs(builder.words_of("1 2 3 4 5 6 7 8 9"))
    client = builder.runs(builder.words_of(SENTENCE)) | public | numbers
    _, digests = builder.build([], client, public, set(), SALT)
    known = guard.KnownData(SALT, [8], set(digests))
    assert known.find(SENTENCE)
    assert not known.find(PUBLIC_SENTENCE)
    assert not known.find("1 2 3 4 5 6 7 8 9")


def test_the_builder_drops_a_phrase_reviewed_as_generic():
    client = builder.runs(builder.words_of(SENTENCE))
    allow = builder.runs(builder.words_of(SENTENCE))
    assert builder.build([NAME], client, set(), allow, SALT)[0] == [2]


def _tracked_list() -> guard.KnownData:
    return guard.load_known_data(REPO)


def test_the_tracked_list_spells_nothing_and_is_not_trivially_small():
    text = (REPO / guard.HASH_FILE).read_text(encoding="utf-8")
    body = [ln for ln in text.splitlines() if ln and not ln.startswith("#")]
    assert body[0].startswith("salt ") and body[1].startswith("lengths ")
    digests = body[2:]
    assert len(digests) > 1000
    assert all(re.fullmatch(r"[0-9a-f]{12}", ln) for ln in digests)


@pytest.mark.parametrize(
    "public",
    [
        "SAES-A-105",
        "SAES-L-132",
        "SAEP-302",
        "SAIC-A-2008",
        "ISO 15156",
        "API 610",
        "API RP 520",
        "ASME B16.5",
        "NACE MR-0175",
        "01-SAMSS-016",
        "ASTM A995",
        "EN 13463-1",
    ],
)
def test_public_standard_numbers_hit_neither_list(public):
    block, allow = guard.load_patterns(REPO)
    assert guard.hits_in(f"per {public} clause 5", block, allow) == []
    assert _tracked_list().find(f"per {public} clause 5") == []


@pytest.mark.parametrize(
    "tag,hit",
    # Built from parts so this file does not itself add a tag-shaped token.
    [
        ("PSV-" + "2345 A/B", True),
        ("PRV-" + "555", True),
        ("12-G" + "-345", True),
        ("1200-12-V" + "-3456A", True),
        ("PSV-9901 A/B", False),
        ("99-G-911 A/B", False),
        ("9900-99-V-0101A/B", False),
    ],
)
def test_a_tag_shape_is_blocked_on_a_diff_and_the_invented_form_is_not(tag, hit):
    block, allow = guard.load_patterns(REPO)
    assert bool(guard.hits_in(f"tag {tag}", block, allow)) is hit


def test_the_mask_keeps_the_shape_only():
    assert guard.mask("PSV-" + "2345") == "AAA-9999"


def test_ci_reads_the_diff_commits_tree_and_pr_text():
    text = (REPO / ".github" / "workflows" / "secret-scan.yml").read_text(
        encoding="utf-8"
    )
    for needed in (
        "--commits --tree",
        "--text-env PR_TITLE",
        "--text-env PR_BODY",
        "github.event.pull_request.body",
        "edited",
    ):
        assert needed in text


def test_pre_push_runs_the_check_for_a_change_of_any_file_type():
    import pre_push_guard

    steps = pre_push_guard.plan(["docs/note.md"], None, REPO)
    commands = [" ".join(cmd) for _, cmd, _, _ in steps]
    assert any(
        "check_client_identifiers.py --base origin/main --commits" in c
        for c in commands
    )
