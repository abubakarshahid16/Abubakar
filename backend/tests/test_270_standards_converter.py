"""Order 270.3: the standards converter. Invented text only; the model is a fake that answers from the
sentence it is shown. What is proven here: only the allowed families leave, only standards text leaves, code
(not the model) decides what is a check, an unproven row carries no limit, a cap or a refusal stops the run
cleanly, the drafts stay out of the repository and name the form they were read against, and the review
reads them only behind the switch."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

from app import (
    claude_approved,
    claude_spend,
    db,
    rule_roles,
    standards,
    standards_converter,
    submittal_review,
)
from app.config import settings
from app.reasoning_provider import ClaudeProvider, ProviderRefused, Response
from tests.test_chat_pr1_model_lane import KEY

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import convert_standards

PUMP = "Centrifugal Pump"
NOW = "2026-10-28T00:00:00Z"
SHA = "b54474a2"
DICT, ROLES, FAMILIES = rule_roles.form(PUMP)


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "convert.sqlite")
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    monkeypatch.setattr(settings, "claude_cache_dir", tmp_path / "cache")
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    yield
    db.reset_connection()


def _doc(doc_id: str, role: str, number: str | None = None) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)"
            " VALUES (?,?,?,1,?,'ready',1,?)",
            (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", f"{doc_id}.pdf", NOW),
        )
        conn.execute(
            "INSERT INTO document_classification (document_id,suggested_by,document_role,document_number)"
            " VALUES (?,?,?,?)",
            (doc_id, "test", role, number),
        )
        conn.execute(
            "INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,section,kind,text,"
            "token_count,content_hash,retrievable) VALUES (?,?,?,0,1,1,NULL,'prose','x',1,?,1)",
            (f"c-{doc_id}", doc_id, "f.pdf", f"h-{doc_id}"),
        )


def _req(doc_id: str, text: str, clause: str = "6.1", rtype: str = "statement") -> dict:
    return standards.create_requirement(
        standard_document_id=doc_id,
        chunk_id=f"c-{doc_id}",
        requirement_text=text,
        source_text=text,
        clause=clause,
        page=1,
        structured={"requirement_type": rtype},
    )


def _standard(number: str = "SAES-G-005", texts: tuple[str, ...] = ()) -> str:
    doc_id = "std-" + number.lower().replace(" ", "-")
    _doc(doc_id, "COMPANY_STANDARD", number)
    for n, t in enumerate(texts):
        _req(doc_id, t, clause=f"6.{n + 1}")
    return doc_id


GOOD = {
    "applies": "yes",
    "condition": None,
    "field": DICT.index("design pressure"),
    "comparator": "<=",
    "limit": "25",
    "unit": "bar",
    "quote": "design pressure shall not exceed 25 bar",
}
SENTENCE = "The casing design pressure shall not exceed 25 bar for this service."
ROW = {"requirement_text": SENTENCE, "clause": "6.1", "requirement_type": "statement"}


class Fake:
    """Answers each item with `answer_for(text)` (a dict of the answer without `i`, or None)."""

    requested_model = "claude-sonnet-5"
    name = "claude"

    def __init__(self, answer_for=lambda text: None, fail_on=None):
        self.answer_for, self.fail_on = answer_for, fail_on
        self.packets, self.carried = [], []

    def reason(self, packet):
        self.packets.append(packet)
        self.carried.append(claude_approved.carried())
        if self.fail_on is not None and len(self.packets) == self.fail_on[0]:
            raise self.fail_on[1]
        checks = []
        for item in json.loads(packet.prompt)["items"]:
            got = self.answer_for(item["text"])
            checks.append(
                {"i": item["i"], **(got or {"applies": "yes", "field": None})}
            )
        return Response(
            text=json.dumps({"checks": checks}),
            provider="claude",
            model_tag="claude-sonnet-5",
            digest="d",
            finish_reason="stop",
            prompt_sha256=packet.sha256,
        )


# ------------------------------------------------------------------ 1. only the allowed families leave


@pytest.mark.parametrize("label", ["SAES-G-005", "saes-k-503", "ISO 15156-3"])
def test_saes_and_iso_are_allowed(label):
    standards_converter.require_family(label)


@pytest.mark.parametrize(
    "label", ["API 610", "ASME B16.5", "API-520", "ANSI/ASME B73.1", "", None]
)
def test_any_other_family_is_refused_and_nothing_is_sent(label):
    with pytest.raises(standards_converter.FamilyNotAllowed):
        standards_converter.require_family(label)
    doc_id = _standard(
        "API 610", ("The casing design pressure shall not exceed 25 bar.",)
    )
    fake = Fake()
    with db.connect() as conn, pytest.raises(standards_converter.FamilyNotAllowed):
        standards_converter.convert(conn, doc_id, label or "API 610", PUMP, fake)
    assert fake.packets == []


def test_the_script_refuses_a_family_before_it_opens_the_database(tmp_path):
    with pytest.raises(standards_converter.FamilyNotAllowed):
        convert_standards.run(
            tmp_path / "no-such.sqlite", PUMP, ["ASME B16.5"], tmp_path / "out", SHA
        )


# ------------------------------------------------------------------ 2. standards text only


SENTINELS = (
    "SENTINEL-DATASHEET-7731",
    "SENTINEL-PROCEDURE-5512",
    "SENTINEL-CRS-9904",
    "SENTINEL-REGISTER-2260",
)


def test_no_datasheet_procedure_crs_or_register_text_can_enter_a_prompt():
    std = _standard(
        texts=(
            "The casing design pressure shall not exceed 25 bar.",
            "Bearings shall be lubricated.",
        )
    )
    for n, (role, sentinel) in enumerate(
        zip(
            ("CONTRACTOR_SUBMITTAL", "PROCEDURE", "CRS", "REGISTER"),
            SENTINELS,
        )
    ):
        other = f"other-{n}"
        _doc(other, role)
        _req(other, f"{sentinel} the design pressure shall not exceed 99 bar.")
    fake = Fake()
    with db.connect() as conn:
        result = standards_converter.convert(conn, std, "SAES-G-005", PUMP, fake)
    assert len(result.rows) == 2 and fake.packets
    sent = "\n".join(p.prompt + "\n" + p.system for p in fake.packets)
    assert "design pressure shall not exceed 25 bar" in sent
    for sentinel in SENTINELS:
        assert sentinel not in sent


def test_a_document_that_is_not_a_company_standard_is_refused_by_the_loader():
    _doc("sheet-1", "CONTRACTOR_SUBMITTAL")
    _req("sheet-1", "SENTINEL-DATASHEET-7731 text")
    with db.connect() as conn, pytest.raises(standards_converter.NotStandardsText):
        standards_converter.requirements_of(conn, "sheet-1")
    with db.connect() as conn, pytest.raises(standards_converter.NotStandardsText):
        standards_converter.requirements_of(conn, "no-such-document")


def test_each_call_declares_exactly_the_standard_it_carries():
    std = _standard(texts=("A.", "B."))
    fake = Fake()
    with db.connect() as conn:
        standards_converter.convert(conn, std, "SAES-G-005", PUMP, fake)
    assert fake.carried == [frozenset({std})]
    assert all(p.step == "standards_convert:SAES-G-005" for p in fake.packets)
    assert claude_approved.carried() is None  # the declaration ends with the call


def test_a_standard_that_is_not_on_the_approved_list_is_refused_before_it_leaves(
    monkeypatch,
):
    """The real provider, the real lane: the declared standard is not approved, so the transport is
    never called and the run is marked refused - not 'stopped at cap'."""
    monkeypatch.setattr(settings, "claude_approved_list_enforced", True)
    monkeypatch.setattr(settings, "reasoning_provider", "claude")
    monkeypatch.setattr(settings, "anthropic_api_key", KEY)
    monkeypatch.setattr(settings, "standards_reader_enabled", True)
    monkeypatch.setattr(settings, "standards_reader_allow_public_egress", True)
    for name in (
        "STANDARDS_READER_ENABLED",
        "STANDARDS_READER_ALLOW_PUBLIC_EGRESS",
        "ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    sent = []

    def send(url, *, headers, body, timeout):
        sent.append(body)
        raise AssertionError("nothing may leave")

    std = _standard(texts=("The casing design pressure shall not exceed 25 bar.",))
    with db.connect() as conn:
        result = standards_converter.convert(
            conn,
            std,
            "SAES-G-005",
            PUMP,
            ClaudeProvider("claude-sonnet-5", transport=send),
        )
    assert sent == []
    assert result.refused == claude_approved.NOT_APPROVED and not result.stopped_at_cap
    assert [r["status"] for r in result.rows] == ["not_asked"]
    assert claude_spend.spent() == 0


# ------------------------------------------------------------------ 3. code decides what is a check


def _verdict(answer, row=ROW):
    return standards_converter.verify(answer, row, DICT, ROLES, FAMILIES)


def test_an_answer_that_passes_every_gate_is_a_check_in_the_forms_own_terms():
    status, reason, check = _verdict(GOOD)
    assert (status, reason) == ("verified", None)
    assert (check.field, check.comparator, check.limit, check.unit) == (
        "design_pressure",
        "<=",
        "25",
        "bar",
    )


@pytest.mark.parametrize(
    "change, reason",
    [
        ({"applies": "maybe"}, "applies_unreadable"),
        ({"applies": "depends", "condition": None}, "condition_not_in_clause"),
        (
            {"applies": "depends", "condition": "for sour service"},
            "condition_not_in_clause",
        ),
        ({"field": None}, "no_field"),
        ({"field": 999}, "no_field"),
        ({"field": True}, "no_field"),
        (
            {"quote": "the design pressure shall not exceed 26 bar"},
            "quote_not_in_clause",
        ),
        ({"quote": "bar"}, "quote_not_in_clause"),
        ({"limit": "30"}, "number_not_in_quote"),
        ({"limit": "2"}, "number_not_in_quote"),
        ({"limit": ""}, "number_not_in_quote"),
        ({"unit": "psi"}, "unit_not_in_quote"),
        ({"unit": ""}, "unit_not_in_quote"),
        ({"field": DICT.index("rated speed"), "unit": "bar"}, "unit_not_of_field"),
        (
            {"field": DICT.index("design temperature"), "unit": "bar"},
            "unit_not_of_field",
        ),
        ({"field": DICT.index("rated flow"), "unit": "bar"}, "unit_not_of_field"),
        ({"comparator": ">="}, "comparator_not_in_quote"),
        ({"comparator": ">"}, "comparator_not_in_quote"),
        ({"comparator": "<"}, "comparator_not_in_quote"),
        ({"comparator": "=="}, "comparator_not_in_quote"),
        ({"comparator": None}, "comparator_not_in_quote"),
    ],
)
def test_every_gate_alone_keeps_an_answer_unproven(change, reason):
    status, why, check = _verdict({**GOOD, **change})
    assert (status, why, check) == ("unproven", reason, None)


def test_the_quote_must_name_the_field_not_just_contain_the_number():
    row = {**ROW, "requirement_text": "The test pressure shall not exceed 25 bar."}
    answer = {**GOOD, "quote": "test pressure shall not exceed 25 bar"}
    assert _verdict(answer, row)[:2] == ("unproven", "field_not_in_quote")


def test_a_range_in_the_quote_proves_no_comparator():
    row = {
        **ROW,
        "requirement_text": "The design pressure shall be at least 5 bar and shall not exceed 25 bar.",
    }
    quote = "design pressure shall be at least 5 bar and shall not exceed 25 bar"
    for comparator in ("<=", ">="):
        assert _verdict({**GOOD, "quote": quote, "comparator": comparator}, row)[
            :2
        ] == (
            "unproven",
            "comparator_not_in_quote",
        )


@pytest.mark.parametrize(
    "quote, said",
    [
        ("design pressure shall not exceed 25 bar", {"<="}),
        ("at least 25 bar", {">="}),
        ("less than 25 bar", {"<"}),
        ("greater than 25 bar", {">"}),
        ("shall be 25 bar", {"="}),
        ("minimum 5 bar, maximum 25 bar", {">=", "<="}),
    ],
)
def test_comparators_said_by_the_quotes_own_words(quote, said):
    assert standards_converter.comparators_said(quote) == said


def test_no_is_the_models_claim_and_never_a_check():
    status, reason, check = _verdict({**GOOD, "applies": "no"})
    assert (status, reason, check) == ("not_applicable", None, None)


def test_an_unproven_row_carries_no_limit_and_only_says_engineer_please_look():
    std = _standard(texts=(SENTENCE, "Bearings shall be lubricated."))
    fake = Fake(
        lambda text: (
            GOOD if "design pressure" in text else {"applies": "yes", "field": None}
        )
    )
    with db.connect() as conn:
        result = standards_converter.convert(conn, std, "SAES-G-005", PUMP, fake)
    by_status = {r["status"]: r for r in result.rows}
    ok, bad = by_status["verified"], by_status["unproven"]
    assert (ok["field"], ok["comparator"], ok["limit"], ok["unit"]) == (
        "design_pressure",
        "<=",
        "25",
        "bar",
    )
    assert ok["note"] is None
    assert bad["note"] == "engineer, please look" and bad["reason"] == "no_field"
    for key in ("field", "comparator", "limit", "unit", "quote"):
        assert bad[key] is None
    assert result.counts()["verified"] == 1 and result.counts()["unproven"] == 1


def test_an_unreadable_reply_is_unproven_not_dropped_or_guessed():
    std = _standard(texts=("A sentence.", "Another sentence."))

    class Garbled(Fake):
        def reason(self, packet):
            r = super().reason(packet)
            return Response(
                text="not json",
                provider="claude",
                model_tag=r.model_tag,
                digest="d",
                finish_reason="stop",
                prompt_sha256=r.prompt_sha256,
            )

    with db.connect() as conn:
        result = standards_converter.convert(conn, std, "SAES-G-005", PUMP, Garbled())
    assert [r["reason"] for r in result.rows] == [
        "reply_unreadable"
    ] * 2 and result.unreadable_batches == 1


# ------------------------------------------------------------------ 4. a cap or a refusal stops the run cleanly


def _many(n: int) -> str:
    return _standard(
        texts=tuple(
            f"The casing design pressure shall not exceed {20 + i} bar."
            for i in range(n)
        )
    )


def _answer_good(text):
    figure = next(w for w in text.replace(".", " ").split() if w.isdigit())
    return {
        **GOOD,
        "limit": figure,
        "quote": f"design pressure shall not exceed {figure} bar",
    }


def test_a_usd_cap_stops_the_run_keeps_what_was_finished_and_says_so(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(standards_converter, "BATCH", 2)
    std = _many(5)
    fake = Fake(
        _answer_good, fail_on=(2, claude_spend.BudgetExceeded("cap $25.00 per step"))
    )
    with db.connect() as conn:
        result = standards_converter.convert(conn, std, "SAES-G-005", PUMP, fake)
    assert result.stopped_at_cap and result.refused is None
    assert [r["status"] for r in result.rows] == ["verified", "verified"] + [
        "not_asked"
    ] * 3
    assert len(fake.packets) == 2  # nothing was asked after the cap
    files = standards_converter.write(result, tmp_path / "mirror", form_sha=SHA)
    body = json.loads(files["json"].read_text())
    assert (
        body["run"] == "stopped at cap"
        and body["counts"]["verified"] == 2
        and body["counts"]["not_asked"] == 3
    )


def test_a_failed_call_stops_the_run_but_is_not_called_a_cap(monkeypatch):
    monkeypatch.setattr(standards_converter, "BATCH", 2)
    std = _many(3)
    fake = Fake(_answer_good, fail_on=(2, ProviderRefused("claude: ReadTimeout")))
    with db.connect() as conn:
        result = standards_converter.convert(conn, std, "SAES-G-005", PUMP, fake)
    assert not result.stopped_at_cap and result.refused == "ProviderRefused"
    assert [r["status"] for r in result.rows] == ["verified", "verified", "not_asked"]


# ------------------------------------------------------------------ 5. the drafts: outside the repo, pinned to the form


def _result():
    std = _standard(texts=(SENTENCE,))
    with db.connect() as conn:
        return standards_converter.convert(
            conn, std, "SAES-G-005", PUMP, Fake(lambda text: GOOD)
        )


def test_the_drafts_are_never_written_inside_the_repository():
    result = _result()
    for inside in (
        standards_converter.REPO,
        standards_converter.REPO / "backend" / "app",
        standards_converter.REPO / "x",
    ):
        with pytest.raises(ValueError, match="inside the repository"):
            standards_converter.write(result, inside, form_sha=SHA)
        assert not (inside / f"{standards_converter.file_stem(result)}.json").exists()


@pytest.mark.parametrize("sha", ["", "main", "b54474", "zzzzzzz", None])
def test_a_file_must_name_the_form_it_was_read_against(sha, tmp_path):
    with pytest.raises(ValueError, match="form_sha"):
        standards_converter.write(_result(), tmp_path / "m", form_sha=sha)


def test_the_files_name_the_form_the_model_the_spend_and_the_run(tmp_path):
    result = _result()
    files = standards_converter.write(result, tmp_path / "mirror", form_sha="B54474A2")
    body = json.loads(files["json"].read_text())
    assert body["form_source"] == {"ref": "#1352", "sha": "b54474a2"}
    assert body["converter"] is True and body["status"] == "draft"
    assert body["standard"] == "SAES-G-005" and body["equipment_type"] == PUMP
    assert (
        body["model"] == "claude-sonnet-5"
        and body["prompt_version"] == standards_converter.PROMPT_VERSION
    )
    assert body["run"] == "complete" and "usd_spent" in body
    [entry] = body["entries"]
    assert entry["status"] == "verified" and entry["field"] == "design_pressure"
    rows = list(csv.DictReader(files["csv"].open(encoding="utf-8")))
    assert [r["status"] for r in rows] == ["verified"] and rows[0]["limit"] == "25"
    assert files["json"].name == "centrifugal_pump.SAES_G_005.json"


def test_the_script_dry_run_counts_and_sends_nothing(tmp_path):
    _standard(texts=("A.", "B.", "C."))
    out = convert_standards.run(
        tmp_path / "convert.sqlite", PUMP, ["SAES-G-005"], None, None, dry_run=True
    )
    assert out["results"] == [{"standard": "SAES-G-005", "requirements": 3, "calls": 1}]


def test_the_script_run_stops_at_the_first_standard_a_cap_stops(tmp_path, monkeypatch):
    monkeypatch.setattr(standards_converter, "BATCH", 1)
    _standard(
        "ISO 15156-3",
        (
            "The casing design pressure shall not exceed 25 bar.",
            "The casing design pressure shall not exceed 26 bar.",
        ),
    )
    _standard("SAES-G-005", ("The casing design pressure shall not exceed 27 bar.",))
    fake = Fake(_answer_good, fail_on=(2, claude_spend.BudgetExceeded("cap")))
    out = convert_standards.run(
        tmp_path / "convert.sqlite",
        PUMP,
        ["SAES-G-005", "ISO 15156-3"],
        tmp_path / "mirror",
        SHA,
        provider=fake,
    )
    assert out["stopped"] is True
    [only] = out[
        "results"
    ]  # the standard after it is not started: the same cap would stop it
    assert only["standard"] == "ISO 15156-3" and only["run"] == "stopped at cap"
    assert (only["verified"], only["not_asked"]) == (1, 1) and len(fake.packets) == 2
    assert sorted(f.name for f in (tmp_path / "mirror").iterdir()) == [
        "centrifugal_pump.ISO_15156_3.csv",
        "centrifugal_pump.ISO_15156_3.json",
    ]


def test_the_script_reports_a_closed_lane_and_sends_nothing(tmp_path):
    _standard(texts=("A.",))
    out = convert_standards.run(
        tmp_path / "convert.sqlite", PUMP, ["SAES-G-005"], tmp_path / "m", SHA
    )
    assert out["lane"] == "PROVIDER_OFF"
    assert out["results"] == [] and not (tmp_path / "m").exists()


# ------------------------------------------------------------------ 6. the review reads the drafts only behind the switch


def _numeric(i: int, text: str, unit: str = "bar") -> dict:
    return {
        "id": f"r{i}",
        "standard_document_id": "std-1",
        "clause": "6.1",
        "requirement_type": "numeric_limit",
        "raw_value": "25",
        "raw_unit": unit,
        "requirement_text": text,
    }


def _mirror(tmp_path, answers):
    std = _standard(texts=tuple(answers))
    with db.connect() as conn:
        result = standards_converter.convert(
            conn, std, "SAES-G-005", PUMP, Fake(lambda t: answers[t])
        )
    standards_converter.write(result, tmp_path / "mirror", form_sha=SHA)
    return tmp_path / "mirror"


def test_the_review_reads_the_drafts_only_when_the_switch_names_a_folder(
    tmp_path, monkeypatch
):
    folder = _mirror(tmp_path, {SENTENCE: GOOD})
    rule = _numeric(1, SENTENCE)
    assert settings.standards_converter_dir == ""
    assert rule_roles.reviewed_names([rule], PUMP) == {}  # switch off: not read
    monkeypatch.setattr(settings, "standards_converter_dir", str(folder))
    assert rule_roles.reviewed_names([rule], PUMP) == {"r1": "design pressure"}
    assert (
        rule_roles.reviewed_names([rule], "Pressure Vessel") == {}
    )  # a pump mapping never applies to a vessel
    assert (
        rule_roles.reviewed_names([_numeric(2, "A different sentence.")], PUMP) == {}
    )  # its text must still match


@pytest.mark.parametrize(
    "answer",
    [
        {**GOOD, "applies": "no"},
        {**GOOD, "applies": "depends", "condition": "for this service"},
        {**GOOD, "unit": "psi"},
        {"applies": "yes", "field": None},
    ],
)
def test_only_verified_yes_rows_are_read_by_the_review(tmp_path, monkeypatch, answer):
    folder = _mirror(tmp_path, {SENTENCE: answer})
    monkeypatch.setattr(settings, "standards_converter_dir", str(folder))
    assert rule_roles.reviewed_names([_numeric(1, SENTENCE)], PUMP) == {}


def test_a_file_that_is_not_a_converter_draft_is_not_read(tmp_path, monkeypatch):
    folder = _mirror(tmp_path, {SENTENCE: GOOD})
    path = next(folder.glob("*.json"))
    body = json.loads(path.read_text())
    for tamper in ({"converter": False}, {"status": "approved"}):
        path.write_text(json.dumps({**body, **tamper}))
        monkeypatch.setattr(settings, "standards_converter_dir", str(folder))
        assert rule_roles.reviewed_names([_numeric(1, SENTENCE)], PUMP) == {}
    (folder / "broken.json").write_text("{not json")
    path.write_text(json.dumps(body))
    assert rule_roles.reviewed_names([_numeric(1, SENTENCE)], PUMP) == {
        "r1": "design pressure"
    }


def test_a_reviewed_file_wins_where_it_names_the_same_rule(tmp_path, monkeypatch):
    folder = _mirror(tmp_path, {SENTENCE: GOOD})
    monkeypatch.setattr(settings, "standards_converter_dir", str(folder))
    reviewed = tmp_path / "reviewed"
    rule_roles.export(
        PUMP,
        [
            {
                "standard": "SAES-G-005",
                "clause": "6.1",
                "text_sha256": rule_roles.text_hash(SENTENCE),
                "field": "design_temperature",
            }
        ],
        reviewed / "pump.json",
    )
    monkeypatch.setattr(rule_roles, "DIR", reviewed)
    assert rule_roles.reviewed_names([_numeric(1, SENTENCE, "degC")], PUMP) == {
        "r1": "design temperature"
    }
