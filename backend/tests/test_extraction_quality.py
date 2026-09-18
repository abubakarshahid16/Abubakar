"""What the extractor stores, and what it refuses to store.

Every number quoted here was MEASURED on five real SAES standards before the
fixes below existed. They are not illustrative:

  * 22 of 44 numeric_limit rows had a NULL value, because "g/L." with the
    sentence's full stop attached is not "g/L", and because `m` and `inch`
    were recognised as lengths but had no conversion.
  * `raw_unit` held 'locations', 'print', 'times' and 'day' - the word after a
    number, kept as a unit because the document said it.
  * 38 of 718 rows (5.3%) carried the running page footer INSIDE the
    requirement text, in a system whose entire claim is that it quotes the
    document.
  * 54 rows (7.1%) were byte-identical duplicates of another row.

THE ONE THING THIS FILE MUST NOT DO is let `subject` become `field`. `field` is
the join key `comparison._match_fact` reads, by exact equality against a
datasheet caption; `subject` is a descriptive phrase for a human. The test that
guards it asserts `field` stays NULL on a row whose `subject` is populated -
not because NULL is good, but because a populated `field` that matches nothing
would hide the fact that no requirement is comparable yet.
"""

from __future__ import annotations

import pytest

from app import claims, db, requirements_3b, standards
from app.config import settings
from app.db import connect

NOW = "2026-09-19T00:00:00Z"


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    yield
    db.reset_connection()


