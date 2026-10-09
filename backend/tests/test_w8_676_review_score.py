"""#676: the review scorer. Every document, standard and finding here is INVENTED.

Mutations: M4438-M4466 (scripts/mutations/w8_676_review_score.py).
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

from app import db, review, review_score as rs
from app.config import settings

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import review_score as cli  # noqa: E402

KEY = json.loads((REPO / "eval" / "review" / "keys" / "invented-pump.json").read_text(encoding="utf-8"))
STD = "STD-PUMP-001.pdf"
SECRET = "UNIQUE-PHRASE-XYZ"


def f(clause, status, field="", std=STD, text=None, **extra):
    return {"id": f"f-{clause}-{status}", "standard": std, "clause": clause, "field": field,
            "compliance_status": status, "requirement_text": text or f"{field} shall be stated. {SECRET}",
            **extra}


def doc(*findings, model="m1"):
    return {"format": rs.FINDINGS_FORMAT, "model": model, "findings": list(findings)}


BASE = doc(
    f("4.2.1", "NON_COMPLIANT", "design pressure"),     # D1 found (a subclause of 4.2)
    f("6.3", "COMPLIANT", "flow"),                      # M1 right
    f("7.1", "NON_COMPLIANT", "head"),                  # T1: a trap flagged
    f("9.4", "NOT_APPLICABLE", "turbine"),              # N1 right
    f("8.8", "NON_COMPLIANT", "noise"),                 # matches no item
)


def key(**over):
    k = copy.deepcopy(KEY)
    k.update(over)
    return k


# ------------------------------------------------------------------ the numbers

def test_a_run_with_known_answers_gets_the_right_numbers():
    r = rs.score(KEY, BASE)
    assert (r["defects"], r["defects_found"], r["recall"]) == (2, 1, 0.5)
    assert r["missed_ids"] == ["D2"]
    # judged: D1 ok, M1 ok, T1 wrong, N1 ok, the 8.8 flag wrong (the key is complete_for_flags)
    assert (r["judged_findings"], r["correct_findings"]) == (5, 3)
    assert r["precision"] == pytest.approx(0.6)
    assert (r["traps"], r["traps_flagged"], r["trap_false_flag_rate"]) == (1, 1, 1.0)
    assert r["false_compliant"] == 0 and r["false_not_applicable"] == 0


def test_a_defect_called_compliant_is_a_false_compliant_and_blocks():
    bad = doc(f("4.2", "COMPLIANT", "design pressure"))
    r = rs.score(KEY, bad)
    assert r["false_compliant"] == 1 and r["false_compliant_ids"] == ["D1"]
    assert r["defects_found"] == 0                                    # COMPLIANT is not "found"
    assert (r["judged_findings"], r["correct_findings"], r["precision"]) == (1, 0, 0.0)   # and not correct
    reasons = rs.check(r, rs.load_baseline("/nonexistent"))
    assert reasons and "called COMPLIANT" in reasons[0] and "D1" in reasons[0]


def test_a_requirement_called_not_applicable_that_applies_is_a_false_not_applicable():
    r = rs.score(KEY, doc(f("5.1", "NOT_APPLICABLE", "material"), f("6.3", "NOT_APPLICABLE", "flow")))
    assert r["false_not_applicable"] == 2
    assert r["false_not_applicable_ids"] == ["D2", "M1"]


def test_recall_counts_every_kind_of_flag_as_found():
    for status in ("NON_COMPLIANT", "MISSING_INFORMATION", "CONDITIONAL", "NEEDS_ENGINEER_REVIEW"):
        assert rs.score(KEY, doc(f("5.1", status, "material")))["defects_found"] == 1
    assert rs.score(KEY, doc(f("5.1", "NOT_IN_DOCUMENT_SCOPE", "material")))["defects_found"] == 0


def test_no_defects_in_the_key_means_no_recall_never_100_percent():
    only_met = key(items=[i for i in KEY["items"] if i["kind"] == "met"])
    assert rs.score(only_met, doc())["recall"] is None
    assert rs.score(KEY, doc())["precision"] is None                # nothing judged: no percentage


# ------------------------------------------------------------------- matching

@pytest.mark.parametrize("finding_clause, item_clause, expected", [
    ("4.2", "4.2", True), ("4.2.1", "4.2", True), ("4.20", "4.2", False), ("4", "4.2", False), ("", "4.2", False)])
def test_a_subclause_matches_its_parent_and_nothing_else(finding_clause, item_clause, expected):
    assert rs._clause_under(finding_clause, item_clause) is expected


def test_the_standard_must_match():
    assert rs.match_item(f("4.2", "NON_COMPLIANT", "design pressure", std="OTHER-STD.pdf"), KEY["items"]) is None
    assert rs.match_item(f("4.2", "NON_COMPLIANT", "design pressure", std="std-pump-001 rev B.pdf"),
                         KEY["items"])["id"] == "D1"
    number_only = f("4.2", "NON_COMPLIANT", "design pressure", std="renamed.pdf", standard_number="STD-PUMP-001")
    assert rs.match_item(number_only, KEY["items"])["id"] == "D1"


def test_the_field_words_must_appear_and_the_most_specific_item_wins():
    items = [{"id": "G", "kind": "met", "standard": "S", "clause": "4"},
             {"id": "S", "kind": "defect", "standard": "S", "clause": "4.2"},
             {"id": "F", "kind": "defect", "standard": "S", "clause": "4", "field": "design pressure"}]
    hit = rs.match_item(f("4.2", "NON_COMPLIANT", "design pressure", std="S"), items)
    assert hit["id"] == "F"                                          # a field outranks a longer clause
    assert rs.match_item(f("4.2", "NON_COMPLIANT", "noise", std="S", text="noise only"), items)["id"] == "S"
    assert rs.match_item(f("4.9", "NON_COMPLIANT", "noise", std="S", text="noise only"), items)["id"] == "G"


def test_a_flag_no_item_matches_is_not_judged_unless_the_key_covers_the_whole_sheet():
    r = rs.score(key(complete_for_flags=False), BASE)
    assert r["judged_findings"] == 4 and r["findings_not_judged_by_key"] == 1
    assert r["precision"] == pytest.approx(3 / 4)
    full = rs.score(key(complete_for_flags=True), BASE)
    assert full["judged_findings"] == 5 and full["findings_not_judged_by_key"] == 0


def test_a_finding_with_another_status_is_counted_apart_and_not_in_precision():
    r = rs.score(KEY, doc(f("4.2", "NOT_IN_DOCUMENT_SCOPE", "design pressure")))
    assert r["findings_other_status"] == 1 and r["judged_findings"] == 0


# ------------------------------------------------------------------- citations

def test_a_citation_is_valid_only_when_the_cited_page_and_clause_contain_the_requirement():
    finding = f("4.2", "NON_COMPLIANT", text="The design pressure shall be at least 12 bar.")
    page = "4.2 Design\nThe design   pressure shall be at least 12 bar.\n"
    assert rs.citation_valid(finding, page) is True
    assert rs.citation_valid(finding, "A different page about noise.") is False
    assert rs.citation_valid(finding, "The design pressure shall be at least 12 bar.") is False   # clause 4.2 absent
    assert rs.citation_valid(finding, None) is None                                               # not checked
    assert rs.citation_valid(f("4.2", "NON_COMPLIANT", text=""), page) is False


def test_a_table_row_cited_cell_by_cell_is_valid_when_every_cell_is_on_the_page():
    row = f("4.2", "NON_COMPLIANT", text="UNS S31600 | Max hardness | 22")
    assert rs.citation_valid(row, "4.2 Table\nUNS S31600  Max hardness (HRC)  22") is True
    assert rs.citation_valid(row, "4.2 Table\nUNS S31600  Max hardness (HRC)  99") is False


def test_citation_validity_is_not_checked_without_page_text_never_100_percent():
    r = rs.score(KEY, BASE)
    assert r["citation_validity"] is None and r["citations_checked"] == 0
    assert "not checked" in r["citations_checked_note"]
    assert "NOT CHECKED" in cli.text_report(r)


def test_citation_validity_uses_the_page_lookup_or_the_stored_verdict():
    pages = {("d", 1): "4.2 The design pressure shall be at least 12 bar.", ("d", 2): "nothing relevant"}
    fs = [f("4.2", "NON_COMPLIANT", text="design pressure shall be at least 12 bar", standard_document_id="d", page=1),
          f("5.1", "NON_COMPLIANT", text="material shall be stated", standard_document_id="d", page=2)]
    r = rs.score(KEY, doc(*fs), page_lookup=lambda d, p: pages.get((d, p)))
    assert (r["citations_checked"], r["citations_valid"]) == (2, 1)
    stored = rs.score(KEY, doc(f("4.2", "NON_COMPLIANT", citation_valid=True),
                               f("5.1", "NON_COMPLIANT", citation_valid=False),
                               f("6.3", "COMPLIANT", citation_valid=None)))
    assert (stored["citations_checked"], stored["citations_valid"]) == (2, 1)       # null is not counted


# ------------------------------------------------------- baseline, gate, bar

def _baseline(**entry):
    r = rs.score(KEY, BASE)
    return {"margin": 0.05, "baselines": {rs.baseline_key(r): {"recall": 0.5, "precision": 0.6,
                                                              "citation_validity": None, **entry}}}


def test_a_merge_that_lowers_recall_or_precision_by_more_than_the_margin_is_blocked():
    worse = rs.score(KEY, doc(f("9.4", "NOT_APPLICABLE", "turbine")))               # recall 0
    why = rs.check(worse, _baseline())
    assert any(w.startswith("recall fell from 50% to 0%") for w in why)
    assert rs.check(rs.score(KEY, BASE), _baseline()) == []                          # equal: passes
    close = _baseline(recall=0.54)
    assert rs.check(rs.score(KEY, BASE), close) == []                                # within the margin


def test_precision_and_citation_validity_are_gated_too():
    r = rs.score(KEY, BASE)
    assert any("precision fell" in w for w in rs.check(r, _baseline(precision=0.9)))
    lower = rs.score(KEY, doc(f("4.2", "NON_COMPLIANT", citation_valid=False)))
    base = {"margin": 0.05, "baselines": {rs.baseline_key(lower): {"citation_validity": 1.0}}}
    assert any("citation_validity fell" in w for w in rs.check(lower, base))


def test_a_number_that_can_no_longer_be_computed_blocks_instead_of_passing():
    empty = rs.score(KEY, doc())
    assert any("cannot be computed" in w for w in rs.check(empty, _baseline()))


def test_a_false_compliant_blocks_even_with_no_baseline():
    r = rs.score(KEY, doc(f("4.2", "COMPLIANT", "design pressure")))
    assert rs.check(r, {"margin": 0.05, "baselines": {}})


def test_the_baseline_is_kept_per_model_and_key():
    a = rs.score(KEY, doc(model="small"))
    b = rs.score(KEY, doc(model="mac-studio"))
    assert rs.baseline_key(a) != rs.baseline_key(b)
    base = {"margin": 0.05, "baselines": {rs.baseline_key(a): {"recall": 1.0}}}
    assert rs.check(a, base)                                                          # compared with its own
    assert rs.check(b, base) == []                                                    # the other model has no baseline


def test_each_number_is_shown_against_the_proposed_bar_and_unknowns_are_unknown():
    s = rs.bar_status(rs.score(KEY, BASE))
    assert s == {"recall": False, "trap_false_flag_rate": False, "false_compliant": True, "citations_valid": None}
    good = rs.score(key(items=[i for i in KEY["items"] if i["id"] in ("D1", "T1")]),
                    doc(f("4.2", "NON_COMPLIANT", "design pressure"), f("7.1", "COMPLIANT", "head"),
                        f("4.2", "NON_COMPLIANT", citation_valid=True)))
    assert rs.bar_status(good) == {"recall": True, "trap_false_flag_rate": True, "false_compliant": True,
                                   "citations_valid": True}


# ------------------------------------------------------------- the key itself

@pytest.mark.parametrize("bad, why", [
    ({"format": "x"}, "format"),
    ({"source": "magic"}, "source"),
    ({"source": "engineer_confirmed"}, "approved_by"),
    ({"items": []}, "no items"),
    ({"items": [{"id": "A", "kind": "defect", "standard": "S", "clause": "1"},
                {"id": "A", "kind": "defect", "standard": "S", "clause": "2"}]}, "unique id"),
    ({"items": [{"id": "A", "kind": "bad", "standard": "S", "clause": "1"}]}, "kind"),
    ({"items": [{"id": "A", "kind": "defect", "standard": "", "clause": "1"}]}, "standard and clause"),
])
def test_an_unusable_key_is_refused_with_the_reason(bad, why):
    with pytest.raises(rs.KeyError_) as err:
        rs.validate_key(key(**bad))
    assert why in str(err.value)


def test_an_engineer_confirmed_key_names_its_engineer():
    rs.validate_key(key(source="engineer_confirmed", approved_by="A. Engineer"))
    with pytest.raises(rs.KeyError_):
        rs.validate_key(key(source="engineer_confirmed", approved_by="  "))


def test_the_findings_file_must_have_its_format(tmp_path):
    p = tmp_path / "f.json"
    p.write_text("{}", encoding="utf-8")
    with pytest.raises(rs.KeyError_):
        rs.load_findings(p)
    p.write_text("not json", encoding="utf-8")
    with pytest.raises(rs.KeyError_):
        rs.load_findings(p)


def test_the_shipped_files_are_valid():
    rs.validate_key(KEY)
    base = rs.load_baseline(REPO / "eval" / "review" / "baseline.json")
    assert base["baselines"] == {} and base["bar"]["false_compliant"] == 0
    assert json.loads((REPO / "eval" / "review" / "answer_key.schema.json").read_text())["required"]
    assert "hidden" not in json.dumps(KEY).lower()


# ------------------------------------------------------- export, CLI, weekly

@pytest.fixture
def live_like_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "score.sqlite")
    db.reset_connection(); db.init_db(); review.ensure_schema()
    with db.connect() as conn:
        conn.execute("INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)"
                     " VALUES ('std',?,'h',1,'p','ready',2,'2026-10-09T00:00:00Z')", (STD,))
        conn.execute("INSERT INTO pages (document_id,page_no,text,char_count,batch_no) VALUES"
                     " ('std',1,'4.2 The design pressure shall be at least 12 bar.',50,0),"
                     " ('std',2,'something else entirely',20,0)")
        for fid, clause, page, status, text in (
                ("a", "4.2", 1, "NON_COMPLIANT", "design pressure shall be at least 12 bar"),
                ("b", "5.1", 2, "MISSING_INFORMATION", "material shall be stated")):
            conn.execute(
                "INSERT INTO review_findings (id,document_id,category,severity,requirement,finding,required_action,"
                "created_at,updated_at,review_run_id,compliance_status,standard_document_id,standard_clause,"
                "standard_page,requirement_source_text,matched_phrase) VALUES (?, 'std','c','s','r','f','a',"
                "'2026-10-09T00:00:00Z','2026-10-09T00:00:00Z','run1',?, 'std',?,?,?,?)",
                (fid, status, clause, page, text, "design pressure" if fid == "a" else "material"))
    db.reset_connection()
    return tmp_path / "score.sqlite"


def test_export_reads_the_findings_and_checks_each_citation_against_the_stored_page(live_like_db, tmp_path):
    out = tmp_path / "run.findings.json"
    assert cli.main(["export", "--db", str(live_like_db), "--run", "run1", "--out", str(out), "--model", "m9"]) == 0
    exported = json.loads(out.read_text(encoding="utf-8"))
    assert exported["model"] == "m9" and len(exported["findings"]) == 2
    by_clause = {x["clause"]: x for x in exported["findings"]}
    assert by_clause["4.2"]["citation_valid"] is True and by_clause["4.2"]["standard"] == STD
    assert by_clause["5.1"]["citation_valid"] is False
    scored = rs.score(KEY, rs.load_findings(out))
    assert scored["defects_found"] == 2 and (scored["citations_checked"], scored["citations_valid"]) == (2, 1)


def test_export_opens_the_database_read_only(live_like_db, tmp_path):
    before = live_like_db.read_bytes()
    cli.main(["export", "--db", str(live_like_db), "--run", "run1", "--out", str(tmp_path / "o.json")])
    conn = cli._open_readonly(str(live_like_db))
    with pytest.raises(Exception):
        conn.execute("DELETE FROM review_findings")
    conn.close()
    assert live_like_db.read_bytes() == before


def _write(path: Path, data) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_score_and_check_commands(tmp_path, capsys):
    k, fnd = _write(tmp_path / "k.json", KEY), _write(tmp_path / "f.json", BASE)
    b = tmp_path / "base.json"
    assert cli.main(["score", "--key", str(k), "--findings", str(fnd), "--baseline", str(b)]) == 0
    assert "recall:            1 of 2 (50%)" in capsys.readouterr().out
    assert cli.main(["check", "--key", str(k), "--findings", str(fnd), "--baseline", str(b)]) == 0
    assert "no baseline stored" in capsys.readouterr().out
    assert cli.main(["record-baseline", "--key", str(k), "--findings", str(fnd), "--baseline", str(b)]) == 0
    stored = json.loads(b.read_text())
    assert stored["baselines"]["m1|invented-pump"]["recall"] == 0.5
    worse = _write(tmp_path / "w.json", doc(f("9.4", "NOT_APPLICABLE", "turbine")))
    assert cli.main(["check", "--key", str(k), "--findings", str(worse), "--baseline", str(b)]) == 1
    assert "BLOCKED" in capsys.readouterr().out
    bad = _write(tmp_path / "bad.json", {"format": "nope"})
    assert cli.main(["score", "--key", str(bad), "--findings", str(fnd)]) == 2


def _weekly_setup(tmp_path):
    keys, runs = tmp_path / "keys", tmp_path / "runs"
    keys.mkdir(); runs.mkdir()
    _write(keys / "invented-pump.json", KEY)
    _write(keys / "no-run.json", key(name="no-run"))
    _write(keys / "exam.json", key(name="exam", source="hidden_exam"))
    _write(keys / "broken.json", {"format": "x"})
    _write(runs / "invented-pump.findings.json", BASE)
    _write(runs / "exam.findings.json", BASE)
    return keys, runs


def test_the_weekly_report_is_counts_only_lists_what_it_could_not_score_and_skips_the_hidden_exam(tmp_path):
    keys, runs = _weekly_setup(tmp_path)
    text, code = cli.weekly_report(keys, runs, rs.load_baseline("/none"), "2026-W41")
    assert code == 0
    assert "## Review score, week 2026-W41" in text
    assert "| invented-pump (invented) | m1 | 1 of 2 (50%) | 3 of 5 (60%) | 0 | 0 | 1 of 1 (100%) | not checked |" in text
    assert "Keys with no run this week (not scored, no number given): no-run." in text
    assert "1 hidden-exam key(s) skipped: scored only by the merger session (#650)." in text
    assert "| exam" not in text and "(hidden_exam)" not in text                          # never in the table
    assert "Key not usable: broken.json" in text
    assert "invented keys prove the scorer, not the system" in text
    assert "Proposed bar (owner to confirm, not measured)" in text
    assert SECRET not in text and STD not in text and "design pressure" not in text      # counts, never document text


def test_the_weekly_report_fails_the_gate_on_a_false_compliant(tmp_path):
    keys, runs = _weekly_setup(tmp_path)
    _write(runs / "invented-pump.findings.json", doc(f("4.2", "COMPLIANT", "design pressure")))
    text, code = cli.weekly_report(keys, runs, rs.load_baseline("/none"), "2026-W41")
    assert code == 1 and "**FAIL**" in text and "D1" in text


def test_the_weekly_report_with_nothing_to_score_passes_nothing(tmp_path):
    (tmp_path / "keys").mkdir(); (tmp_path / "runs").mkdir()
    text, code = cli.weekly_report(tmp_path / "keys", tmp_path / "runs", rs.load_baseline("/none"), "w")
    assert code == 0 and "No key was scored this week." in text
    assert "nothing scored, so nothing passes or fails" in text


def test_the_weekly_command_refuses_a_keys_folder_in_the_hidden_exam_and_reads_nothing_there(tmp_path, capsys, monkeypatch):
    hidden = tmp_path / "Hidden-Exam" / "keys"
    hidden.mkdir(parents=True)
    _write(hidden / "k.json", KEY)
    touched: list[str] = []
    real_glob = Path.glob
    monkeypatch.setattr(Path, "glob", lambda self, pat: (touched.append(str(self)), real_glob(self, pat))[1])
    code = cli.main(["weekly", "--keys-dir", str(hidden), "--runs-dir", str(tmp_path)])
    assert code == 2 and "REFUSED" in capsys.readouterr().out
    assert not [t for t in touched if "hidden-exam" in t.lower()]                       # it never even listed it


def test_nothing_defaults_to_the_hidden_exam():
    assert cli.DEFAULT_KEYS == REPO / "eval" / "review" / "keys"
    for text in ((REPO / "scripts" / "review_score.py").read_text(encoding="utf-8").splitlines()
                 + (REPO / "backend" / "app" / "review_score.py").read_text(encoding="utf-8").splitlines()):
        code = text.split("#")[0]
        assert not ("hidden-exam" in code.lower() and ("Path(" in code or "open(" in code or "glob(" in code)), text


def test_the_weekly_week_label_defaults_to_the_iso_week(tmp_path, capsys):
    keys, runs = _weekly_setup(tmp_path)
    assert cli.main(["weekly", "--keys-dir", str(keys), "--runs-dir", str(runs),
                     "--baseline", str(tmp_path / "none.json"), "--out", str(tmp_path / "w.md")]) == 0
    import re
    assert re.search(r"week \d{4}-W\d{2}", (tmp_path / "w.md").read_text())
