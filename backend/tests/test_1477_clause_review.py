"""#1477: AI clause review of a procedure or specification, quotes verified by code.

The model is a FAKE: no socket, no real model. Every document here is invented
(CLAUDE.md rule 3). Each test fails without the code it names.
"""

from __future__ import annotations

import json

import pytest

from app import access, clause_review, db, standards
from app import reasoning_provider as rp
from app.config import settings
from tests.test_b3_page_ledger import NOW, _review, temp_storage  # noqa: F401 - autouse

PAGE1 = (
    "Roles. The HAZOP chair is appointed by the Safety Department and has not worked on the "
    "design of the unit under study. A scribe records every deviation."
)
PAGE2 = (
    "Follow up. Each recommendation is entered in the action register with an owner and a due "
    "date, and the register is reviewed monthly until all actions are closed."
)
REQ_CHAIR = "The HAZOP chair shall be independent of the design team."
REQ_ACTIONS = (
    "Recommendations shall be tracked to closure with a named owner and a due date."
)
REQ_GUIDE = (
    "Every node shall be studied with the guide words no, more, less and reverse."
)
GOOD_CHAIR = "The HAZOP chair is appointed by the Safety Department and has not worked on the design of the unit under study."


@pytest.fixture(autouse=True)
def _resolver():
    yield
    access.set_user_resolver(None)


def _procedure(doc_id="doc_proc", kind="procedure", pages=(PAGE1, PAGE2)) -> str:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)"
            " VALUES (?,?,?,1,'x','ready',?,?)",
            (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", len(pages), NOW),
        )
        for n, text in enumerate(pages, start=1):
            conn.execute(
                "INSERT INTO pages (document_id,page_no,text,char_count,needs_ocr,batch_no)"
                " VALUES (?,?,?,?,0,0)",
                (doc_id, n, text, len(text)),
            )
            conn.execute(
                "INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,section,kind,text,"
                "token_count,content_hash,retrievable) VALUES (?,?,?,?,?,?,NULL,'prose',?,1,?,1)",
                (
                    f"{doc_id}-c{n}",
                    doc_id,
                    f"{doc_id}.pdf",
                    n,
                    n,
                    n,
                    text,
                    f"h-{doc_id}-{n}",
                ),
            )
        if kind:
            conn.execute(
                "INSERT INTO document_kinds (document_id,kind,state,routed_at) VALUES (?,?,?,?)",
                (doc_id, kind, "confirmed", NOW),
            )
    return doc_id


def _world(requirements=(REQ_CHAIR,), kind="procedure"):
    sub = _procedure(kind=kind)
    run, scope = _review(sub)
    # the helper's one noise-level requirement is not a prose question: replace the set
    with db.connect() as conn:
        conn.execute("DELETE FROM standard_requirements")
    for i, text in enumerate(requirements, start=1):
        standards.create_requirement(
            standard_document_id="doc_std",
            chunk_id="sc",
            clause=f"5.{i}",
            page=1,
            requirement_text=text,
            source_text=text,
        )
    return sub, run, scope


class Fake:
    """A local provider answering per requirement text; records every packet."""

    requested_model = "fake-local"

    def __init__(self, answers, clock=None, step=0.0):
        self.answers, self.packets, self.clock, self.step = answers, [], clock, step

    def reason(self, packet):
        self.packets.append(packet)
        if self.clock is not None:
            self.clock.t += self.step
        asked = packet.prompt.split("NOW THE REAL QUESTION.")[1]
        reply = next(v for k, v in self.answers.items() if k in asked)
        text = reply if isinstance(reply, str) else json.dumps(reply)
        return rp.Response(
            text=text,
            provider=rp.OLLAMA,
            model_tag="fake-local:1",
            digest="d",
            finish_reason="stop",
            prompt_sha256=packet.sha256,
            schema_errors=rp.schema_errors(text, packet.json_schema),
        )


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "clause_review_enabled", True)


def _rows(run):
    return [
        dict(r)
        for r in db.connect().execute(
            "SELECT * FROM review_findings WHERE review_run_id = ? AND origin = ? ORDER BY standard_clause",
            (run, clause_review.ORIGIN),
        )
    ]


def _go(run, scope, fake, **kw):
    return clause_review.run(run, allowed_document_ids=scope, provider=fake, **kw)