def _standard(doc_id: str, *chunks: tuple[str, str]) -> str:
    """A COMPANY_STANDARD with `(section, text)` chunks."""
    with connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,"
            "status,uploaded_at) VALUES (?,?,?,1,?,'ready',?)",
            (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", f"/tmp/{doc_id}", NOW))
        conn.execute(
            "INSERT INTO document_classification (document_id, suggested_by,"
            " document_role, discipline) VALUES (?,'none','COMPANY_STANDARD','Piping')",
            (doc_id,))
        for n, (section, text) in enumerate(chunks):
            conn.execute(
                "INSERT INTO chunks (id,document_id,filename,ordinal,page_start,"
                "page_end,section,text,token_count,content_hash,retrievable,kind)"
                " VALUES (?,?,?,?,1,1,?,?,?,?,1,'prose')",
                (f"{doc_id}:c{n}", doc_id, f"{doc_id}.pdf", n, section, text,
                 len(text.split()), f"hash-{doc_id}-{n}"))
    return doc_id


def extract(doc_id: str, **kw) -> dict:
    return standards.extract_requirements(
        doc_id, allowed_document_ids=frozenset({doc_id}), **kw)


def rows(doc_id: str) -> list[dict]:
    return [dict(r) for r in connect().execute(
        "SELECT * FROM standard_requirements WHERE standard_document_id = ?"
        " ORDER BY id", (doc_id,))]


# ------------------------------------------------------------ the unit gate

def test_the_sentences_full_stop_is_not_part_of_the_unit():
    """THE PRODUCT'S OWN WORKED EXAMPLE, verbatim from SAES-A-008 page 6.

    `raw_unit` was 'g/L.' - one character too long - so it did not normalise
    and the limit was stored with a NULL value. The number was read, believed,
    and thrown away.
    """
    limit = requirements_3b.parse_limit(
        "The maximum solids loading limit shall not exceed 5 g/L.")

    assert limit["raw_unit"] == "g/L"
    assert limit["value"] == 5.0
    assert limit["unit"] == "g/L"


def test_a_word_that_is_not_a_unit_is_not_stored_as_one():
    """'in 3 locations' is not a limit of three locations.

    Measured in the corpus as raw_unit values 'locations', 'print' and 'times'.
    A reader sees a numeric_limit row and there is no such quantity to compare.
    """
    limit = requirements_3b.parse_limit(
        "The primer shall not exceed 3 coats.")

    assert limit["raw_unit"] is None, "a non-unit word was stored as a unit"
    # THE COUNT IS STILL THERE. Refusing the unit must not discard the number
    # the document stated - this asserts the code path ran and kept what it
    # should, so the assertion above is not passing on an empty result.
    assert limit["raw_value"] == "3"
    assert limit["operator"] == "<="


def test_db_a_survives_the_unit_gate():
    """A-WEIGHTING IS PART OF THE UNIT, and the gate must not strip it.

    Phase 5B fixed exactly this on the datasheet side; a gate that dropped the
    bracket here would reopen the same defect from the standards side, on the
    16 chunks across 8 documents that state noise limits.
    """
    limit = requirements_3b.parse_limit(
        "The noise level shall not exceed 90 dB(A).")

    assert limit["raw_unit"] == "dB(A)", "the A-weighting was stripped"


def test_an_unbalanced_bracket_is_punctuation_and_is_removed():
    """The other half of the rule above: ')' with nothing opening it is not
    part of the unit."""
    limit = requirements_3b.parse_limit(
        "The cover shall be not less than 300 mm).")

    assert limit["raw_unit"] == "mm"
    assert limit["value"] == 300_000.0


@pytest.mark.parametrize("sentence,value,unit", [
    ("The cable shall be buried a minimum of 1 m.", 1_000_000.0, "um"),
    ("The plate shall be at least 2 inch.", 50_800.0, "um"),
    ("The scale density shall be less than 50 g/m2.", 50.0, "g/m2"),
    ("Heat input shall not exceed 2.5 KJ/mm.", 2.5, "KJ/mm"),
    ("Hardness shall not exceed 200 BHN.", 200.0, "BHN"),
])
def test_the_units_measured_as_missing_now_resolve(sentence, value, unit):
    """Each of these was measured with a NULL value on the real corpus."""
    limit = requirements_3b.parse_limit(sentence)
    assert (limit["value"], limit["unit"]) == (value, unit)


def test_a_rate_never_compares_against_the_quantity_it_is_a_rate_of():
    """5 C/hr is a heating rate. 5 C is a temperature. Same number, and they
    must not be comparable - which is why C/hr is its own dimension."""
    assert claims.unit_dimension("C/hr") == "temperature_rate"
    assert claims.unit_dimension("C") == "temperature"
    assert claims.unit_dimension("C/hr") != claims.unit_dimension("C")


# --------------------------------------------------------- the page footer

FOOTER_CHUNK = (
    "However, the Page 42 of 57 �Saudi Arabian Oil Company, 2022 Saudi "
    "Aramco: Company General Use welder performance shall be evaluated by the "
    "inspector before work begins."
)


def test_the_running_footer_is_removed_before_the_sentence_is_read():
    """A chunk spanning a page break puts the footer INSIDE a sentence.

    Verbatim from SAES-W-011. The stored requirement quoted the standard as
    saying "However, the Page 42 of 57 (c)Saudi Arabian Oil Company, 2022 Saudi
    Aramco: Company General Use welder performance shall be evaluated" - which
    the standard does not say.
    """
    doc = _standard("doc_f", ("7.1", FOOTER_CHUNK))

    extract(doc)

    stored = rows(doc)
    assert len(stored) == 1, f"expected one requirement, got {stored}"
    text = stored[0]["requirement_text"]
    assert "Page 42 of 57" not in text
    assert "Company General Use" not in text
    # AND THE SENTENCE SURVIVED. Stripping the footer must not take the
    # requirement with it - without this the test would pass on an extractor
    # that produced nothing at all.
    assert "welder performance shall be evaluated" in text


# ------------------------------------------------------------- the dedupe

def test_the_same_clause_repeated_across_chunks_is_stored_once():
    """A clause whose page break repeats it is one requirement, not two.

    Measured at 54 of 762 rows. A duplicate double-counts in every total and
    shows an engineer the same clause twice with no way to tell them apart.
    """
    sentence = "The vessel shall be hydrostatically tested before shipment."
    doc = _standard("doc_d", ("7.1", sentence), ("7.1", sentence))

    result = extract(doc)

    assert result["requirements"] == 1, "the duplicate was written"
    assert len(rows(doc)) == 1


def test_the_same_sentence_under_a_different_clause_is_kept():
    """Dedupe is per (clause, text), not per text. The same obligation stated
    under two clauses is two requirements, and collapsing them would silently
    drop one of the two citations."""
    sentence = "The vessel shall be hydrostatically tested before shipment."
    doc = _standard("doc_d2", ("7.1", sentence), ("9.4", sentence))

    assert extract(doc)["requirements"] == 2


# -------------------------------------------------- subject, and NOT field

def test_subject_is_populated_and_field_stays_null():
    """THE LINE THIS CHANGE MUST NOT CROSS.

    `subject` is descriptive. `field` is the key `comparison._match_fact` joins
    on by exact equality against a datasheet caption, and the phrase before the
    operator is never a caption. A populated `field` here would make the column
    read as usable while matching nothing - hiding, rather than fixing, the
    fact that no requirement is comparable yet.
    """
    doc = _standard(
        "doc_s", ("5.3", "The maximum solids loading limit shall not exceed 5 g/L."))

    extract(doc)

    row = rows(doc)[0]
    assert row["subject"] == "maximum solids loading limit"
    assert row["field"] is None, (
        "field was populated; _match_fact joins on it by exact equality and "
        "a descriptive phrase will never equal a datasheet caption")


def test_the_subject_keeps_no_article_modal_or_footer():
    doc = _standard("doc_s2", ("7.4", (
        "Page 7 of 8 Saudi Aramco: Company General Use "
        "The scale density shall be less than 50 g/m2.")))

    extract(doc)

    subject = rows(doc)[0]["subject"]
    assert subject == "scale density", f"got {subject!r}"


def test_a_sentence_with_no_comparator_has_no_subject():
    """`subject` is the phrase before the OPERATOR, so a statement has none.

    NULL rather than the whole sentence: a subject that is just the sentence
    again tells a reader nothing and would make the column look populated on
    every row.
    """
    doc = _standard("doc_s3", ("4.1", "The vendor shall submit a test certificate."))

    extract(doc)

    row = rows(doc)[0]
    assert row["requirement_type"] == "statement"
    assert row["subject"] is None


# ------------------------------------------------------------- replace=True

def test_re_extraction_replaces_its_own_rows_and_keeps_confirmed_ones():
    """CONFIRMED ROWS ARE NEVER DELETED.

    Re-extraction is how every fix in this file reaches the corpus, so it will
    be run again and again. A human's decision must survive all of them - a
    confirmed requirement silently discarded by a re-run is a person's work
    destroyed by a maintenance action, with nothing on screen to say so.
    """
    doc = _standard(
        "doc_r",
        ("5.1", "The vessel shall be tested before shipment."),
        ("5.2", "The flange shall be rated for 300 psi."))
    extract(doc)
    first = rows(doc)
    assert len(first) == 2
    with connect() as conn:
        # `confirmed_by` is a real foreign key to `users`, so the person whose
        # decision this test protects has to exist.
        conn.execute(
            "INSERT INTO users (id,email,display_name,password_hash,created_at)"
            " VALUES ('boss','boss@example.test','boss','h',?)", (NOW,))
        conn.execute(
            "UPDATE standard_requirements SET confirmed_by='boss', confirmed_at=?"
            " WHERE id = ?", (NOW, first[0]["id"]))

    extract(doc, replace=True)

    after = rows(doc)
    kept = [r for r in after if r["id"] == first[0]["id"]]
    assert kept, "re-extraction deleted a CONFIRMED requirement"
    assert kept[0]["confirmed_by"] == "boss"
    # The unconfirmed one was replaced rather than duplicated: still two rows.
    #
    # THIS ASSERTION FOUND A REAL DEFECT. `replace` deletes only unconfirmed
    # rows, and the extractor then re-read the confirmed row's sentence and
    # wrote a second, unconfirmed copy beside it - three rows where there are
    # two requirements. Since every fix to this extractor reaches the corpus BY
    # re-running it, a confirmed requirement would have gained one duplicate
    # per maintenance action, indefinitely.
    assert len(after) == 2, f"re-extraction changed the row count: {len(after)}"


def test_re_extraction_does_not_write_a_second_copy_of_a_confirmed_row():
    """The confirmed row IS that requirement; re-parsing must not shadow it.

    Asserted separately from the count above so the failure names the cause:
    one confirmed row, one unconfirmed copy of the same clause and text.
    """
    doc = _standard("doc_r2", ("5.1", "The vessel shall be tested before shipment."))
    extract(doc)
    original = rows(doc)[0]
    with connect() as conn:
        conn.execute(
            "INSERT INTO users (id,email,display_name,password_hash,created_at)"
            " VALUES ('boss2','boss2@example.test','boss2','h',?)", (NOW,))
        conn.execute(
            "UPDATE standard_requirements SET confirmed_by='boss2', confirmed_at=?"
            " WHERE id = ?", (NOW, original["id"]))

    extract(doc, replace=True)
    extract(doc, replace=True)          # twice: duplicates accumulate per run

    after = rows(doc)
    assert len(after) == 1, (
        f"{len(after)} rows for one confirmed requirement - re-extraction is "
        "writing an unconfirmed copy beside the human's decision")
    assert after[0]["confirmed_by"] == "boss2"


# ------------------------------------------------- stale job recovery

def _job(doc_id: str, state: str, updated_at: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO jobs (id, document_id, stage, state, started_at, updated_at)"
            " VALUES (?,?,?,?,?,?)",
            (f"job_{doc_id}", doc_id, standards.EXTRACTION_STAGE, state,
             updated_at, updated_at))


def test_a_job_left_running_by_a_dead_process_is_queued_again():
    """THE ORPHAN NOBODY WOULD EVER SEE.

    `next_extraction_job` selects `queued` and only `queued`. Nothing anywhere
    in this codebase sweeps, times out or retries, so a job that was `running`
    when the process died is never picked up again - by anything, ever. The
    status keeps reporting work in progress that no process is doing, which is
    worse than a failure: a failure says so.
    """
    _standard("doc_j", ("1.1", "x"))
    _job("doc_j", "running", "2020-01-01T00:00:00Z")
    assert standards.next_extraction_job() is None, "setup did not produce an orphan"

    recovered = standards.recover_stale_extraction_jobs()

    assert recovered == 1
    assert standards.next_extraction_job() == "doc_j"


def test_a_job_that_started_moments_ago_is_left_alone():
    """The age threshold is the guard against reclaiming a LIVE job.

    Without it this sweep would re-queue work another worker is doing, and the
    same standard would be extracted twice at once.
    """
    _standard("doc_live", ("1.1", "x"))
    _job("doc_live", "running", standards._now())

    assert standards.recover_stale_extraction_jobs() == 0
    assert standards.next_extraction_job() is None


def test_recovery_does_not_touch_a_finished_job():
    """`done` and `failed` are terminal. Re-queueing either would re-run work
    that finished, or hide a failure by retrying it forever."""
    _standard("doc_done", ("1.1", "x"))
    _job("doc_done", "done", "2020-01-01T00:00:00Z")

    assert standards.recover_stale_extraction_jobs() == 0
    assert standards.next_extraction_job() is None
