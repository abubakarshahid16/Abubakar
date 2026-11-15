# ruff: noqa: F401
"""K2 (order 13): the paper's noun in every review sentence, the plain "not checked" sentence, the CRS of a paper that is not a
datasheet (one label set, quality export, the held count) and the kind cues (old contract cues in the conflict check, list rows,
a transmittal's own number). INVENTED papers; no model, no network."""

from __future__ import annotations

import json

import pytest

from app import (
    access,
    comparison,
    crs_export_quality,
    db,
    kind_words,
    paper_kind,
    review_jobs,
    transmittal_check,
)
from app.config import settings
from tests import agent_review_support as s

BASE = {
    "basis": comparison.BASIS_REQUIRED_FIELDS,
    "fields_required": 0,
    "fields_answered": 0,
    "sufficient": False,
}
TECH = "not enough to recommend a code"


# ---------------------------------------------------------------- the noun, one home


@pytest.mark.parametrize(
    ("kind", "noun"),
    [("datasheet", "datasheet"), ("contract", "contract"), ("procedure", "procedure"), ("transmittal", "transmittal"),
     ("calculation", "calculation"), ("test_record", "test record"), ("other", "document"), (None, "document"), ("", "document")],
)  # fmt: skip
def test_the_noun_of_a_decided_kind(kind, noun):
    assert kind_words.noun_of_kind(kind) == noun


def test_a_datasheet_keeps_its_exact_old_sentences():
    full = {**BASE, "fields_required": 254, "fields_answered": 11}
    assert comparison.plain_reason(
        "Manual Review Required", TECH, full, None, []
    ).startswith(
        "Found 11 of the 254 datasheet values the applicable standards ask for."
    )
    assert (
        "No applicable standard asks this datasheet for a value that was checked."
        in comparison.plain_reason("Manual Review Required", TECH, BASE, None, [])
    )
    assert "asks this datasheet for a value" in comparison._insufficient_reason(BASE)
    assert comparison._standards_sentence(["X 1"], "so it was not checked.").startswith(
        "1 standard the datasheet cites is not"
    )


@pytest.mark.parametrize("noun", ["contract", "procedure", "transmittal"])
def test_no_sentence_the_review_writes_calls_another_kind_a_datasheet(noun):
    """The REAL sentences of `comparison` (written for a datasheet) go through `in_noun` with the run's recorded noun."""
    comp = {**BASE, "paper_noun": noun, "fields_required": 12, "fields_answered": 3}
    zero = {**BASE, "paper_noun": noun}
    old = {
        k: v for k, v in comp.items() if k != "paper_noun"
    }  # as comparison sees a run
    old0 = {k: v for k, v in zero.items() if k != "paper_noun"}
    real = [
        comparison.plain_reason("Manual Review Required", TECH, old, None, ["IEC 1"]),
        comparison.plain_reason("Manual Review Required", TECH, old0, None, ["IEC 1"]),
        comparison.plain_reason("Manual Review Required", "NOMINAL ESTIMATE", {**old, "fields_read": 4}, None, ["IEC 1"]),
        comparison.plain_reason("Manual Review Required", "Manual review: no requirement was evaluated", old0, None, []),
        comparison._insufficient_reason(old0),
        comparison._insufficient_reason(old),
        comparison.recommend_code([], old0)["reason"],
        comparison.recommend_code([], old0)["details"],
    ]  # fmt: skip
    assert all(
        "datasheet" in t.lower() for t in real
    )  # the sentences are written for a datasheet...
    out = [kind_words.in_noun(t, comp) for t in real]
    for text in out:
        assert "datasheet" not in text.lower() and noun in text, text
    assert (
        kind_words.in_noun("the datasheet cites 2 standards", {})
        == "the datasheet cites 2 standards"
    )  # a datasheet: unchanged
    assert (
        kind_words.in_noun(
            {"reason": "No datasheet", "details": "x", "code": "C"}, comp
        )["reason"]
        == f"No {noun}"
    )