def test_a_verified_quote_is_an_engineer_row_with_the_quote_and_page(on):
    _sub, run, scope = _world()
    fake = Fake({"HAZOP chair": {"answer": "quote", "page": 1, "quote": GOOD_CHAIR}})
    status = _go(run, scope, fake)
    [row] = _rows(run)
    assert status["verified"] == 1 and len(fake.packets) == 1
    assert row["compliance_status"] == "NEEDS_ENGINEER_REVIEW"
    assert row["contractor_page"] == 1 and row["contractor_evidence_text"] == GOOD_CHAIR
    assert row["finding"].startswith(clause_review.TEXT_VERIFIED)
    assert (
        row["requirement_id"]
        and row["standard_clause"] == "5.1"
        and row["confirmed_by"] is None
    )


def test_thinking_is_on_and_the_prompt_carries_the_marked_invented_examples(on):
    _sub, run, scope = _world()
    fake = Fake({"HAZOP chair": {"answer": "no_evidence", "page": None, "quote": None}})
    _go(run, scope, fake)
    [packet] = fake.packets
    assert packet.think is True
    assert packet.prompt.count("EXAMPLE ") >= 5
    assert "HAZOP chair is appointed" in packet.prompt  # the passage the model is shown
    for row in clause_review.examples("procedure"):
        assert row["label"] == clause_review.INVENTED_MARK


def test_a_fabricated_quote_is_dropped_and_the_row_says_so(on):
    _sub, run, scope = _world()
    fake = Fake(
        {
            "HAZOP chair": {
                "answer": "quote",
                "page": 1,
                "quote": "The HAZOP chair is always an external consultant with ten years of experience.",
            }
        }
    )
    status = _go(run, scope, fake)
    [row] = _rows(run)
    assert status["unverified"] == 1 and status["verified"] == 0
    assert (
        "could not be verified" in row["finding"]
        and "engineer to check" in row["finding"]
    )
    assert row["contractor_evidence_text"] is None and row["contractor_page"] is None
    assert "external consultant" not in row["finding"]


def test_a_real_quote_on_the_wrong_page_is_not_verified(on):
    _sub, run, scope = _world()
    fake = Fake({"HAZOP chair": {"answer": "quote", "page": 2, "quote": GOOD_CHAIR}})
    _go(run, scope, fake)
    [row] = _rows(run)
    assert (
        "could not be verified" in row["finding"]
        and row["contractor_evidence_text"] is None
    )


def test_a_quote_is_matched_folded_but_exactly():
    page = "The HAZOP   chair is\nappointed by the Safety Department and has not worked on the design."
    assert clause_review.verify_quote(
        "the hazop chair IS appointed by the safety department", page
    )
    assert not clause_review.verify_quote(
        "the hazop chair was appointed by the safety department", page
    )
    assert not clause_review.verify_quote(
        "the hazop chair", page
    )  # too short to prove anything
    assert not clause_review.verify_quote(
        "The HAZOP chair is appointed ... Safety Department", page
    )
    assert not clause_review.verify_quote("", page)


def test_no_evidence_is_an_engineer_row_never_missing_information(on):
    _sub, run, scope = _world((REQ_GUIDE,))
    fake = Fake({"guide words": {"answer": "no_evidence", "page": None, "quote": None}})
    status = _go(run, scope, fake)
    [row] = _rows(run)
    assert status["no_evidence"] == 1
    assert row["compliance_status"] == "NEEDS_ENGINEER_REVIEW" != "MISSING_INFORMATION"
    assert (
        row["finding"].endswith(clause_review.TEXT_NO_EVIDENCE)
        and row["contractor_page"] is None
    )


def test_an_unreadable_answer_is_an_engineer_row(on):
    _sub, run, scope = _world()
    status = _go(run, scope, Fake({"HAZOP chair": "this is not json"}))
    [row] = _rows(run)
    assert status["unreadable"] == 1 and row["finding"].endswith(
        clause_review.TEXT_UNREADABLE
    )


def test_the_ai_can_never_make_a_row_compliant(on):
    _sub, run, scope = _world((REQ_CHAIR, REQ_ACTIONS, REQ_GUIDE))
    fake = Fake(
        {
            "HAZOP chair": {"answer": "quote", "page": 1, "quote": GOOD_CHAIR},
            "tracked to closure": {
                "answer": "quote",
                "page": 2,
                "quote": "made up words that are not on the page at all",
            },
            "guide words": {"answer": "no_evidence", "page": None, "quote": None},
        }
    )
    _go(run, scope, fake)
    assert {r["compliance_status"] for r in _rows(run)} == {"NEEDS_ENGINEER_REVIEW"}


def test_switch_off_changes_nothing(monkeypatch):
    assert settings.clause_review_enabled is False
    _sub, run, scope = _world()
    fake = Fake({"HAZOP chair": {"answer": "quote", "page": 1, "quote": GOOD_CHAIR}})
    assert _go(run, scope, fake) == {"ran": False, "reason": "off"}
    clause_review.for_review(run, scope)
    assert (
        fake.packets == [] and _rows(run) == [] and clause_review.status_of(run) is None
    )


