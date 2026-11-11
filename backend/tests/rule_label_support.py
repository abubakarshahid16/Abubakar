"""Shared fixtures for the rule-label tests: an invented database copy, an invented model. No real document text."""

from __future__ import annotations

import hashlib
import json
import sqlite3

from app import claude_approved, compiled_rule_report, rule_labels
from app.config import settings

#: A quote that states a quantity, and one that does not. Invented.
QUOTE_NUM = "The set pressure shall not exceed 10 bar for the invented item."
QUOTE_TXT = "The supplier shall provide a written statement of the invented scope."
STANDARD = "SAES-X-100.pdf"
OTHER_STANDARD = "ZZZ-X-100.pdf"
ENV = {
    "REASONING_PROVIDER": "claude",
    "STANDARDS_READER_ENABLED": "1",
    "STANDARDS_READER_ALLOW_PUBLIC_EGRESS": "1",
    "ANTHROPIC_API_KEY": "test-key-not-real",
}
USAGE = {
    "input_tokens": 1000,
    "output_tokens": 100,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 0,
}
MODEL_A, MODEL_B = "claude-sonnet-5-5", "claude-opus-5-5"


def make_db(
    path,
    *,
    requirements=(("r1", QUOTE_NUM), ("r2", QUOTE_TXT)),
    standard=STANDARD,
    with_book=False,
):
    """A database copy holding only what the label job reads: documents, standard_requirements, and (with_book) a
    minimal rule book with approvals. Returns the path."""
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE documents (id TEXT PRIMARY KEY, filename TEXT)")
    conn.execute("INSERT INTO documents VALUES ('d1', ?)", (standard,))
    conn.execute(
        "CREATE TABLE standard_requirements (id TEXT PRIMARY KEY, standard_document_id TEXT, clause TEXT, page INTEGER,"
        " source_text TEXT, superseded_at TEXT)"
    )
    for i, (rid, quote) in enumerate(requirements, 1):
        conn.execute(
            "INSERT INTO standard_requirements VALUES (?, 'd1', ?, 1, ?, NULL)",
            (rid, f"4.{i}", quote),
        )
    if with_book:
        conn.execute(
            "CREATE TABLE rulebook_rule (id TEXT PRIMARY KEY, rule_key TEXT, standard TEXT)"
        )
        conn.execute(
            "CREATE TABLE rulebook_version (id TEXT PRIMARY KEY, rule_id TEXT, version_no INTEGER)"
        )
        conn.execute(
            "CREATE TABLE rulebook_provenance (id TEXT PRIMARY KEY, rule_version_id TEXT, standard_document_id TEXT,"
            " clause TEXT, page INTEGER, quote TEXT)"
        )
        conn.execute(
            "CREATE TABLE rulebook_approval (id TEXT PRIMARY KEY, rule_version_id TEXT, decision TEXT, approver_id TEXT,"
            " decided_at TEXT, equipment_type TEXT, tier TEXT)"
        )
        conn.execute("INSERT INTO rulebook_rule VALUES ('rule1', 'k1', ?)", (standard,))
        conn.execute("INSERT INTO rulebook_version VALUES ('v1', 'rule1', 1)")
        conn.execute(
            "INSERT INTO rulebook_provenance VALUES ('p1', 'v1', 'd1', '4.1', 1, ?)",
            (QUOTE_NUM,),
        )
        conn.execute(
            "INSERT INTO rulebook_approval VALUES ('a1', 'v1', 'approve', 'u1', '2026-11-01', 'kind_x', 'engineer')"
        )
    conn.commit()
    conn.close()
    return path


def patch_pages(monkeypatch, pages=None, origin=None):
    """The page text the app would cite, for document d1 (and a low-confidence OCR flag when `origin` says so)."""
    pages = (
        pages
        if pages is not None
        else {1: f"{QUOTE_NUM}\n{QUOTE_TXT}\nA closing line of the invented page."}
    )
    monkeypatch.setattr(
        compiled_rule_report,
        "pages_of",
        lambda conn, sdid: dict(pages) if sdid == "d1" else {},
    )
    monkeypatch.setattr(
        compiled_rule_report,
        "page_origin",
        lambda conn, sdid: (
            dict(
                origin
                if origin is not None
                else {
                    n: {"page_source": "native", "page_min_conf": None} for n in pages
                }
            )
            if sdid == "d1"
            else {}
        ),
    )


def table_hash(conn, table):
    rows = [tuple(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY 1")]
    return len(rows), hashlib.sha256(json.dumps(rows, default=str).encode()).hexdigest()


def reading(
    values=(10.0,),
    comparator="le",
    unit="bar",
    strength="shall",
    subject="the invented item",
):
    return {
        "comparator": comparator,
        "values": list(values),
        "unit": unit,
        "strength": strength,
        "subject": subject,
    }


def answer(
    model=MODEL_A,
    kind="datasheet",
    field="a_field",
    rd=None,
    valid=True,
    prompt=rule_labels.PROMPT_VERSION,
):
    rd = rd if rd is not None else reading()
    content = {
        "paper_kind": kind,
        "field": field if kind == "datasheet" else None,
        "reading": rd,
        "valid": valid,
    }
    return rule_labels.PassAnswer(
        model,
        prompt,
        content["paper_kind"],
        content["field"],
        rd,
        valid,
        rule_labels.answer_hash(content),
    )


class FakeModel:
    """A sender that answers per rule. `fn(rule_dict) -> answer dict or None` (None: leaves the rule out)."""

    def __init__(self, fn=None, model_id=None):
        self.calls, self.bodies, self.fn, self.model_id = (
            0,
            [],
            fn or self.good,
            model_id,
        )

    @staticmethod
    def good(rule):
        start = " ".join(rule["quote"].split()[:3])
        if "10 bar" in rule["quote"]:
            return {
                "n": rule["n"],
                "start": start,
                "paper_kind": "datasheet",
                "field": FIELD(),
                "comparator": "le",
                "values": [10],
                "unit": "bar",
                "strength": "shall",
                "subject": "the invented item",
                "reason": "limit",
            }
        return {
            "n": rule["n"],
            "start": start,
            "paper_kind": "contract",
            "field": None,
            "comparator": "required",
            "values": [],
            "unit": None,
            "strength": "shall",
            "subject": "the supplier",
            "reason": "duty",
        }

    def __call__(self, url, *, headers, body, timeout):
        self.calls += 1
        self.bodies.append(body)
        rules = json.loads(body["messages"][0]["content"][0]["text"])["rules"]
        answers = [a for a in (self.fn(r) for r in rules) if a is not None]
        return {
            "model": self.model_id or body["model"],
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": json.dumps({"answers": answers})}],
            "usage": USAGE,
        }


def FIELD() -> str:
    from app import rule_label_job

    return next(iter(rule_label_job.field_list()))


def declared():
    return claude_approved.carrying(["d1"])


def switch(monkeypatch, on=True):
    monkeypatch.setattr(settings, "agent_review_enabled", on)