def test_a_review_that_checked_nothing_says_what_was_not_checked_and_why():
    comp = {
        **BASE,
        "paper_noun": "contract",
        "not_checked_plain": kind_words.not_checked_sentence("contract"),
    }
    said = comparison.plain_reason("Manual Review Required", TECH, BASE, None, [])
    text = kind_words.in_noun(said, comp)
    assert text.startswith(
        "No contract checklist is held, so no point of this contract was checked;"
    )
    assert "does not mean the contract is acceptable" in text
    assert (
        kind_words.not_checked_sentence("datasheet") is None
        and kind_words.not_checked_sentence(None) is None
    )
    assert "library" in kind_words.not_checked_sentence("transmittal")
    assert "procedure" in kind_words.not_checked_sentence("procedure")


def _world(tmp_path, monkeypatch, text):
    s.setup_world(tmp_path, monkeypatch)
    conn = db.connect()
    s.add_document(conn, "doc_k2", "k2.pdf", text)
    conn.commit()
    return conn


def _stored_run(conn, doc, outcome):
    from app import submittal_review

    submittal_review.ensure_schema()
    with conn:
        conn.execute(
            "INSERT INTO review_runs (id, submittal_document_id, status, outcome_json, created_at, updated_at)"
            " VALUES (?,?,'completed',?,'t','t')",
            (f"run-{doc}", doc, json.dumps(outcome)),
        )


def test_a_stored_run_of_a_contract_gets_its_noun_and_the_sentence_a_datasheets_run_is_not_touched(
    tmp_path, monkeypatch
):
    conn = _world(
        tmp_path, monkeypatch, "SUPPLY CONTRACT FOR WIDGET SKIDS\nArticle 1 Definitions"
    )
    s.add_document(conn, "doc_ds", "ds.pdf", "PUMP DATA SHEET\nflow 10 m3/h")
    conn.commit()
    outcome = {
        "recommended_code": "Manual Review Required", "completeness": dict(BASE),
        "reason": "No applicable standard asks this datasheet for a value that was checked. That is not enough to suggest a review code yet.",
        "details": "no requirement of an applicable standard asks this datasheet for a value",
    }  # fmt: skip
    _stored_run(conn, "doc_k2", outcome)
    _stored_run(conn, "doc_ds", outcome)
    for doc in ("doc_k2", "doc_ds"):
        kind_words.refresh_outcome(f"run-{doc}")
    got = {
        d: json.loads(
            conn.execute(
                "SELECT outcome_json FROM review_runs WHERE id = ?", (f"run-{d}",)
            ).fetchone()[0]
        )
        for d in ("doc_k2", "doc_ds")
    }
    assert got["doc_k2"]["completeness"]["paper_noun"] == "contract"
    assert got["doc_k2"]["reason"].startswith(
        "No contract checklist is held, so no point of this contract was checked;"
    )
    assert (
        "datasheet" not in got["doc_k2"]["details"]
        and "contract" in got["doc_k2"]["details"]
    )
    assert got["doc_ds"] == outcome  # a datasheet's stored run is the same, key for key


def test_the_progress_words_use_the_decided_kind(tmp_path, monkeypatch):
    _world(
        tmp_path, monkeypatch, "DOCUMENT TRANSMITTAL No. TR-9\nDocuments listed below"
    )
    noun, _unit = review_jobs.document_words("doc_k2")
    assert (
        noun == "transmittal"
        and review_jobs.step_label(0, (noun, "page")) == "reading the transmittal"
    )


# ---------------------------------------------------------------- the CRS of a paper that is not a datasheet


def test_the_crs_meta_of_a_contract_says_not_checked_and_counts_the_held_findings(
    tmp_path, monkeypatch
):
    _world(tmp_path, monkeypatch, "SUPPLY CONTRACT FOR WIDGET SKIDS\nArticle 1")
    out = {"completeness": {"fields_required": 0}}
    findings = [{"compliance_status": "NEEDS_ENGINEER_REVIEW"}] * 3 + [
        {"compliance_status": "OK"}
    ]
    got = kind_words.crs_meta(
        {"review_notes": [{"note": "x"}], "copy": "internal"},
        "doc_k2",
        out,
        findings,
        [{}, {}],
    )
    notes = {n["note"]: n for n in got["review_notes"]}
    assert (
        "No contract checklist is held" in notes[kind_words.NOTE_NOT_CHECKED]["detail"]
    )
    assert notes["Findings held for an engineer"]["count"] == 3
    assert (
        "this CRS has 2 rows" in notes["Findings held for an engineer"]["detail"]
        and "this run's own findings"
        in notes["Findings held for an engineer"]["detail"]
    )
    assert got["export_quality"] is True


