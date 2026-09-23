"""Phase 5A: which standards apply, why, and what is missing.

THE TEST THAT MATTERS MOST is
`test_a_semantically_retrieved_standard_does_not_satisfy_a_missing_reference`.
Everything else here is scaffolding around the one failure this phase exists to
prevent: retrieval finding something vaguely related, that thing landing on the
list as "applicable", and a missing standard quietly disappearing so a review
nobody could have performed reads as complete.

Every test goes through `select()` rather than a helper, and asserts something
positive before asserting an absence - honesty-audit entries 6, 11, 13 and 16.
Where a guard is targeted, the test checks that guard is the ONLY thing holding
the behaviour, which is species four.

Mutations: M57-M63, `python scripts/mutation_check.py --phase 6`.
"""

from __future__ import annotations

import uuid

import pytest

from app import applicability, db, keyword, standards, submittal_review
from app.config import settings


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "app.sqlite")
    db.reset_connection(); db.init_db(); submittal_review.ensure_schema()
    keyword.ensure_schema()
    yield
    db.reset_connection()


def _doc(doc_id: str, filename: str, role: str, text: str = "", **meta) -> str:
    with db.connect() as conn:
        conn.execute("""INSERT INTO documents
            (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)
            VALUES (?,?,?,1,?,'ready',1,'2026-09-18T00:00:00Z')""",
            (doc_id, filename, f"sha-{doc_id}", filename))
        columns = ["document_id", "suggested_by", "document_role", *meta]
        values = [doc_id, "test", role, *meta.values()]
        conn.execute(
            f"INSERT INTO document_classification ({','.join(columns)})"
            f" VALUES ({','.join('?' * len(values))})", values)
        conn.execute("""INSERT INTO chunks
            (id,document_id,filename,ordinal,page_start,page_end,section,kind,
             text,token_count,content_hash,retrievable)
            VALUES (?,?,?,0,1,1,NULL,'prose',?,1,?,1)""",
            (f"{doc_id}-c1", doc_id, filename, text or filename,
             f"h-{doc_id}"))
    keyword.index_document(doc_id)
    return doc_id


def _run(submittal_id: str) -> str:
    run_id = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute("""INSERT INTO review_runs
            (id,submittal_document_id,status,created_at,updated_at)
            VALUES (?,?,'pending','2026-09-18T00:00:00Z','2026-09-18T00:00:00Z')""",
            (run_id, submittal_id))
    return run_id


def _scope(*ids): return frozenset(ids)


CITES_610 = ("Pump shall comply with API 610 and NACE MR-0175. "
             "Casing material per ASTM A995.")


# ============================================ rule 1: explicit references

def test_a_standard_named_in_the_datasheet_is_selected_as_referenced():
    """THE MUTATION TARGET (M57)."""
    std = _doc("std_610", "API-610.pdf", "COMPANY_STANDARD",
               document_number="API 610", discipline="Mechanical")
    sub = _doc("sub", "pump-datasheet.pdf", "CONTRACTOR_SUBMITTAL",
               text=CITES_610, discipline="Mechanical", equipment_type="pump")
    result = applicability.select(sub, allowed_document_ids=_scope(std, sub),
                                  persist=False)
    chosen = {s["standard_document_id"]: s for s in result["selected"]}
    assert std in chosen, "a standard the datasheet names was not selected"
    assert chosen[std]["method"] == applicability.METHOD_REFERENCED
    # THE REASON NAMES THE CITATION, not the retrieval.
    assert "API 610" in chosen[std]["reason"]
    # And it is no longer missing.
    missing = {m["identifier"] for m in result["missing_references"]}
    assert "API 610" not in missing


def test_a_one_letter_koc_discipline_code_is_read_as_a_citation():
    """#161: a real KOC pump datasheet's reference list names standards under
    BOTH one-letter (KOC-E-003, electrical) and two-letter (KOC-ME-008,
    mechanical equipment) discipline codes in the same document. Before the
    fix, `referenced_standards` required exactly two letters, so the
    one-letter citations were invisible end to end - not selected as
    referenced, and not reported missing either, because `select()` never
    knew the submittal had cited them at all.
    """
    sub = _doc("sub", "pump.pdf", "CONTRACTOR_SUBMITTAL",
               text="Equipment shall comply with KOC-E-003 and KOC-ME-008.")
    result = applicability.select(sub, allowed_document_ids=_scope(sub),
                                  persist=False)
    assert result["referenced_total"] == 2
    missing = {m["identifier"] for m in result["missing_references"]}
    assert "KOC-E-003" in missing
    assert "KOC-ME-008" in missing


