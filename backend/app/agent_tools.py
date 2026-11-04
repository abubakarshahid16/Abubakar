"""The six tools of the agent reviewer (#1690, spec docs/agent-proof-spec.md). Thin wrappers over existing code.

The lead agent asks for one tool at a time; CODE runs it and verifies. Nothing here decides a verdict by itself:

  open_page        page text from the stored page table (one page, one document).
  search           `search.search`, its ranking untouched, scope narrowed to the allowed documents.
  get_clause       a held standard's clause (scope, conditions, exceptions) at the contract's edition.
  compare_number   `figure_compare` (#1689, not on main yet): decided by code, or "cannot decide".
  record_finding   `ai_review_proposals.verify` (#1667) plus the finding rules; only an accepted finding is stored.
  ask_engineer     a YELLOW query row: item id, a short reason, no document text.

Rules kept here: CLAUDE.md rule 5 (a tool never returns text from a document outside `allowed_document_ids`: the scope is
an intersection, never a union), rule 4 (no claim without a resolving citation, null renders as nothing, "not mentioned"
is never GREEN, confidence is never "high"), rule 13 (no per-layout code). Every result is
{'ok': bool, 'result': dict, 'cites': [{'doc','page'} | {'doc','clause'}]}. The loop logs only 'ok' and 'cites'; the raw
text sits in 'result' and is the model's to read, never the log's.

Nothing in this module opens a socket or loads a model, except that `search` calls the existing search (which may embed the
question locally); tests inject a fake.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field

from . import ai_review_proposals, numparse, standard_ids, subject_scope
from .reader_api import _fold

VERDICTS = ("GREEN", "YELLOW", "RED")
CONFIDENCES = ("low", "medium")  # never "high"
PRIORITIES = ("must", "should", "nice")
MAX_REASON_WORDS = 30
MAX_CLAUSE_CHARS = 6000
MAX_PAGE_CHARS = 20000
MAX_SEARCH_HITS = 10
MIN_QUOTE_CHARS = ai_review_proposals.MIN_QUOTE_CHARS
#: Phrases that mean the document does not say it. Such a finding can never be GREEN.
NOT_MENTIONED_WORDS = (
    "not mentioned",
    "not stated",
    "not given",
    "not provided",
    "not specified",
    "not shown",
    "not found",
    "no mention",
    "absent",
    "missing",
    "blank",
    "n/a",
)

TOOL_SPECS: list[dict] = [
    {
        "name": "open_page",
        "description": "Read one page of one document in scope. Returns the page text with its number; says so when the page is unread or empty.",
        "params": {"doc": "document id", "page": "page number, 1-based"},
    },
    {
        "name": "search",
        "description": "Search the documents in scope (keyword and meaning). Returns passages with document and page.",
        "params": {
            "query": "words to look for",
            "scope": "optional list of document ids; narrowed to the allowed ones",
        },
    },
    {
        "name": "get_clause",
        "description": "Read the full clause of a held standard at the contract's edition, with its scope, conditions and exceptions. Says 'not held' when the standard or edition is not held.",
        "params": {"standard": "standard identifier", "clause": "clause number"},
    },
    {
        "name": "compare_number",
        "description": "Compare a figure from a clause with a figure from the document. Decided by code; may answer 'cannot decide'.",
        "params": {
            "clause_figure": "figure with unit as in the clause",
            "doc_figure": "figure with unit as in the document",
        },
    },
    {
        "name": "record_finding",
        "description": "Record a finding (GREEN, YELLOW or RED). Code verifies every quote and number; it is stored only when accepted, else refused with the reason.",
        "params": {
            "finding": "{item, verdict, doc, page, doc_quote, standard, clause, clause_quote, value, clause_figure, doc_figure, "
            "comment, action, priority, confidence(low|medium)}"
        },
    },
    {
        "name": "ask_engineer",
        "description": "Ask the engineer: stores a YELLOW query row. Give the item id and a reason of at most 30 words; no document text.",
        "params": {"item": "item id", "reason": "why the engineer must decide"},
    },
]


@dataclass
class ToolContext:
    """What a tool may touch. `allowed_document_ids` is the ONLY door to document text (rule 5)."""

    allowed_document_ids: frozenset[str]
    document_id: str  # the document under review
    editions: Mapping[str, str] = field(
        default_factory=dict
    )  # standard -> contract edition
    findings: list[dict] = field(default_factory=list)  # sink: accepted findings only
    queries: list[dict] = field(default_factory=list)  # sink: engineer query rows

    def __post_init__(self) -> None:
        self.allowed_document_ids = frozenset(self.allowed_document_ids)


def _res(ok: bool, result: dict, cites: Iterable[dict] = ()) -> dict:
    return {"ok": ok, "result": result, "cites": list(cites)}


def _refuse(reason: str, cites: Iterable[dict] = ()) -> dict:
    return _res(False, {"refused": reason}, cites)


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _default_page_reader(doc: str, page: int) -> str | None:
    """The stored text of one page, or None when there is no such page row."""
    from .db import connect

    row = (
        connect()
        .execute(
            "SELECT text FROM pages WHERE document_id = ? AND page_no = ?", (doc, page)
        )
        .fetchone()
    )
    return None if row is None else (row["text"] or "")


def _default_standard_pages(doc: str) -> list[tuple[int, str]]:
    return subject_scope.standard_pages(doc)


def _default_standard_resolver(
    allowed: frozenset[str],
) -> Callable[[str, str], str | None]:
    """(standard, edition) -> the allowed document that is that standard at that edition, else None."""

    def resolve(standard: str, edition: str) -> str | None:
        from .db import connect

        want = _fold(edition)
        for doc in sorted(allowed):
            row = (
                connect()
                .execute("SELECT filename FROM documents WHERE id = ?", (doc,))
                .fetchone()
            )
            if row is None:
                continue
            stem = re.sub(
                r"\.(pdf|docx?)$", "", row["filename"] or "", flags=re.IGNORECASE
            )
            if (
                standard_ids.same_standard(standard, stem)
                and want
                and want in _fold(stem)
            ):
                return doc
        return None

    return resolve


def _default_search(query: str, allowed: frozenset[str]) -> dict:
    from . import search as search_module

    return search_module.search(
        query, limit=MAX_SEARCH_HITS, allowed_document_ids=allowed
    )


def _clause_key(clause: str) -> list[tuple[str, str]]:
    ident = re.sub(r"\s+", "", str(clause or "")).upper().rstrip(".")
    return (
        [(kind, ident) for kind in ("number", "lettered", "appendix")] if ident else []
    )


class ToolBox:
    """Runs the six tools for one item or one run. Readers are injectable so tests use invented data."""

    def __init__(
        self,
        ctx: ToolContext,
        *,
        page_reader: Callable[[str, int], str | None] | None = None,
        searcher: Callable[[str, frozenset[str]], dict] | None = None,
        standard_pages: Callable[[str], list[tuple[int, str]]] | None = None,
        standard_resolver: Callable[[str, str], str | None] | None = None,
    ) -> None:
        self.ctx = ctx
        self._page = page_reader or _default_page_reader
        self._search = searcher or _default_search
        self._standard_pages = standard_pages or _default_standard_pages
        self._resolve = standard_resolver or _default_standard_resolver(
            ctx.allowed_document_ids
        )
        #: compare results this box has made: (clause_figure, doc_figure) -> normalised result
        self._compares: dict[tuple[str, str], dict] = {}
        self._tools = {
            "open_page": self.open_page,
            "search": self.search,
            "get_clause": self.get_clause,
            "compare_number": self.compare_number,
            "record_finding": self.record_finding,
            "ask_engineer": self.ask_engineer,
        }

    # ---------------------------------------------------------------- dispatch

    def run(self, name: str, args: object) -> dict:
        tool = self._tools.get(name)
        if tool is None:
            return _refuse("unknown_tool")
        if not isinstance(args, dict):
            return _refuse("arguments_malformed")
        try:
            return tool(**args)
        except TypeError:
            return _refuse("arguments_malformed")
        except Exception as exc:  # noqa: BLE001  a tool failure is a refusal, never a verdict; only the class is reported
            return _refuse(f"tool_error:{type(exc).__name__}")

    def _in_scope(self, doc: object) -> bool:
        return isinstance(doc, str) and doc in self.ctx.allowed_document_ids

    # ---------------------------------------------------------------- open_page

    def open_page(self, doc: object = None, page: object = None) -> dict:
        number = _int(page)
        if not self._in_scope(doc):
            return _refuse("document_not_in_scope")
        if number is None or number < 1:
            return _refuse("page_number_invalid")
        text = self._page(doc, number)
        if text is None:
            return _res(
                False,
                {"doc": doc, "page": number, "state": "page_not_read", "text": None},
            )
        if not text.strip():
            return _res(
                False,
                {
                    "doc": doc,
                    "page": number,
                    "state": "page_has_no_readable_text",
                    "text": None,
                },
            )
        shown = text[:MAX_PAGE_CHARS]
        return _res(
            True,
            {
                "doc": doc,
                "page": number,
                "state": "read",
                "text": shown,
                "truncated": len(shown) < len(text),
            },
            [{"doc": doc, "page": number}],
        )

    # ---------------------------------------------------------------- search

    def search(self, query: object = None, scope: object = None) -> dict:
        if not isinstance(query, str) or not query.strip():
            return _refuse("query_missing")
        allowed = self.ctx.allowed_document_ids
        if scope is not None:
            if not isinstance(scope, (list, tuple, set, frozenset)):
                return _refuse("scope_malformed")
            allowed = allowed & frozenset(
                s for s in scope if isinstance(s, str)
            )  # intersection, never union
        if not allowed:
            return _res(True, {"passages": [], "note": "nothing in scope"})
        out = self._search(query, allowed)
        passages, cites = [], []
        for hit in (out or {}).get("hits", []):
            doc = hit.get("document_id")
            if (
                doc not in allowed
            ):  # belt and braces: never pass on a passage from outside the scope
                continue
            page = hit.get("page_start")
            passages.append({"doc": doc, "page": page, "text": hit.get("text") or ""})
            cites.append({"doc": doc, "page": page})
        return _res(True, {"passages": passages}, cites)

    # ---------------------------------------------------------------- get_clause

    def _edition_of(self, standard: str) -> str | None:
        for name, edition in self.ctx.editions.items():
            if (
                standard_ids.same_standard(standard, name)
                and str(edition or "").strip()
            ):
                return str(edition).strip()
        return None

    def _clause_text(
        self, standard: object, clause: object
    ) -> tuple[str | None, str | None, str | None]:
        """(text, document id, reason when None). Held, in scope, at the contract's edition, else a reason."""
        if (
            not isinstance(standard, str)
            or not standard.strip()
            or not isinstance(clause, str)
        ):
            return None, None, "arguments_malformed"
        edition = self._edition_of(standard)
        if edition is None:
            return None, None, "not held: contract edition unknown"
        doc = self._resolve(standard, edition)
        if doc is None or not self._in_scope(doc):
            return None, None, "not held"
        text = subject_scope.StandardText(self._standard_pages(doc))
        for key in _clause_key(clause):
            spans = text.spans(key)
            if spans:
                start, _soft, end = spans[0]
                lines = [
                    ln
                    for ln, off in zip(text.lines, text.offsets, strict=False)
                    if start <= off < end
                ]
                body = "\n".join(lines).strip()
                if body:
                    return body, doc, None
        return None, doc, "clause not found in the held standard"

    def get_clause(self, standard: object = None, clause: object = None) -> dict:
        body, _doc, reason = self._clause_text(standard, clause)
        if body is None:
            return _res(
                False, {"standard": standard, "clause": clause, "state": reason}
            )
        shown = body[:MAX_CLAUSE_CHARS]
        return _res(
            True,
            {
                "standard": standard,
                "clause": clause,
                "edition": self._edition_of(standard),
                "text": shown,
                "truncated": len(shown) < len(body),
            },
            [{"doc": standard, "clause": str(clause)}],
        )

    # ---------------------------------------------------------------- compare_number

    def _call_figure_compare(self, clause_figure: str, doc_figure: str) -> object:
        """THE SINGLE CALL SITE of `figure_compare` (#1689, branch c3/figure-compare, not on main).
        TODO(#1689): when it is on main, check the real function name and result shape here; one-line change."""
        from . import (
            figure_compare,  # lazy: a missing module must give "cannot decide", never a verdict
        )

        return figure_compare.compare(clause_figure, doc_figure)

    @staticmethod
    def _normalise_compare(raw: object) -> dict:
        """Only a result that clearly says decided with a known verdict is a decision. Anything else cannot decide."""
        if isinstance(raw, Mapping):
            verdict = str(raw.get("verdict") or "").strip().lower()
            if raw.get("decided") is True and verdict in ("meets", "does_not_meet"):
                return {
                    "decided": True,
                    "verdict": verdict,
                    "reason": str(raw.get("reason") or "")[:200],
                }
            return {
                "decided": False,
                "verdict": None,
                "reason": str(raw.get("reason") or "cannot decide")[:200],
            }
        return {"decided": False, "verdict": None, "reason": "cannot decide"}

    def compare_number(
        self, clause_figure: object = None, doc_figure: object = None
    ) -> dict:
        if (
            not isinstance(clause_figure, str)
            or not isinstance(doc_figure, str)
            or not clause_figure.strip()
            or not doc_figure.strip()
        ):
            return _refuse("figures_missing")
        try:
            outcome = self._normalise_compare(
                self._call_figure_compare(clause_figure, doc_figure)
            )
        except Exception:  # noqa: BLE001  not importable, or it failed: never a verdict
            outcome = {
                "decided": False,
                "verdict": None,
                "reason": "compare unavailable -> cannot decide",
            }
        self._compares[(clause_figure.strip(), doc_figure.strip())] = outcome
        return _res(True, outcome)

    # ---------------------------------------------------------------- record_finding

    def _page_text(self, doc: str, page: int) -> str | None:
        text = self._page(doc, page)
        return text if text and text.strip() else None

    def record_finding(self, finding: object = None) -> dict:
        if not isinstance(finding, dict):
            return _res(
                False,
                {
                    "verdict": "refused",
                    "accepted": False,
                    "reason": "finding_malformed",
                },
            )
        why = self._finding_problem(finding)
        if why:
            return _res(
                False,
                {
                    "verdict": "refused",
                    "accepted": False,
                    "reason": why,
                    "refused": why,
                },
            )
        stored = {
            k: finding.get(k)
            for k in (
                "item",
                "verdict",
                "doc",
                "page",
                "doc_quote",
                "standard",
                "clause",
                "clause_quote",
                "value",
                "comment",
                "action",
                "priority",
                "confidence",
            )
            if finding.get(k) not in (None, "")  # null renders as nothing, never 0
        }
        self.ctx.findings.append(stored)
        cites = []
        if stored.get("doc") and stored.get("page"):
            cites.append({"doc": stored["doc"], "page": stored["page"]})
        if stored.get("standard") and stored.get("clause"):
            cites.append({"doc": stored["standard"], "clause": str(stored["clause"])})
        return _res(
            True,
            {
                "verdict": "accepted",
                "accepted": True,
                "reason": None,
                "item": stored.get("item"),
                "finding_verdict": stored.get("verdict"),
            },
            cites,
        )

    def _finding_problem(self, f: dict) -> str | None:
        """None when the finding stands, else the reason it is refused (first failure)."""
        item = str(f.get("item") or "").strip()
        verdict = f.get("verdict")
        if not item:
            return "item_missing"
        if verdict not in VERDICTS:
            return "verdict_not_green_yellow_red"
        if f.get("confidence") not in CONFIDENCES:
            return "confidence_not_low_or_medium"  # never "high"
        if f.get("priority") not in (None, *PRIORITIES):
            return "priority_not_known"
        doc, page = f.get("doc"), _int(f.get("page"))
        quote = str(f.get("doc_quote") or "").strip()
        if doc is not None and not self._in_scope(doc):
            return "document_not_in_scope"
        mentioned = _fold(
            " ".join(str(f.get(k) or "") for k in ("comment", "value", "doc_quote"))
        )
        says_absent = (
            any(_fold(w) in mentioned for w in NOT_MENTIONED_WORDS)
            or f.get("mentioned") is False
        )
        if verdict == "GREEN" and says_absent:
            return "not_mentioned_is_never_green"
        if verdict in ("GREEN", "RED"):
            if not quote or doc is None or page is None:
                return "document_quote_with_page_required"
            if (
                not str(f.get("clause_quote") or "").strip()
                or not f.get("standard")
                or not f.get("clause")
            ):
                return "clause_quote_required"
        if not quote and not f.get("clause_quote"):
            return None  # a YELLOW query with nothing to verify; ask_engineer is the usual door
        if quote:
            if doc is None or page is None:
                return "document_quote_with_page_required"
            page_text = self._page_text(doc, page)
            if page_text is None:
                return "page_not_read"
            if len(quote) < MIN_QUOTE_CHARS:
                return "evidence_quote_too_short"
            if _fold(quote) not in _fold(page_text):
                return "document_quote_not_on_page"
        clause_text = None
        if f.get("clause_quote") or (verdict in ("GREEN", "RED")):
            clause_text, _cdoc, why = self._clause_text(
                f.get("standard"), f.get("clause")
            )
            if clause_text is None:
                return f"clause_not_verified:{why}"
            cq = str(f.get("clause_quote") or "").strip()
            if len(cq) < MIN_QUOTE_CHARS or _fold(cq) not in _fold(clause_text):
                return "clause_quote_not_in_clause"
        value = str(f.get("value") or "").strip()
        if (
            value
            and quote
            and not numparse.value_in_text(value, self._page_text(doc, page) or "")
        ):
            return "value_not_on_page"
        problem = self._numbers_problem(f, verdict)
        if problem:
            return problem
        if quote and clause_text is not None:
            return self._through_verify(f, doc, page, quote)
        return None

    def _numbers_problem(self, f: dict, verdict: str) -> str | None:
        """A number is decided only by code: a GREEN or RED that carries figures needs a decided compare_number that agrees."""
        cf, df = (
            str(f.get("clause_figure") or "").strip(),
            str(f.get("doc_figure") or "").strip(),
        )
        if not cf and not df:
            return None
        if verdict == "YELLOW":
            return None
        done = self._compares.get((cf, df))
        if done is None or not done["decided"]:
            return "number_not_decided_by_code"
        expect = {"GREEN": "meets", "RED": "does_not_meet"}[verdict]
        return (
            None
            if done["verdict"] == expect
            else "verdict_disagrees_with_code_comparison"
        )

    def _through_verify(self, f: dict, doc: str, page: int, quote: str) -> str | None:
        """The #1667 gate: page, value, clause held, numbers in the words on the page, no verdict word without evidence."""
        standard = str(f.get("standard"))
        clause = str(f.get("clause"))
        proposal = {
            "type": "add",
            "confidence": f.get("confidence"),
            "reason": "finding recorded by the agent reviewer",
            "field": str(f.get("item")),
            "value": str(f.get("value") or "").strip() or quote,
            "text": str(f.get("comment") or f.get("item"))[
                : ai_review_proposals.MAX_TEXT_CHARS
            ],
            "page": page,
            "standard": standard,
            "clause": clause,
            "evidence": [{"page": page, "quote": quote}],
        }
        page_text = self._page_text(doc, page) or ""
        ctx = ai_review_proposals.Context(
            pages={page: page_text}, rows={}, held={standard: [clause]}
        )
        verdict = ai_review_proposals.verify(proposal, ctx)
        return None if verdict.accepted else f"verify_refused:{verdict.reason}"

    # ---------------------------------------------------------------- ask_engineer

    def ask_engineer(self, item: object = None, reason: object = None) -> dict:
        item_id = str(item or "").strip()
        words = str(reason or "").split()
        if not item_id:
            return _refuse("item_missing")
        if not words:
            return _refuse("reason_missing")
        if len(words) > MAX_REASON_WORDS:
            return _refuse("reason_longer_than_30_words")
        row = {
            "item": item_id,
            "verdict": "YELLOW",
            "reason": " ".join(words),
            "kind": "engineer_query",
        }
        self.ctx.queries.append(row)
        return _res(True, {"queued": True, "item": item_id, "verdict": "YELLOW"})