def test_the_crs_meta_of_a_datasheet_is_the_same_object(tmp_path, monkeypatch):
    _world(tmp_path, monkeypatch, "PUMP DATA SHEET\nflow")
    meta = {"review_notes": []}
    assert (
        kind_words.crs_meta(
            meta, "doc_k2", {}, [{"compliance_status": "NEEDS_ENGINEER_REVIEW"}], []
        )
        is meta
    )


def test_one_label_set_rewrites_the_ai_draft_labels_and_nothing_else():
    rows = [
        {"comment_by": "AI Review"}, {"comment_by": "AI - engineer to confirm"},
        {"comment_by": "AI clause review - engineer to confirm"}, {"comment_by": "Playbook check (draft)"},
        {"comment_by": "Confirmed by Ann"}, {"comment_by": ""},
    ]  # fmt: skip
    crs_export_quality.one_label_set(rows)
    assert [r["comment_by"] for r in rows] == [
        crs_export_quality.AI_DRAFT_LABEL
    ] * 3 + ["Playbook check (draft)", "Confirmed by Ann", ""]


# ---------------------------------------------------------------- the kind cues


def _kind(*lines):
    return paper_kind.decide_paper_kind([{"page_no": 1, "text": "\n".join(lines)}])


def test_the_old_contract_cues_count_in_the_conflict_check():
    for cue in ('Schedule "Q"', "GENERAL CONDITIONS OF CONTRACT", "Supply Agreement"):
        got = _kind(cue, "Pump Data Sheet")
        assert (got.paper_kind, got.guess, got.method) == (
            "datasheet",
            True,
            "cues_conflict",
        ), cue
        assert got.candidates == ("contract", "datasheet")


def test_the_list_rows_of_a_transmittal_never_override_its_heading():
    got = _kind(
        "DOCUMENT TRANSMITTAL No. TR-9",
        "1  ABC-100-001  Rev A  datasheet",
        "2  ABC-100-002  Rev B  calculation",
    )
    assert (got.paper_kind, got.method) == ("transmittal", "title_cue")
    assert (
        _kind("HAZOP STUDY PROCEDURE", "Pump data sheet reference").paper_kind
        == "procedure"
    )


def test_a_list_row_is_not_a_heading_even_without_a_strong_first_line():
    got = _kind(
        "Scope of supply", "1  Pump data sheet", "2  Relief valve sizing calculation"
    )
    assert got.method != "cues_conflict"


def test_a_transmittal_does_not_list_its_own_number(tmp_path, monkeypatch):
    conn = _world(
        tmp_path,
        monkeypatch,
        "DOCUMENT TRANSMITTAL No. INV-TR-0001\n1  ABC-100-001  Rev A  for review\n",
    )
    conn.execute(
        "INSERT INTO document_classification (document_id, document_number, revision, suggested_by) VALUES ('d_a','ABC-100-001','A','t')"
    ) if False else None
    got = transmittal_check.check(conn, "doc_k2", frozenset({"doc_k2"}))
    assert [r["number"] for r in got["rows"]] == [
        "ABC-100-001"
    ]  # the transmittal's own number is not a document


# ---------------------------------------------------------------- the label set reaches the CRS the engineer reads