@pytest.mark.parametrize("kind", ["datasheet", "report", None])
def test_other_kinds_are_not_run(on, kind):
    _sub, run, scope = _world(kind=kind)
    fake = Fake({"HAZOP chair": {"answer": "quote", "page": 1, "quote": GOOD_CHAIR}})
    out = _go(run, scope, fake)
    assert out["ran"] is False and fake.packets == [] and _rows(run) == []


def test_a_specification_is_run(on):
    _sub, run, scope = _world(kind="specification")
    fake = Fake({"HAZOP chair": {"answer": "no_evidence", "page": None, "quote": None}})
    assert _go(run, scope, fake)["kind"] == "specification" and len(fake.packets) == 1


def test_a_rerun_over_unchanged_pages_makes_no_model_call(on):
    _sub, run, scope = _world()
    fake = Fake({"HAZOP chair": {"answer": "quote", "page": 1, "quote": GOOD_CHAIR}})
    _go(run, scope, fake)
    again = Fake({})
    status = _go(run, scope, again)
    assert again.packets == [] and status["cache_hits"] == 1 and status["calls"] == 0
    [row] = _rows(run)  # replaced, not doubled
    assert row["contractor_evidence_text"] == GOOD_CHAIR


def test_a_cached_quote_is_verified_again_against_the_stored_page(on):
    sub, run, scope = _world()
    _go(
        run,
        scope,
        Fake({"HAZOP chair": {"answer": "quote", "page": 1, "quote": GOOD_CHAIR}}),
    )
    # same text seen by the model, but page 1's stored text is no longer the quoted one
    with db.connect() as conn:
        conn.execute(
            "UPDATE pages SET text = ? WHERE document_id = ? AND page_no = 1",
            ("Nothing about the chair is written on this page at all, sorry.", sub),
        )
    again = Fake({})
    _go(run, scope, again)
    [row] = _rows(run)
    assert again.packets == [] and "could not be verified" in row["finding"]


def test_changed_text_is_asked_again(on):
    sub, run, scope = _world()
    _go(
        run,
        scope,
        Fake({"HAZOP chair": {"answer": "no_evidence", "page": None, "quote": None}}),
    )
    with db.connect() as conn:
        conn.execute(
            "UPDATE chunks SET text = ? WHERE id = ?",
            (PAGE1 + " Revised in rev B.", f"{sub}-c1"),
        )
    fake = Fake({"HAZOP chair": {"answer": "no_evidence", "page": None, "quote": None}})
    assert _go(run, scope, fake)["calls"] == 1


def test_the_time_budget_stops_cleanly_and_names_what_was_not_reviewed(on, monkeypatch):
    monkeypatch.setattr(
        settings, "clause_review_seconds_per_page", 50.0
    )  # 2 pages -> 100 s
    _sub, run, scope = _world((REQ_CHAIR, REQ_ACTIONS, REQ_GUIDE))
    clock = Clock()
    fake = Fake(
        {
            k: {"answer": "no_evidence", "page": None, "quote": None}
            for k in ("HAZOP chair", "tracked to closure", "guide words")
        },
        clock,
        step=60.0,
    )
    status = _go(run, scope, fake, clock=clock)
    assert len(fake.packets) == 2 and len(_rows(run)) == 2
    assert status["not_reviewed"] == ["5.3"] and status["not_reviewed_count"] == 1
    assert "time budget" in status["stopped"] and status["minutes_per_page"] == 1.0
    assert clause_review.status_of(run)["not_reviewed"] == ["5.3"]


def test_requirements_over_the_cap_are_named_not_reviewed(on, monkeypatch):
    monkeypatch.setattr(settings, "clause_review_max_requirements", 1)
    _sub, run, scope = _world((REQ_CHAIR, REQ_ACTIONS))
    fake = Fake({"HAZOP chair": {"answer": "no_evidence", "page": None, "quote": None}})
    status = _go(run, scope, fake)
    assert len(_rows(run)) == 1 and status["not_reviewed"] == ["5.2"]


def test_a_call_that_fails_is_listed_not_reviewed_and_makes_no_row(on):
    class Down(Fake):
        def reason(self, packet):
            raise rp.ProviderRefused("ollama: down")

    _sub, run, scope = _world()
    status = _go(run, scope, Down({}))
    assert status["failed"] == ["5.1"] and _rows(run) == []