def test_a_citation_of_a_part_matches_the_standard():
    """"API RP 520 Pt-1" cites API RP 520."""
    std = _doc("std_520", "API-RP-520.pdf", "COMPANY_STANDARD",
               document_number="API RP 520")
    sub = _doc("sub", "psv.pdf", "CONTRACTOR_SUBMITTAL",
               text="Design per API RP 520 Pt-1&2.")
    result = applicability.select(sub, allowed_document_ids=_scope(std, sub),
                                  persist=False)
    methods = {s["method"] for s in result["selected"]}
    assert applicability.METHOD_REFERENCED in methods
    assert result["missing_references"] == []


# ======================================= the guard this phase exists for

def test_a_referenced_standard_absent_from_the_library_is_reported_missing():
    """THE MUTATION TARGET (M58). And it lowers completeness."""
    sub = _doc("sub", "pump.pdf", "CONTRACTOR_SUBMITTAL", text=CITES_610)
    result = applicability.select(sub, allowed_document_ids=_scope(sub),
                                  persist=False)
    missing = {m["identifier"] for m in result["missing_references"]}
    # Listed by THE IDENTIFIER THE DATASHEET USED.
    assert "API 610" in missing
    assert "NACE MR-0175" in missing
    assert result["reference_coverage"] == 0.0
    assert result["completeness"] in (0.0, None) or result["completeness"] < 0.5
    # Never silently dropped: the count is reported too.
    assert result["referenced_total"] >= 2


def test_a_semantically_retrieved_standard_does_not_satisfy_a_missing_reference():
    """THE MUTATION TARGET (M59), AND THE POINT OF PHASE 5A.

    A datasheet cites API 610. API 610 is NOT in the library. A different
    standard - same discipline, similar words - is. The similar one may appear
    on the list, but API 610 MUST still be reported missing and completeness
    must still be reduced.

    Without this, a review that could not possibly have been performed reads as
    complete.
    """
    # In the library: a mechanical standard that is NOT API 610.
    other = _doc("std_other", "NORSOK-M-501.pdf", "COMPANY_STANDARD",
                 document_number="NORSOK M-501", discipline="Mechanical",
                 text="Pump coating surface preparation shall comply.")
    sub = _doc("sub", "pump.pdf", "CONTRACTOR_SUBMITTAL", text=CITES_610,
               discipline="Mechanical")
    result = applicability.select(sub, allowed_document_ids=_scope(other, sub),
                                  persist=False)

    # POSITIVE FIRST: the other standard WAS found, so the test is standing
    # where the guard can fail it. If nothing were selected, this test would
    # pass for the wrong reason.
    assert result["selected"], "nothing was selected, so the guard is untested"
    chosen = {s["standard_document_id"] for s in result["selected"]}
    assert other in chosen

    # AND THE MISSING REFERENCE IS STILL MISSING.
    missing = {m["identifier"] for m in result["missing_references"]}
    assert "API 610" in missing, \
        "a retrieved standard was allowed to cover a missing citation"
    assert result["reference_coverage"] == 0.0
    # No selected row claims to satisfy a reference it does not.
    for row in result["selected"]:
        if row["method"] != applicability.METHOD_REFERENCED:
            assert row.get("satisfies_reference") is not True


def test_a_weaker_rule_never_overrides_a_citation():
    """A standard both cited AND discipline-matched is recorded as CITED."""
    std = _doc("std_610", "API-610.pdf", "COMPANY_STANDARD",
               document_number="API 610", discipline="Mechanical")
    sub = _doc("sub", "pump.pdf", "CONTRACTOR_SUBMITTAL", text=CITES_610,
               discipline="Mechanical")
    result = applicability.select(sub, allowed_document_ids=_scope(std, sub),
                                  persist=False)
    row = next(s for s in result["selected"] if s["standard_document_id"] == std)
    assert row["method"] == applicability.METHOD_REFERENCED


# ================================================ the other selection rules