def _view_rows():
    def row(by, ref, comment=None):
        return {
            "document_name": "P-1.pdf", "page_section": "p.2", "comment": comment or f"A problem {ref}.", "comment_by": by,
            "standard_reference": f"STD-1 {ref}", "row_kind": "datasheet_check", "engineer_confirmed": False,
            "priority": 3, "reasoning": "",
        }  # fmt: skip

    return [
        row("AI Review", "1", "Not read from the datasheet (5 pages) - Rated capacity"),
        row("AI - engineer to confirm", "2"),
        row("AI clause review - engineer to confirm", "3"),
        row("Playbook check (draft)", "4"),
    ]


def test_a_non_datasheet_internal_view_names_the_paper_and_carries_one_label_set():
    from app import crs_export

    meta = {
        "review_run_id": "run-k2",
        "export_quality": True,
        "copy": "internal",
        "paper_noun": "contract",
    }
    view = crs_export.build_crs_view(_view_rows(), meta)
    assert sorted({r["comment_by"] for r in view["rows"]}) == [
        "AI reviewer - engineer to confirm",
        "Playbook check (draft)",
    ]
    assert view["rows"][0]["comment"].startswith("Not read from the contract (5 pages)")


def test_a_datasheet_view_is_the_same_with_the_quality_flag_on_or_off_labels_and_words_alike():
    from app import crs_export

    meta = {
        "review_run_id": "run-k2",
        "copy": "internal",
    }  # no paper_noun: a datasheet (or an unknown kind)
    on = crs_export.build_crs_view(_view_rows(), {**meta, "export_quality": True})
    off = crs_export.build_crs_view(_view_rows(), {**meta, "export_quality": False})
    labels = lambda v: {r["comment_by"] for r in v["rows"]}  # noqa: E731
    assert (
        labels(on)
        == labels(off)
        == {
            "AI Review",
            "AI - engineer to confirm",
            "AI clause review - engineer to confirm",
            "Playbook check (draft)",
        }
    )
    assert on["rows"][0]["comment"].startswith("Not read from the datasheet")


def test_the_contractor_copy_of_a_non_datasheet_stays_as_it_was(tmp_path, monkeypatch):
    _world(tmp_path, monkeypatch, "SUPPLY CONTRACT FOR WIDGET SKIDS\nArticle 1")
    out = {"completeness": {"fields_required": 0}}
    findings = [{"compliance_status": "NEEDS_ENGINEER_REVIEW"}]
    meta = {
        "review_notes": [],
        "copy": "issue",
        "recommended_code_reason": "No applicable standard asks this datasheet for a value.",
    }
    assert (
        kind_words.crs_meta(meta, "doc_k2", out, findings, [{}]) is meta
    )  # the same object: no change at all
    internal = kind_words.crs_meta(
        {**meta, "copy": "internal"}, "doc_k2", out, findings, [{}]
    )
    assert internal["paper_noun"] == "contract" and internal["export_quality"] is True


def test_a_run_stored_before_this_change_is_shown_with_the_decided_noun_on_the_crs(
    tmp_path, monkeypatch
):
    _world(tmp_path, monkeypatch, "SUPPLY CONTRACT FOR WIDGET SKIDS\nArticle 1")
    old_reason = "No applicable standard asks this datasheet for a value that was checked. That is not enough to suggest a review code yet."
    got = kind_words.crs_meta(
        {"recommended_code_reason": old_reason, "review_notes": [], "copy": "internal"},
        "doc_k2",
        {"completeness": {"fields_required": 0}},
        [],
        [],
    )
    assert got["recommended_code_reason"].startswith(
        "No contract checklist is held, so no point of this contract was checked;"
    )
    assert "datasheet" not in got["recommended_code_reason"]


# ---- the two guards that failed no test, and the cut of a comment


def test_a_strong_first_line_heading_beats_the_data_sheet_and_calculation_lines_below_it():
    for first, want in (
        ("HAZOP STUDY PROCEDURE", "procedure"),
        ("DOCUMENT TRANSMITTAL", "transmittal"),
    ):
        got = _kind(first, "Pump Data Sheet", "Relief Valve Sizing Calculation")
        assert (got.paper_kind, got.method) == (want, "title_cue"), first
    both = _kind(
        "Scope of supply", "Pump Data Sheet", "Relief Valve Sizing Calculation"
    )
    assert (both.paper_kind, both.method) == (
        "datasheet",
        "cues_conflict",
    )  # without a strong first line it is "not sure"