def test_it_asks_only_the_local_model(on, monkeypatch):
    _sub, run, scope = _world()
    made = []

    class Local(Fake):
        def __init__(self, *a, **k):
            super().__init__(
                {"HAZOP chair": {"answer": "no_evidence", "page": None, "quote": None}}
            )
            made.append(k.get("timeout"))

    monkeypatch.setattr(rp, "OllamaProvider", Local)
    monkeypatch.setattr(
        rp,
        "get_provider",
        lambda *a, **k: pytest.fail("the configured provider may be Claude"),
    )
    monkeypatch.setattr(
        rp, "ClaudeProvider", lambda *a, **k: pytest.fail("Claude may not be used here")
    )
    assert clause_review.run(run, allowed_document_ids=scope)["ran"] is True and made


def test_an_unmarked_example_is_refused(tmp_path):
    bad = tmp_path / "x.json"
    bad.write_text(
        json.dumps(
            {
                "label": clause_review.INVENTED_MARK,
                "examples": [
                    {
                        "label": "a real looking one",
                        "requirement": "r",
                        "passages": [],
                        "answer": {},
                        "why": "w",
                    }
                ],
            }
        )
    )
    clause_review._load_examples.cache_clear()
    with pytest.raises(ValueError):
        clause_review._load_examples(str(bad), 0.0)


def test_the_examples_are_5_to_10_and_all_marked():
    for kind in clause_review.KINDS:
        rows = clause_review.examples(kind)
        assert 5 <= len(rows) <= 10
        assert all(
            r["invented"] and r["label"] == clause_review.INVENTED_MARK for r in rows
        )


def test_the_rows_reach_the_crs_for_a_non_datasheet_and_are_not_in_the_headline(on):
    from app import main as main_mod
    from app import review_tiers
    from app.api import run_summary

    _sub, run, scope = _world((REQ_CHAIR, REQ_GUIDE))
    fake = Fake(
        {
            "HAZOP chair": {"answer": "quote", "page": 1, "quote": GOOD_CHAIR},
            "guide words": {"answer": "no_evidence", "page": None, "quote": None},
        }
    )
    _go(run, scope, fake)
    rows, _meta, _name, _stamp = main_mod._crs_content(
        run, access.unrestricted_scope(), "internal"
    )
    mine = [r for r in rows if r["row_kind"] == "clause_review"]
    assert len(mine) == 2
    assert all(
        r["engineer_confirmed"] is False and "engineer to confirm" in r["comment_by"]
        for r in mine
    )
    assert any(GOOD_CHAIR in r["ai_review_comment"] for r in mine)
    assert all("not issued" in r["comment"].lower() for r in mine)
    # the workbook builds for a procedure (no datasheet-only column is needed)
    workbook, _ = main_mod._crs_workbook(run, access.unrestricted_scope(), "internal")
    assert workbook
    # not counted anywhere a headline is made
    findings = run_summary.comparison_mod.list_findings(run, allowed_document_ids=scope)
    assert len(findings) == 2 and clause_review.without_rows(findings) == []
    assert (
        review_tiers.summarise(clause_review.without_rows(findings))["counts"]["total"]
        == 0
    )
    assert main_mod._finding_counts(run)[0] == 0


def test_an_engineers_decision_on_a_row_survives_a_rerun(on):
    _sub, run, scope = _world()
    fake = Fake({"HAZOP chair": {"answer": "no_evidence", "page": None, "quote": None}})
    _go(run, scope, fake)
    [row] = _rows(run)
    with db.connect() as conn:
        conn.execute(
            "UPDATE review_findings SET engineer_comment = 'checked on site' WHERE id = ?",
            (row["id"],),
        )
    _go(
        run,
        scope,
        Fake({"HAZOP chair": {"answer": "quote", "page": 1, "quote": GOOD_CHAIR}}),
    )
    [after] = _rows(run)
    assert after["id"] == row["id"] and after["engineer_comment"] == "checked on site"
    assert after["finding"].endswith(clause_review.TEXT_NO_EVIDENCE)


def test_the_review_job_runs_it_after_the_other_checks_only_when_on(monkeypatch):
    from app import review_jobs

    calls = []
    monkeypatch.setattr(review_jobs, "_ai_check", lambda *a: calls.append("ai"))
    monkeypatch.setattr(review_jobs, "_web_check", lambda *a: calls.append("web"))
    monkeypatch.setattr(clause_review, "run", lambda *a, **k: calls.append("clause"))
    review_jobs._checks("r", frozenset(), [])
    assert calls == ["ai", "web"]
    monkeypatch.setattr(settings, "clause_review_enabled", True)
    calls.clear()
    review_jobs._checks("r", frozenset(), [])
    assert calls == ["ai", "web", "clause"]