def test_equipment_discipline_and_service_each_select_with_their_own_method():
    equip = _doc("std_eq", "pumps.pdf", "COMPANY_STANDARD", equipment_type="pump")
    disc = _doc("std_di", "mech.pdf", "COMPANY_STANDARD", discipline="Mechanical")
    serv = _doc("std_sv", "sour.pdf", "COMPANY_STANDARD", service="sour")
    sub = _doc("sub", "s.pdf", "CONTRACTOR_SUBMITTAL", equipment_type="pump",
               discipline="Mechanical", service="sour")
    result = applicability.select(
        sub, allowed_document_ids=_scope(equip, disc, serv, sub), persist=False)
    by_id = {s["standard_document_id"]: s["method"] for s in result["selected"]}
    assert by_id[equip] == applicability.METHOD_EQUIPMENT
    assert by_id[disc] == applicability.METHOD_DISCIPLINE
    assert by_id[serv] == applicability.METHOD_SERVICE


def test_a_null_attribute_on_either_side_is_not_a_match():
    """"Neither has a discipline recorded" is not evidence they belong
    together."""
    std = _doc("std", "s.pdf", "COMPANY_STANDARD")          # no attributes
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL")      # none either
    result = applicability.select(sub, allowed_document_ids=_scope(std, sub),
                                  persist=False)
    methods = {s["method"] for s in result["selected"]}
    assert applicability.METHOD_DISCIPLINE not in methods
    assert applicability.METHOD_EQUIPMENT not in methods


def test_zero_applicable_standards_is_a_valid_answer():
    """On this repository's real corpus it is the CORRECT answer."""
    sub = _doc("sub", "pump.pdf", "CONTRACTOR_SUBMITTAL", text=CITES_610)
    result = applicability.select(sub, allowed_document_ids=_scope(sub),
                                  persist=False)
    assert result["selected"] == []
    assert result["library_size"] == 0
    # Not an error, and the missing references are still reported.
    assert result["missing_references"]


# ============================================ supersession, exclusions, audit

def test_a_superseded_standard_is_not_selected_but_stays_readable():
    """THE MUTATION TARGET (M60). The 3A rule, reused."""
    old = _doc("std_old", "API-610-2019.pdf", "COMPANY_STANDARD",
               document_number="API 610", discipline="Mechanical")
    new = _doc("std_new", "API-610-2021.pdf", "COMPANY_STANDARD",
               document_number="API 610 R2", discipline="Mechanical")
    sub = _doc("sub", "pump.pdf", "CONTRACTOR_SUBMITTAL", text=CITES_610,
               discipline="Mechanical")
    scope = _scope(old, new, sub)

    # POSITIVE FIRST: while current, the old revision IS selectable.
    before = applicability.select(sub, allowed_document_ids=scope, persist=False)
    assert old in {s["standard_document_id"] for s in before["selected"]}

    standards.supersede(old, new, allowed_document_ids=scope)
    after = applicability.select(sub, allowed_document_ids=scope, persist=False)
    assert old not in {s["standard_document_id"] for s in after["selected"]}
    # STILL READABLE - a different question from selectable.
    assert old in {r["id"] for r in standards.list_standards(
        allowed_document_ids=scope)}


def test_a_considered_standard_that_did_not_match_keeps_its_exclusion_reason():
    """THE MUTATION TARGET (M61). "We looked and it did not apply"."""
    unrelated = _doc("std_x", "civil.pdf", "COMPANY_STANDARD",
                     discipline="Civil")
    sub = _doc("sub", "pump.pdf", "CONTRACTOR_SUBMITTAL",
               discipline="Mechanical")
    run = _run(sub)
    scope = _scope(unrelated, sub)
    applicability.select(sub, allowed_document_ids=scope, review_run_id=run)

    rows = applicability.applicable_standards(run, allowed_document_ids=scope)
    excluded = [r for r in rows if r["included"] == 0]
    assert excluded, "a standard considered and passed over was not recorded"
    assert excluded[0]["standard_document_id"] == unrelated
    assert excluded[0]["exclusion_reason"], "an excluded standard must say why"


def test_a_selection_without_a_reason_is_refused():
    std = _doc("std", "s.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL")
    run = _run(sub)
    with pytest.raises(applicability.ApplicabilityError):
        applicability.record_selection(
            review_run_id=run, standard_document_id=std,
            method=applicability.METHOD_SEMANTIC, reason="   ")
    with pytest.raises(applicability.ApplicabilityError):
        applicability.record_selection(
            review_run_id=run, standard_document_id=std,
            method="telepathy", reason="because")
    with pytest.raises(applicability.ApplicabilityError):
        applicability.record_selection(
            review_run_id=run, standard_document_id=std,
            method=applicability.METHOD_SEMANTIC, reason="x", included=False)