def test_the_noun_swap_leaves_a_datasheet_sentence_exactly_as_it_was_in_any_case():
    for text in (
        "DATASHEET",
        "DataSheet values",
        "No applicable standard asks this Datasheet.",
    ):
        assert (
            kind_words.in_noun(text, {}) == text
        )  # no recorded noun: untouched, whatever the case
        assert kind_words.in_noun(text, {"paper_noun": "datasheet"}) == text
    assert (
        kind_words.in_noun("the datasheets cite 3", {"paper_noun": "contract"})
        == "the contracts cite 3"
    )


@pytest.mark.parametrize("tail", ["N/mm2 limit", "Scope of supply", "shall apply"])
def test_a_comment_is_never_cut_after_a_bare_number_or_a_clause_number(tail):
    from app import crs_export_quality as q

    pad = "word " * 60
    for text in (pad + "design pressure 10 " + tail + " " + "x " * 40, pad + "see clause 4.1.2. " + tail + " " + "x " * 40,
                 pad + "tag INV-VAL-1 " + tail + " " + "x " * 40):  # fmt: skip
        for limit in range(len(pad) + 10, len(pad) + 50):
            head, rest = q.split_comment(text, limit)
            assert (
                head + " " + rest == text
                or head + rest == text
                or (head + " " + rest).split() == text.split()
            )
            last = head.split()[-1] if head.split() else ""
            assert not q._BARE_NUMBER.fullmatch(last), (limit, head[-20:], rest[:12])


# ---- R52b: quotes, titles and field labels are never rewritten; only the system's own sentences change


def test_the_noun_changes_only_the_systems_own_words_never_a_quote_a_title_or_a_field_label():
    quote = "the Datasheet governs where it conflicts with the Specification (clause 2)"
    label = "Datasheet number (field)"
    title = "Datasheet Requirements for Pumps (rule book title)"
    row = {
        "comment": f'Not read from the datasheet (5 pages) - {label}. The rule says: "{quote}". Rule book: {title}. Held, not compared with the datasheet.',
        "page_section": "Not read from the datasheet (5 pages)",
        "ai_review_comment": f'The AI read: "{quote}"',
        "reasoning": f"Read: {label} = 12 (p.2). Datasheet field not identified - engineer to check",
        "comment_by": "AI Review",
    }
    before = dict(row)
    view = {
        "rows": [row],
        "review_notes": [{"detail": "No datasheet field found - engineer to check"}],
    }
    kind_words.name_the_paper(view, {"paper_noun": "contract"})
    got = view["rows"][0]
    for text in (quote, label, title):
        assert all(
            text in got[k]
            for k in ("comment", "ai_review_comment", "reasoning")
            if text in before[k]
        )  # every quote, title and label identical
    assert (
        "Not read from the contract (5 pages)" in got["comment"]
        and got["page_section"] == "Not read from the contract (5 pages)"
    )
    assert (
        "Held, not compared with the contract." in got["comment"]
        and "Contract field not identified" in got["reasoning"]
    )
    assert (
        view["review_notes"][0]["detail"]
        == "No contract field found - engineer to check"
    )
    assert got["comment_by"] == "AI reviewer - engineer to confirm"
    # a datasheet word outside the system's templates survives: counted by what is left, not by a rewrite
    assert got["comment"].count("Datasheet") == before["comment"].count("Datasheet")


def test_a_short_generic_fragment_of_a_template_is_never_a_swap_key():
    keys = kind_words.templates()
    assert keys and all(len(k) >= 20 for k in keys)
    assert "The datasheet " not in keys and "Datasheet states " not in keys
    assert "Not read from the datasheet" in keys  # a whole system sentence is


# ---- follow-ups of R52c: quote boundaries, and the templates cannot drift silently

QUOTE_SHAPES = ('"{}"', "\u201c{}\u201d", "'{}'", "\u2018{}\u2019")