def test_a_failure_of_the_review_never_fails_the_job(on, monkeypatch):
    _sub, run, scope = _world()

    def boom(*a, **k):
        raise RuntimeError("secret document text must not be logged")

    monkeypatch.setattr(clause_review, "run", boom)
    clause_review.for_review(run, scope)
    assert "RuntimeError" in clause_review.status_of(run)["plain"]
    assert "secret" not in clause_review.status_of(run)["plain"]


def test_a_crs_row_names_the_standard_the_clause_and_the_requirement(on):
    from app import main as main_mod

    _sub, run, scope = _world((REQ_CHAIR, REQ_GUIDE))
    fake = Fake(
        {
            "HAZOP chair": {"answer": "quote", "page": 1, "quote": GOOD_CHAIR},
            "guide words": {"answer": "no_evidence", "page": None, "quote": None},
        }
    )
    _go(run, scope, fake)
    rows, _m, _n, _s = main_mod._crs_content(
        run, access.unrestricted_scope(), "internal"
    )
    by_clause = {
        r["standard_reference"]: r for r in rows if r["row_kind"] == "clause_review"
    }
    assert set(by_clause) == {"std cl. 5.1", "std cl. 5.2"} or all(
        "5.1" in k or "5.2" in k for k in by_clause
    )
    found = next(r for k, r in by_clause.items() if "5.1" in k)
    none = next(r for k, r in by_clause.items() if "5.2" in k)
    assert "std" in found["standard_reference"]
    assert (
        REQ_CHAIR in found["ai_review_comment"]
        and GOOD_CHAIR in found["ai_review_comment"]
    )
    assert found["page_section"] == "p.1"
    text = none["ai_review_comment"]
    assert REQ_GUIDE in text and "read the 4 most relevant passages" in text
    assert "may be stated in other words" in text
    assert text.lower().count("engineer to check") == 1  # said once, not twice


def test_the_run_says_what_was_read_and_what_was_not_and_the_kind_state(
    on, monkeypatch
):
    from app.api import run_summary
    from app import main as main_mod

    monkeypatch.setattr(settings, "clause_review_seconds_per_page", 50.0)
    _sub, run, scope = _world((REQ_CHAIR, REQ_ACTIONS, REQ_GUIDE))
    with db.connect() as conn:
        conn.execute("UPDATE document_kinds SET state = 'suggested'")
    clock = Clock()
    fake = Fake(
        {
            k: {"answer": "no_evidence", "page": None, "quote": None}
            for k in ("HAZOP chair", "tracked to closure", "guide words")
        },
        clock,
        step=60.0,
    )
    status = _go(run, scope, fake, clock=clock)
    plain = status["plain"]
    assert "2 of 3 requirement(s) read" in plain and "1 not reviewed" in plain
    assert "time budget" in plain and "5.3" in plain
    assert "suggested, not confirmed" in plain
    # the run summary's AI status carries it, top level and nested
    ai = run_summary.ai_engineering_check_mod.ai_check_status(
        run, allowed_document_ids=scope
    )
    assert ai["plain"].endswith(plain) and ai["clause_review"]["not_reviewed"] == [
        "5.3"
    ]
    # the CRS carries it as a note and the notice says the review is not complete
    _rows_, meta, _n, _s = main_mod._crs_content(
        run, access.unrestricted_scope(), "internal"
    )
    assert any(
        plain in n["detail"] for n in meta["review_notes"] if n["note"] == "Not checked"
    )
    assert "REVIEW INCOMPLETE" in meta["incomplete_notice"]


def test_a_complete_read_of_a_confirmed_kind_is_no_incomplete_part_but_a_guessed_kind_is(
    on,
):
    from app import absence

    _sub, run, scope = _world()
    _go(
        run,
        scope,
        Fake({"HAZOP chair": {"answer": "no_evidence", "page": None, "quote": None}}),
    )
    ai = clause_review._stored_ai_status(db.connect(), run)
    assert "1 of 1 requirement(s) read" in ai["clause_review"]["plain"]
    assert (
        absence.unchecked_parts(run_status="completed", outcome={}, ai_status=ai) == []
    )
    with db.connect() as conn:
        conn.execute("UPDATE document_kinds SET state = 'suggested'")
    _go(run, scope, Fake({}))
    ai = clause_review._stored_ai_status(db.connect(), run)
    parts = absence.unchecked_parts(run_status="completed", outcome={}, ai_status=ai)
    [part] = [p for p in parts if p["part"] == "clause_review"]
    assert (
        part["part"] == "clause_review" and "suggested, not confirmed" in part["line"]
    )
