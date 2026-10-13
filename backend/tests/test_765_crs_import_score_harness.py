"""#765 (Stage E, PROOF FIRST): the harness that imports a past CRS and scores
our findings against it, proved end to end on invented data.

#747 already drafts an answer-key item per comment (`rs.key_from_crs`) and the
CLI already reads a real .xlsx file (`from-crs`). Neither was ever proved
TOGETHER: a file on disk -> the CLI -> a drafted key -> the scorer -> a
recall/precision report. That is the chain a real KJO CRS will take once the
owner supplies one (#765's NEEDS OWNER part); this tests the same unmodified
code on an invented CRS, so the chain is proved before any client text
reaches it. Invented comments and findings only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from app import crs_export
from tools import review_score as rs

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import review_score as cli  # noqa: E402

#: The same two comments #747's own tests already prove parse cleanly (one
#: standard, one clause, one field each) - reused here so this harness test
#: carries no new parsing risk of its own.
COMMENTS = [
    ("p.2 - Margin", "Per SAES-J-600 clause 8, the margin above operating pressure is too small."),
    ("p.4 - Orifice area", "Provide the orifice area (API RP 520 Part I, section 5.2)."),
]


def _write_xlsx(tmp_path: Path, comments=COMMENTS, name="crs.xlsx") -> Path:
    findings = [{"document_name": "invented-vessel.pdf", "page_section": page, "comment": text,
                "comment_by": "Engineer A"} for page, text in comments]
    data = crs_export.build_crs(findings, {"review_run_id": "invented"})
    path = tmp_path / name
    path.write_bytes(data)
    return path


def _drafted_key(tmp_path: Path, out_name="drafted-key.json") -> tuple[int, Path]:
    crs = _write_xlsx(tmp_path)
    out = tmp_path / out_name
    code = cli.main(["from-crs", "--crs", str(crs), "--name", "invented-vessel",
                     "--approved-by", "Engineer A", "--out", str(out)])
    return code, out


def _load_scorable_key(out: Path) -> dict:
    # the drafted file also carries "to_complete" (rows to check by hand);
    # the scorer's own format never has that key.
    return rs.validate_key({k: v for k, v in json.loads(out.read_text(encoding="utf-8")).items()
                            if k != "to_complete"})


def test_the_cli_reads_a_real_file_from_disk_and_drafts_a_scorable_key(tmp_path, capsys):
    code, out = _drafted_key(tmp_path)
    assert code == 0
    printed = capsys.readouterr().out
    assert "2 item(s) drafted, 0 comment(s) to complete" in printed
    key = _load_scorable_key(out)
    assert {(i["standard"], i["clause"], i.get("field")) for i in key["items"]} == {
        ("SAES-J-600", "8", "Margin"), ("API RP 520 Part I", "5.2", "Orifice area")}
    assert key["source"] == "engineer_confirmed" and key["approved_by"] == "Engineer A"


def test_the_cli_refuses_to_write_the_drafted_key_inside_the_repo(tmp_path):
    crs = _write_xlsx(tmp_path)
    inside = REPO / "eval" / "review" / "keys" / "_test_765_refused.json"
    code = cli.main(["from-crs", "--crs", str(crs), "--name", "x",
                     "--approved-by", "Engineer A", "--out", str(inside)])
    assert code == 2
    assert not inside.exists()


def _finding(id_, standard, clause, status, field="", page=None):
    return {"id": id_, "standard": standard, "clause": clause, "field": field,
            "compliance_status": status, "requirement_text": f"{field} requirement text",
            "submittal_page": page}


def test_an_imported_key_scores_sensibly_against_the_runs_own_findings(tmp_path):
    """The whole chain, invented data only: CRS file -> CLI -> drafted key ->
    scorer -> a recall/precision report that names its denominators."""
    _code, out = _drafted_key(tmp_path)
    key = _load_scorable_key(out)

    findings_doc = {"format": rs.FINDINGS_FORMAT, "model": "qwen3.5:4b", "findings": [
        _finding("f1", "SAES-J-600", "8", "NON_COMPLIANT", field="Margin", page=2),
        _finding("f2", "API RP 520 Part I", "5.2", "MISSING_INFORMATION", field="Orifice area", page=4),
        _finding("f3", "SAES-D-901", "4.3", "COMPLIANT"),  # no key item names this: not judged
    ]}
    result = rs.score(key, findings_doc)

    assert result["source"] == "engineer_confirmed" and result["key"] == "invented-vessel"
    assert (result["defects"], result["defects_found"], result["recall"]) == (2, 2, 1.0)
    assert result["false_compliant"] == 0
    assert result["defects_found_without_page"] == 0
    # f3 answers no item; complete_for_flags is False (a draft from one CRS
    # never claims every real defect is listed), so it is not held against
    # precision, only counted apart.
    assert result["complete_for_flags"] is False
    assert result["unmatched_findings"] == 1
    assert result["findings_not_judged_by_key"] == 0


def test_a_defect_the_key_names_but_no_finding_flags_is_missed_by_id_not_silently_dropped(tmp_path):
    _code, out = _drafted_key(tmp_path)
    key = _load_scorable_key(out)
    only_one = {"format": rs.FINDINGS_FORMAT, "findings": [
        _finding("f1", "SAES-J-600", "8", "NON_COMPLIANT", field="Margin", page=2)]}

    result = rs.score(key, only_one)

    assert (result["defects_found"], result["recall"]) == (1, 0.5)
    assert result["missed_ids"] == ["crs-2"]  # named by its drafted id, never a count alone


def test_a_finding_that_calls_a_keyed_defect_compliant_is_a_false_compliant_never_hidden(tmp_path):
    _code, out = _drafted_key(tmp_path)
    key = _load_scorable_key(out)
    bad = {"format": rs.FINDINGS_FORMAT, "findings": [
        _finding("f1", "SAES-J-600", "8", "COMPLIANT", field="Margin", page=2),
        _finding("f2", "API RP 520 Part I", "5.2", "NON_COMPLIANT", field="Orifice area", page=4),
    ]}

    result = rs.score(key, bad)

    assert result["false_compliant"] == 1 and result["false_compliant_ids"] == ["crs-1"]