@pytest.mark.parametrize("shape", QUOTE_SHAPES)
def test_text_between_quote_marks_is_never_rewritten_whatever_its_length(shape):
    inside = "see Annex B (see the datasheet pages)"  # contains a template fragment, inside a quote
    long_inside = (
        "see Annex B "
        + "word " * 40
        + "Not read from the datasheet (5 pages) and Held, not compared with the datasheet"
    )
    for quoted in (inside, long_inside):
        text = f"Not read from the datasheet (5 pages). The rule says {shape.format(quoted)}. Held, not compared with the datasheet."
        got = kind_words.in_templates(text, "contract")
        assert (
            shape.format(quoted) in got
        )  # the quote is identical, template words inside it included
        assert got.startswith("Not read from the contract (5 pages).") and got.endswith(
            "Held, not compared with the contract."
        )


def test_an_apostrophe_is_not_a_quote_and_an_unclosed_quote_protects_what_follows():
    assert kind_words.in_templates(
        "Not read from the datasheet (the vendor's sheet). Held, not compared with the datasheet.",
        "contract",
    ) == (
        "Not read from the contract (the vendor's sheet). Held, not compared with the contract."
    )
    unclosed = 'The rule says "see Annex B. Held, not compared with the datasheet.'
    assert (
        kind_words.in_templates(unclosed, "contract") == unclosed
    )  # an open quote runs to the end: left alone


def test_a_template_that_opens_with_a_quote_mark_is_still_said_after_a_closed_quote():
    text = '"the paper says this" Please confirm or justify. This is a recommendation, not a requirement; it is not compared with the datasheet.'
    assert "Please confirm or justify" in kind_words.in_templates(
        text, "contract"
    )  # no crash, no mangling


#: Every string constant with "datasheet" in the six row-builder files must be a template `templates()` returns or be listed here.
KNOWN_FAULT = {
    "Datasheet ": "KNOWN FAULT this round: a short f-string piece in crs_mapping; saying it would also open a quote",
    "Datasheet states ": "KNOWN FAULT this round: too short to be an exact key (a quote may begin with it)",
    "The datasheet ": "KNOWN FAULT this round: too short to be an exact key (a quote may begin with it)",
    "datasheet_check": "a code identifier (a row kind), not a sentence",
    "datasheet_check_not_run": "a code identifier (an outcome key), not a sentence",
}


def test_every_datasheet_worded_constant_of_the_row_builders_is_a_template_or_a_named_known_fault():
    import ast
    import re
    from pathlib import Path

    keys = set(kind_words.templates())
    missed: list[str] = []
    for name in kind_words._TEMPLATE_FILES:
        tree = ast.parse(
            (Path(__file__).resolve().parents[1] / "app" / f"{name}.py").read_text(
                encoding="utf-8"
            )
        )
        docs = {
            id(n.body[0].value)
            for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body and isinstance(n.body[0], ast.Expr)
            and isinstance(n.body[0].value, ast.Constant)
        }  # fmt: skip
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docs
                and re.search("datasheet", node.value, re.I)
            ):
                if node.value not in keys and node.value not in KNOWN_FAULT:
                    missed.append(f"{name}: {node.value[:60]!r}")
    assert not missed, (
        "a new datasheet-worded sentence is neither a template nor a named known fault: "
        + "; ".join(missed)
    )
    assert all(
        KNOWN_FAULT[k] for k in KNOWN_FAULT
    )  # every exception carries its reason


def test_a_row_builder_source_that_cannot_be_read_fails_loudly_never_swaps_nothing(
    monkeypatch,
):
    import importlib.util

    real = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name, *a, **k: (
            None if name.endswith(".absence") else real(name, *a, **k)
        ),
    )
    kind_words.templates.cache_clear()
    try:
        with pytest.raises(kind_words.TemplateSourceError):
            kind_words.templates()
        with pytest.raises(kind_words.TemplateSourceError):
            kind_words.name_the_paper(
                {"rows": [{"comment": "Not read from the datasheet"}]},
                {"paper_noun": "contract"},
            )
    finally:
        monkeypatch.undo()
        kind_words.templates.cache_clear()