def test_confidence_is_never_high():
    """CLAUDE.md rule 4. Even an explicit citation stops at 0.9."""
    std = _doc("std", "s.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL")
    run = _run(sub)
    row = applicability.record_selection(
        review_run_id=run, standard_document_id=std,
        method=applicability.METHOD_REFERENCED, reason="cited",
        confidence=1.0)
    assert row["confidence"] <= 0.9
    weak = applicability.record_selection(
        review_run_id=run, standard_document_id=std,
        method=applicability.METHOD_SEMANTIC, reason="retrieved",
        confidence=0.99)
    assert weak["confidence"] <= 0.4


def test_an_engineer_override_writes_an_audit_row():
    """THE MUTATION TARGET (M62). A reason is required."""
    std = _doc("std", "s.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL")
    run = _run(sub)
    scope = _scope(std, sub)

    row = applicability.override(
        run, std, include=True, reason="applies by project agreement",
        allowed_document_ids=scope, actor={"id": None, "email": "e@x.test"})
    assert row["selection_method"] == applicability.METHOD_MANUAL
    assert row["included"] == 1

    audit = db.connect().execute(
        "SELECT * FROM audit_events WHERE action = 'review.applicability_override'"
    ).fetchone()
    assert audit is not None, "an override wrote no audit row"
    assert std in (audit["detail"] or "")

    with pytest.raises(applicability.ApplicabilityError):
        applicability.override(run, std, include=False, reason="  ",
                               allowed_document_ids=scope)


def test_an_override_cannot_name_a_standard_the_caller_cannot_read():
    secret = _doc("std_secret", "s.pdf", "COMPANY_STANDARD")
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL")
    run = _run(sub)
    with pytest.raises(applicability.ApplicabilityError):
        applicability.override(run, secret, include=True, reason="x",
                               allowed_document_ids=_scope(sub))


# ================================================================ permissions

def test_an_unauthorised_caller_sees_no_applicable_standards_for_a_run():
    """THE MUTATION TARGET (M63)."""
    std = _doc("std", "s.pdf", "COMPANY_STANDARD", discipline="Mechanical")
    mine = _doc("sub_mine", "m.pdf", "CONTRACTOR_SUBMITTAL", discipline="Mechanical")
    theirs = _doc("sub_theirs", "t.pdf", "CONTRACTOR_SUBMITTAL",
                  discipline="Mechanical")
    their_run = _run(theirs)
    applicability.select(theirs, allowed_document_ids=_scope(std, theirs),
                         review_run_id=their_run)

    # POSITIVE FIRST: the rows exist and their owner can read them.
    assert applicability.applicable_standards(
        their_run, allowed_document_ids=_scope(std, theirs))
    # And a caller granted only their own submittal sees nothing.
    assert applicability.applicable_standards(
        their_run, allowed_document_ids=_scope(mine)) == []


def test_reading_a_submittal_does_not_grant_the_standards_it_cites():
    std = _doc("std", "s.pdf", "COMPANY_STANDARD", discipline="Mechanical")
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL", discipline="Mechanical")
    run = _run(sub)
    applicability.select(sub, allowed_document_ids=_scope(std, sub),
                         review_run_id=run)
    # Granted the submittal but NOT the standard: the row is filtered out.
    rows = applicability.applicable_standards(run, allowed_document_ids=_scope(sub))
    assert all(r["standard_document_id"] != std for r in rows)


def test_an_empty_grant_set_selects_nothing():
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL", text=CITES_610)
    result = applicability.select(sub, allowed_document_ids=frozenset(),
                                  persist=False)
    assert result["selected"] == []
    assert result["library_size"] == 0
    # The submittal's own text is unreadable too, so nothing is claimed about
    # what it cites.
    assert result["referenced_total"] == 0


@pytest.mark.parametrize("call", [
    lambda: applicability.select("d"),
    lambda: applicability.applicable_standards("r"),
    lambda: applicability.override("r", "s", include=True, reason="x"),
])
def test_a_caller_that_forgets_the_filter_raises_typeerror(call):
    with pytest.raises(TypeError):
        call()


# ================================================================ persistence

