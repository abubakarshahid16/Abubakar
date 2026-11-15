"""Test support for the calculator's proof: the exit re-reads the page from the store, so a unit test that builds a line by hand gives the store a page.

`install(monkeypatch)` replaces the exit's page source with a dict and wraps `numeric_line` / `checklist_lines` so that the page text a test hands them is
registered under the document id ("doc1") they are given. Nothing here reads a database."""

from __future__ import annotations

from app import agent_review_calculator as calc
from app import agent_review_code_proof as proof

DOC = "doc1"


def install(monkeypatch) -> dict:
    pages: dict = {}
    monkeypatch.setattr(
        proof, "PAGE_SOURCE", [lambda doc, page: pages.get((doc, page))]
    )
    real_numeric, real_checklist = calc.numeric_line, calc.checklist_lines

    def numeric_line(item, requirement, fact, *, page_text=None, document_id=DOC, **kw):
        if fact and page_text is not None:
            pages[(document_id, fact.get("page"))] = page_text
        return real_numeric(
            item, requirement, fact, page_text=page_text, document_id=document_id, **kw
        )

    def checklist_lines(results, *, page_texts, document_id=DOC, **kw):
        for k, v in page_texts.items():
            pages[(document_id, k)] = v
        return real_checklist(
            results, page_texts=page_texts, document_id=document_id, **kw
        )

    monkeypatch.setattr(calc, "numeric_line", numeric_line)
    monkeypatch.setattr(calc, "checklist_lines", checklist_lines)
    return pages
