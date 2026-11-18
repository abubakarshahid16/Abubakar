"""Shared fixtures for the general review's tests (`app.aim_review`). Invented documents only: no client identifier, no real text.

A throwaway database holds one paper (a contractor submittal, two pages) and three rule books, each with stored rules labelled for
datasheets. Book C is held but NOT on the list a test passes as `allowed_books`. Nothing here asks a real model or opens a socket.
"""

from __future__ import annotations

import hashlib
import json

from app import access, db
from app.config import settings

PAPER = "doc_aimpaper01"
BOOK_A = "doc_aimbookA1"
BOOK_B = "doc_aimbookB1"
BOOK_C = "doc_aimbookC1"  # held, never on the list

PAPER_PAGES = {
    1: "GENERAL DATA SHEET FOR A TEST ITEM OF TYPE QX\n"
    "Design pressure of the test item: 12 bar gauge at the inlet\n"
    "Operating temperature of the test item: 80 degC at the outlet\n",
    2: "Body material of the test item: carbon steel to the buyer list\n"
    "Noise level of the test item: to be advised by the vendor later\n",
}
BOOK_RULES = {
    BOOK_A: [
        (
            "4.1",
            3,
            "The design pressure of the item shall not exceed 20 bar gauge in any case.",
        ),
        (
            "4.2",
            3,
            "The operating temperature shall be stated on the data sheet for every item.",
        ),
    ],
    BOOK_B: [
        (
            "7.3",
            5,
            "The body material shall be stated together with the material grade.",
        )
    ],
    BOOK_C: [
        (
            "9.9",
            2,
            "A noise level shall be guaranteed by the vendor for every item supplied.",
        )
    ],
}
#: Invented PUBLIC-family books (offered by subject and type); a company standard is offered only when cited or table-named.
FILENAMES = {
    BOOK_A: "ISO 99101.pdf",
    BOOK_B: "ISO 99202.pdf",
    BOOK_C: "ISO 99303.pdf",
}


def _hex(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _doc(conn, doc_id: str, filename: str, role: str, pages: dict[int, str]) -> None:
    conn.execute(
        "INSERT INTO documents (id, filename, sha256, size_bytes, stored_path, page_count, status, uploaded_at)"
        " VALUES (?, ?, ?, 1, ?, ?, 'indexed', '2026-11-18T00:00:00Z')",
        (doc_id, filename, _hex(doc_id), f"/nowhere/{doc_id}", len(pages)),
    )
    conn.execute(
        "INSERT INTO document_classification (document_id, document_role, suggested_by) VALUES (?, ?, 'test')",
        (doc_id, role),
    )
    for n, t in pages.items():
        conn.execute(
            "INSERT INTO pages (document_id, page_no, text, char_count, batch_no) VALUES (?, ?, ?, ?, 0)",
            (doc_id, n, t, len(t)),
        )


def build_db() -> None:
    from app import rule_equipment, rule_label_schema, submittal_review

    db.init_db()
    submittal_review.ensure_schema()
    conn = db.connect()
    rule_label_schema.create_tables(
        conn
    )  # their ensure_schema is behind a switch; the tables are what is read here
    rule_equipment.create_tables(conn)
    with conn:
        _doc(conn, PAPER, "paper-one.pdf", "CONTRACTOR_SUBMITTAL", PAPER_PAGES)
        for book, rules in BOOK_RULES.items():
            pages = {}
            for _clause, page, text in rules:
                pages[page] = (
                    pages.get(page, f"Section heading of {FILENAMES[book]}\n")
                    + text
                    + "\n"
                )
            _doc(conn, book, FILENAMES[book], "COMPANY_STANDARD", pages)
            for i, (clause, page, text) in enumerate(rules):
                rid = f"req_{book}_{i}"
                conn.execute(
                    "INSERT INTO standard_requirements (id, standard_document_id, clause, page, requirement_text,"
                    " source_text, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'x', 'x')",
                    (rid, book, clause, page, text, text),
                )
                conn.execute(
                    "INSERT INTO rule_label (source, rule_ref, paper_kind, state, a_model, a_prompt, a_answer_sha256,"
                    " b_model, b_prompt, b_answer_sha256, reading_json, quote_page, quote_sha256, labelled_at)"
                    " VALUES ('requirement', ?, 'datasheet', 'ai_approved', 'model-a', 'p', ?, 'model-b', 'p', ?, ?, ?, ?,"
                    " 'x')",
                    (
                        rid,
                        _hex("a" + rid),
                        _hex("b" + rid),
                        json.dumps({"subject": "test subject"}),
                        page,
                        _hex(rid),
                    ),
                )


def open_aim_db(tmp_path, monkeypatch):
    """The throwaway database, as a generator for each test module's own `aim_db` fixture."""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "aim.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    # The owner's approved list is not what these tests are about (B's tests own the gate): the list is not enforced here,
    # and the gate is still asked on every call (blocks, the shown list, contracts).
    monkeypatch.setattr(settings, "claude_approved_list_enforced", False)
    # The general review runs only where the AI reviewer's lane is on; its rule-label tables exist only then.
    monkeypatch.setattr(settings, "agent_review_enabled", True)
    # The suite pins the old engine on (`env_isolation`); a test of the general review switches it off itself.
    monkeypatch.setattr(settings, "review_old_engine_enabled", False)
    db.reset_connection()
    build_db()
    yield db.connect()
    db.reset_connection()


class MemoryStore:
    """A ChecklistStore in memory: put never overwrites (an older checklist stays), get returns the newest."""

    def __init__(self) -> None:
        self.saved: dict[str, list[tuple[str, dict]]] = {}
        self.puts: list[dict] = []

    def get(self, key: str) -> dict | None:
        rows = self.saved.get(key)
        return dict(rows[-1][1], sha256=rows[-1][0]) if rows else None

    def put(self, key: str, checklist: dict, *, run_id: str, usd: float) -> str:
        raw = json.dumps(checklist, sort_keys=True, ensure_ascii=False).encode()
        sha = hashlib.sha256(raw).hexdigest()
        self.saved.setdefault(key, []).append((sha, json.loads(raw)))
        self.puts.append({"key": key, "run_id": run_id, "usd": usd})
        return sha