def test_the_selection_is_written_to_the_phase_1_relation():
    """`review_applicable_standards`, filled at last - not a second table."""
    std = _doc("std", "s.pdf", "COMPANY_STANDARD", discipline="Mechanical")
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL", discipline="Mechanical")
    run = _run(sub)
    applicability.select(sub, allowed_document_ids=_scope(std, sub),
                         review_run_id=run)
    rows = db.connect().execute(
        "SELECT * FROM review_applicable_standards WHERE review_run_id = ?",
        (run,)).fetchall()
    assert rows, "the phase 1 relation is still empty"
    row = next(r for r in rows if r["standard_document_id"] == std)
    assert row["selection_method"] == applicability.METHOD_DISCIPLINE
    assert row["selection_reason"]
    assert row["confidence"] <= 0.5
    # And no second table appeared.
    tables = {r[0] for r in db.connect().execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    for forbidden in ("applicable_standards", "standard_selection",
                      "review_standards"):
        assert forbidden not in tables


def test_re_running_selection_does_not_duplicate_rows():
    std = _doc("std", "s.pdf", "COMPANY_STANDARD", discipline="Mechanical")
    sub = _doc("sub", "d.pdf", "CONTRACTOR_SUBMITTAL", discipline="Mechanical")
    run = _run(sub)
    scope = _scope(std, sub)
    applicability.select(sub, allowed_document_ids=scope, review_run_id=run)
    applicability.select(sub, allowed_document_ids=scope, review_run_id=run)
    count = db.connect().execute(
        "SELECT COUNT(*) FROM review_applicable_standards"
        " WHERE review_run_id = ? AND standard_document_id = ?",
        (run, std)).fetchone()[0]
    assert count == 1


# =============================== which cited standards the library lacks
#
# FOUND 2026-09-19, by fact-checking a demo script against the database. The
# dashboard and the CRS each checked "is this cited standard missing?" by
# comparing an IDENTIFIER against a dict keyed by DOCUMENT ID, so the answer
# was always yes: 15 of 15 on the drum sheet, when six are in the library.
# No test had ever cited a standard that IS in the library, so the "not
# missing" direction was never exercised - these are those tests.

from app.applicability import missing_references  # noqa: E402

_LIBRARY = [
    {"id": "doc_l132", "filename": "SAES-L-132.pdf", "document_number": None},
    {"id": "doc_a133", "filename": "SAES-A-133.pdf", "document_number": None},
    {"id": "doc_api520", "filename": "x.pdf", "document_number": "API RP 520"},
]


def test_a_cited_standard_the_library_holds_is_not_missing():
    """THE DIRECTION NOTHING TESTED. Before the fix this returned both."""
    assert missing_references(_LIBRARY, ["SAES-L-132", "32-SAMSS-004"]) \
        == ["32-SAMSS-004"]


def test_a_standard_missing_from_the_library_is_reported_in_its_own_spelling():
    assert missing_references(_LIBRARY, ["32-SAMSS-004"]) == ["32-SAMSS-004"]


def test_two_spellings_of_one_held_standard_are_both_matched():
    """WHY IT ASKS PER NAME. `_match_referenced` is keyed by DOCUMENT, so two
    citations that reach the same standard collide in one combined result and
    only the last one's identifier survives. Read identifiers back out of
    that and the other citation is reported missing - the same defect, one
    level down.

    THE EXAMPLE MATTERS, and the first one chosen was wrong. "SAES-L-132" vs
    "SAES L 132" normalise to the SAME key, so the survivor still matches
    both, and mutation M250 reported NOT DETECTED - correctly. The collision
    only loses a citation when two DIFFERENT keys reach one standard, which
    the prefix rule allows: "API RP 520 Pt-1" and "API RP 520" are both the
    standard numbered API RP 520. Order matters too - the second overwrites
    the first, so the first is the one that would be lost.
    """
    assert missing_references(_LIBRARY, ["SAES-L-132", "SAES L 132"]) == []
    assert missing_references(_LIBRARY, ["API RP 520 Pt-1", "API RP 520"]) == []


def test_a_citation_of_part_of_a_held_standard_is_not_missing():
    """The prefix rule selection already uses: "API RP 520 Pt-1" cites the
    standard numbered "API RP 520". Asked of the same matcher, so the two
    cannot disagree about what counts as held."""
    assert missing_references(_LIBRARY, ["API RP 520 Pt-1"]) == []


def test_each_missing_standard_is_reported_once():
    assert missing_references(
        _LIBRARY, ["32-SAMSS-004", "32 SAMSS 004", "32-SAMSS-004"]) \
        == ["32-SAMSS-004"]


def test_an_empty_library_reports_everything_cited():
    assert missing_references([], ["SAES-L-132", "32-SAMSS-004"]) \
        == ["SAES-L-132", "32-SAMSS-004"]
