"""Shared fixtures for the AI reviewer's job and route tests: an invented paper, an invented rule book, an invented model.

No real document text. The fake model never touches a network: it answers from a table of invented answers and counts what
it was asked, so a test can say exactly which items were sent to the lead model.
"""

from __future__ import annotations

import hashlib
import json
import threading

from app import db, rule_label_schema, rule_labels
from app.config import settings

PAPER, STD = "doc_paper", "doc_std"
PAPER_PAGE = "DATA SHEET\nCoating thickness: 0.35 mm\nMarking blue\nCoating layers two\nSerial invented"
STD_PAGE = (
    "4.1 Frame\nThe coating thickness shall be at least 0.2 mm on every outside surface.\n"
    "4.3 Marking\nThe marking shall be in red for every unit.\n"
    "4.4 Coating\nThe coating shall be applied in two layers of equal depth.\n"
    "4.5 Colour\nThe housing shall be painted in a single colour."
)
ENV = {
    "REASONING_PROVIDER": "claude",
    "STANDARDS_READER_ENABLED": "1",
    "STANDARDS_READER_ALLOW_PUBLIC_EGRESS": "1",
    "ANTHROPIC_API_KEY": "test-key-not-real",
}
H = "b" * 64
A_MODEL, B_MODEL = "claude-sonnet-5-5", "claude-opus-5-5"

#: item id -> (rule quote, clause, rule kind, comparator, value, unit)
RULES = {
    "R-coat": (
        "The coating shall be applied in two layers of equal depth.",
        "4.4",
        None,
        None,
        None,
        None,
    ),
    "R-frame": (
        "The coating thickness shall be at least 0.2 mm on every outside surface.",
        "4.1",
        "limit",
        ">=",
        0.2,
        "mm",
    ),
    "R-mark": (
        "The marking shall be in red for every unit.",
        "4.3",
        None,
        None,
        None,
        None,
    ),
    "R-colour": (
        "The housing shall be painted in a single colour.",
        "4.5",
        None,
        None,
        None,
        None,
    ),
}
#: the rule label's field per item (a Pass needs the quoted page line to carry it)
FIELDS = {
    "R-coat": "coating_layers",
    "R-frame": "coating_thickness",
    "R-mark": "marking",
    "R-colour": "colour",
}
#: what the invented lead says per item (a missing key: the lead leaves the item out of its answer)
ANSWERS = {
    "R-coat": {
        "paper_page": 1,
        "paper_quote": "Coating layers two",
        "clause_quote": RULES["R-coat"][0],
        "reasoning": "two layers are stated",
        "comment": "none",
        "verdict": "Pass",
        "reason_code": "met",
        "field_label": "Coating layers",
    },
    "R-frame": {
        "paper_page": 1,
        "paper_quote": "Coating thickness: 0.35 mm",
        "clause_quote": RULES["R-frame"][0],
        "paper_figure": "Coating thickness: 0.35 mm",
        "clause_figure": "coating thickness shall be at least 0.2 mm",
        "reasoning": "width above the minimum",
        "comment": "none",
        "verdict": "Pass",
        "reason_code": "met",
        "field_label": "Coating thickness",
    },
    "R-mark": {
        "paper_page": 1,
        "paper_quote": "Marking blue",
        "clause_quote": RULES["R-mark"][0],
        "reasoning": "the marking is blue, not red",
        "comment": "make the marking red",
        "verdict": "Fail",
        "reason_code": "not_met",
        "field_label": "Marking",
    },
}


def item(item_id: str, *, tier: str = "AI approved", kind: str = "datasheet") -> dict:
    _quote, clause, rule_kind, op, value, unit = RULES[item_id]
    return {
        "item_id": item_id,
        "source": "rule",
        "rule_version_id": f"req-{item_id}",
        "standard": "INV-STD-100",
        "standard_document_id": STD,
        "clause": clause,
        "clause_page": 1,
        "rule_kind": rule_kind,
        "requirement_type": "numeric_limit" if rule_kind else "statement",
        "comparator": op,
        "value": value,
        "unit": unit,
        "field_roles": [],
        "question": f"does the paper meet clause {clause}",
        "page_hint": [1],
        "clause_quote_ref": f"C-{item_id}",
        "rule_quote_ref": f"Q-{item_id}",
        "rule_label": {
            "paper_kind": kind,
            "field": FIELDS.get(item_id),
            "tier": tier,
            "state": "ai_approved",
        },
    }


def item_doc(
    ids=("R-coat", "R-frame", "R-mark", "R-colour"), left_out=()
) -> tuple[dict, dict]:
    """(the item document the builder would return, its clause cache)."""
    cache = {}
    for i in ids:
        quote, clause = RULES[i][0], RULES[i][1]
        cache[f"Q-{i}"] = {
            "text": quote,
            "page": 1,
            "source": "rule_quote",
            "standard_document_id": STD,
            "clause": clause,
        }
        cache[f"C-{i}"] = {
            "text": quote,
            "page": 1,
            "source": "rule_quote",
            "standard_document_id": STD,
            "clause": clause,
        }
    block = {
        "on": True,
        "paper_kind": "datasheet",
        "paper_kind_known": True,
        "counts": {
            "needs_another_paper": {
                "total": len(left_out),
                "by_kind": {"procedure": len(left_out)},
            }
        },
        "left_out": list(left_out),
        "summary_lines": ["another equipment type: 2 rules not asked (pump 2)"],
        "equipment": {
            "paper_equipment_state": "usable",
            "paper_types": ["invented_type"],
        },
        "missing_rule_books": [
            {"rule_book": "INV-MISSING-9", "why": "cited by the paper"}
        ],
    }
    items = [item(i) for i in ids]
    return {
        "paper": PAPER,
        "paper_kind": "datasheet",
        "made_at": "2026-11-11T00:00:00Z",
        "counts": {"skill": 0, "rule": len(items)},
        "items": items,
        "rule_labels": block,
    }, cache


