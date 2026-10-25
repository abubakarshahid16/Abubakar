"""Order 201 (#805 rule 4): no program file names a test sheet.

The quick proof (Rule A): small made-up files, no model, no real document. A name
in CODE fails; a name in a comment or docstring passes only with `[found-on]` on
its line; the real ids, the invented PF1 set and the held-out list are all read.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "check_no_test_sheet_names.py"
)
spec = importlib.util.spec_from_file_location("check_no_test_sheet_names", SCRIPT)
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)

PATTERN = check.build_pattern(
    ["216400C", "EF1975", "M-03", "I-06", "pf1-t01-pump", "STD-PUMP-0101"]
)


def hits(name: str, text: str) -> list[str]:
    return [n for _, n in check.violations_in(Path(name), text, PATTERN)]


def test_the_repository_is_clean_today():
    assert check.main() == 0


def test_a_name_in_python_code_fails():
    assert hits("a.py", 'if sheet_id == "216400C":\n    pass\n') == ["216400C"]
    assert hits("a.py", 'RULES = {"M-03": 1}\n') == ["M-03"]


def test_a_name_in_a_string_a_program_uses_fails_even_with_the_mark_in_a_trailing_comment():
    assert hits("a.py", 'x = "216400C"  # [found-on]\n') == ["216400C"]


def test_a_comment_names_a_sheet_only_with_the_mark():
    assert hits("a.py", "# found on 216400C\n") == ["216400C"]
    assert hits("a.py", "# found on 216400C [found-on]\n") == []


def test_a_docstring_names_a_sheet_only_with_the_mark():
    bare = '"""Seen on I-06."""\n'
    marked = '"""Seen on I-06. [found-on]"""\n'
    assert hits("a.py", bare) == ["I-06"]
    assert hits("a.py", marked) == []
    inner = 'def f():\n    """Why.\n\n    Seen on I-06 [found-on]\n    """\n'
    assert hits("a.py", inner) == []


def test_a_real_client_document_number_is_caught_on_both_halves():
    assert hits("a.py", "# review of EF1975-XX-M-03\n") == ["EF1975", "M-03"]


def test_whole_tokens_only_and_any_case():
    assert hits("a.py", 'x = "M-030"\n') == []
    assert hits("a.py", 'x = "XM-03"\n') == []
    assert hits("a.py", 'x = "PF1-T01-PUMP"\n') == ["PF1-T01-PUMP"]
    assert hits("a.py", 'x = "std-pump-0101"\n') == ["std-pump-0101"]


def test_typescript_comments_with_the_mark_pass_and_code_fails():
    assert hits("a.ts", "// seen on I-06 [found-on]\n") == []
    assert hits("a.ts", "/* seen on I-06 */\n") == ["I-06"]
    assert hits("a.ts", " * seen on I-06 [found-on]\n") == []
    assert hits("a.tsx", 'const sheet = "I-06";\n') == ["I-06"]
    assert hits("a.tsx", 'const sheet = "I-06"; // [found-on]\n') == ["I-06"]


def test_a_data_file_is_code():
    assert hits("a.json", '{"sheet": "216400C"}\n') == ["216400C"]
    assert hits("a.json", '{"note": "216400C [found-on]"}\n') == ["216400C"]


def test_test_files_are_not_scanned():
    for name in ("test_x.py", "x.test.ts", "tests/helper.py", "__tests__/x.ts"):
        assert check._is_test_file(Path(name)), name
    assert not check._is_test_file(Path("backend/app/claims.py"))


def test_the_invented_sheets_are_read_from_the_pf1_spec(tmp_path):
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "id": "pf1-t09-tank",
                        "sheet": {
                            "document_number": "PF1-DS-0909",
                            "tag": "SYN-T-0909",
                        },
                        "standard": {"number": "STD-TANK-0909"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    names = check.pf1_names(spec_file)
    assert set(names) == {"pf1-t09-tank", "PF1-DS-0909", "SYN-T-0909", "STD-TANK-0909"}
    assert check.pf1_names(tmp_path / "missing.json") == []
    assert len(check.pf1_names()) >= 16  # the committed set: 4 sheets x 4 names


def test_the_held_out_ids_come_from_a_local_file(tmp_path, monkeypatch):
    listing = tmp_path / "held.txt"
    listing.write_text(
        "# local, never committed\nHX-77\n\nHX-78  # a note\n", encoding="utf-8"
    )
    ids, note = check.heldout_names(listing)
    assert ids == ["HX-77", "HX-78"] and note is None
    pattern = check.build_pattern(ids)
    assert [
        n for _, n in check.violations_in(Path("a.py"), 'x = "HX-77"\n', pattern)
    ] == ["HX-77"]
    monkeypatch.setenv("PF1_HELDOUT_IDS", str(listing))
    assert check.heldout_names()[0] == ["HX-77", "HX-78"]


def test_a_missing_held_out_list_is_said_not_silent(tmp_path):
    ids, note = check.heldout_names(tmp_path / "none.txt")
    assert ids == [] and "not checked" in note


@pytest.mark.parametrize("bad", ["216400C", "pf1-t01-pump"])
def test_the_run_fails_on_a_planted_name(tmp_path, monkeypatch, bad, capsys):
    base = tmp_path / "backend" / "app"
    base.mkdir(parents=True)
    (base / "planted.py").write_text(f'SHEET = "{bad}"\n', encoding="utf-8")
    monkeypatch.setattr(check, "ROOT", tmp_path)
    monkeypatch.setattr(check, "SCAN", ((base, (".py",)),))
    assert check.main() == 1
    assert "planted.py:1" in capsys.readouterr().out