def label_rows(conn, ids, state="ai_approved") -> None:
    """An approved label per rule, as the table's own guard demands (two models, one prompt, hashes, a page)."""
    rule_label_schema.create_tables(conn)
    for i in ids:
        cols = {
            "source": "requirement",
            "rule_ref": f"req-{i}",
            "rule_version_id": f"v-{i}",
            "state": state,
            "paper_kind": "datasheet",
            "labelled_at": "2026-11-11T00:00:00Z",
            "a_model": A_MODEL,
            "b_model": B_MODEL,
            "a_prompt": rule_labels.PROMPT_VERSION,
            "b_prompt": rule_labels.PROMPT_VERSION,
            "a_answer_sha256": H,
            "b_answer_sha256": H,
            "quote_sha256": H,
            "quote_page": 1,
            "reading_json": '{"comparator": "required", "values": [], "unit": null, "strength": "shall"}',
        }
        conn.execute(
            f"INSERT INTO rule_label ({', '.join(cols)}) VALUES ({','.join('?' * len(cols))})",
            tuple(cols.values()),
        )
    conn.commit()


def add_document(conn, doc_id: str, filename: str, text: str) -> None:
    conn.execute(
        "INSERT INTO documents(id, filename, sha256, size_bytes, stored_path, status, uploaded_at)"
        " VALUES (?,?,?,1,'x','ready','2020-01-01')",
        (doc_id, filename, hashlib.sha256(doc_id.encode()).hexdigest()),
    )
    conn.execute(
        "INSERT INTO pages(document_id, page_no, text, char_count, batch_no) VALUES (?,1,?,?,0)",
        (doc_id, text, len(text)),
    )
    # the search chunk a stored paper has: a paper with page text but no chunk is stopped before any rule is chosen (C2)
    conn.execute(
        "INSERT INTO chunks(id, document_id, filename, ordinal, page_start, page_end, text, token_count, content_hash)"
        " VALUES (?,?,?,0,1,1,?,?,?)",
        (
            f"{doc_id}:c0",
            doc_id,
            filename,
            text,
            len(text.split()),
            hashlib.sha256(text.encode()).hexdigest(),
        ),
    )
    conn.commit()


def setup_world(tmp_path, monkeypatch, *, on: bool = True) -> None:
    """A throwaway database with the invented paper and rule book, the switch, a private spend log."""
    from app.agent_claude import reset_shared_meter_for_tests

    reset_shared_meter_for_tests()
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "agent.sqlite")
    monkeypatch.setattr(settings, "startup_warmup", False)
    monkeypatch.setattr(settings, "agent_review_enabled", on)
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    monkeypatch.setattr(settings, "claude_cache_dir", tmp_path / "cache")
    monkeypatch.setattr(settings, "claude_budget_usd_per_step", 5.0)
    monkeypatch.setattr(settings, "claude_budget_usd_total", 20.0)
    monkeypatch.setattr(settings, "claude_approved_list_enforced", False)
    db.reset_connection()
    db.init_db()
    with db.connect() as conn:
        add_document(conn, PAPER, "paper.pdf", PAPER_PAGE)
        add_document(conn, STD, "INV-STD-100.pdf", STD_PAGE)


class FakeModel:
    """An invented Claude. Lead batches are answered from `answers`; second opinions say `agree`; the context check says the
    rule carries no limiting condition. `lead_asked` lists the item ids of each lead call, in order."""

    LEAD, SECOND = "fake-lead-model-1", "fake-second-model-2"

    def __init__(self, answers=None, agree=True, cut_first=False, second_model=None):
        self.answers = dict(ANSWERS if answers is None else answers)
        self.agree, self.cut_first = agree, cut_first
        self.second_name = second_model or self.SECOND
        self.lead_asked: list[list[str]] = []
        self.kinds: list[str] = []
        self._lock = threading.Lock()

    def __call__(self, url, *, headers, body, timeout):
        usage = {
            "input_tokens": 3000,
            "output_tokens": 600,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        }
        system = json.dumps(body.get("system"))
        if "CONTEXT CHECK" in system:
            self.kinds.append("context")
            return self._reply(self.second_name, usage, json.dumps({"limits": False}))
        if "independent senior engineer" in system:
            self.kinds.append("second")
            return self._reply(
                self.second_name,
                usage,
                json.dumps({"agree": self.agree, "reason": "fake"}),
            )
        last = body["messages"][0]["content"][-1]["text"]
        ids = [q["item_id"] for q in json.loads(last.split("\n\n")[0])["items"]]
        with self._lock:
            self.lead_asked.append(ids)
            self.kinds.append("lead")
            cut = self.cut_first and len(self.lead_asked) == 1
        if cut:  # the answer stops at max_tokens: half a JSON text
            reply = self._reply(self.LEAD, usage, '{"answers": [{"item_id": "R-co')
            reply["stop_reason"] = "max_tokens"
            return reply
        got = [{"item_id": i, **self.answers[i]} for i in ids if i in self.answers]
        return self._reply(self.LEAD, usage, json.dumps({"answers": got}))

    @staticmethod
    def _reply(model, usage, text):
        return {
            "model": model,
            "stop_reason": "end_turn",
            "usage": usage,
            "content": [{"type": "text", "text": text}],
        }
