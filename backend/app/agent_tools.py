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
from typing import Protocol

from . import ai_review_proposals, numparse, standard_ids, subject_scope
from .agent_edition import (
    NOT_CONFIRMED,
    _not_confirmed,
)
from .reader_api import _fold

VERDICTS = ("GREEN", "YELLOW", "RED")
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
        "description": "Compare a figure quoted from the document with the figure quoted from the clause. Decided by code: meets, does_not_meet, or 'cannot decide'.",
        "params": {
            "doc_quote": "the document's words holding the figure, with unit",
            "clause_quote": "the clause's words holding the figure, with unit",
        },
    },
    {
        "name": "record_finding",
        "description": "Record a finding (GREEN, YELLOW or RED). Code verifies every quote and number; it is stored only when accepted, else refused with the reason.",
        "params": {
            "finding": "{item, doc, color(GREEN|YELLOW|RED), page, doc_quote, clause_quote, standard, clause, action, "
            "priority(must|should|nice), figures(optional list of {doc_quote, clause_quote}), reason}"
        },
    },
    {
        "name": "ask_engineer",
        "description": "Ask the engineer: stores a YELLOW query row. Give the item id and a reason of at most 30 words; no document text.",
        "params": {"item": "item id", "reason": "why the engineer must decide"},
    },
]


#: Words that carry no subject: articles, modals, comparators, requirement words. A CLOSED set: a word not listed here is
#: part of the subject, so a doubtful case ends as "subject not matched" (cannot decide), never as a pass.
NEUTRAL_WORDS = frozenset(
    {
        "a", "an", "the", "of", "is", "are", "be", "been", "shall", "must", "should", "will", "may", "can", "value", "values",
        "comparator", "requirement", "at", "least", "most", "more", "less", "than", "not", "no", "exceed", "exceeding",
        "maximum", "minimum", "max", "min", "required", "limited", "limit", "between", "and", "to", "from", "up", "equal",
        "greater", "lower", "higher", "above", "below", "under", "over", "have", "has", "with", "for", "in", "by",
    }
)  # fmt: skip
_FIRST_NUMBER = re.compile(r"[-+\u2212]?\d")


def _stem(word: str) -> str:
    """Plural endings only (-ies, -es, -s); never -ing or -ed ("bearing" is not "bear"). Same on both sides."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith(("sses", "xes", "ches", "shes", "zes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


_FIGURE_TOKEN = re.compile(
    r"\d+(?:[.,]\d+)*|[\u00bc-\u00be\u2150-\u215e]|\b(?:"
    + "|".join(sorted(ai_review_proposals.NUMBER_WORDS))
    + r")\b",
    re.IGNORECASE,
)
#: A number that names a kind, not a quantity: "Class 150", "Type 2", "No. 3".
_LABEL_NUMBER = re.compile(
    r"\b(?:class|type|no|number|grade|series|schedule|sch|pn|dn|group|category|part|table|item|clause|section|zone|size)\.?\s*#?\d",
    re.IGNORECASE,
)


#: Short words that are words, not labels. Any other token of two letters or fewer in a subject region ("Grade A",
#: "Zone H", "Pump K") is a label we cannot compare, so the quote is ambiguous. A lowercase "a" is the article.
SHORT_WORDS_ALLOWED = frozenset(
    {"of", "is", "to", "be", "no", "or", "at", "in", "by", "an", "as", "on"}
)


def _label_before_number(quote: str) -> str:
    found = _FIRST_NUMBER.search(quote)
    return quote[: found.start()] if found else quote


def _has_short_label(quote: str) -> bool:
    for at, token in enumerate(re.findall(r"[A-Za-z]+", _label_before_number(quote))):
        if len(token) > 2 or token.lower() in SHORT_WORDS_ALLOWED:
            continue
        if token.lower() == "a" and (at == 0 or token == "a"):
            continue  # the article: a lowercase "a", or "A" opening the quote; never "Grade A"
        return True
    return False


def subject_ambiguous(quote: str) -> bool:
    """More than one number in the quote (so the figure's own number cannot be told from a number inside its label), or a
    number that names a kind ("Class 150"). Such a quote is never compared."""
    return (
        len(_FIGURE_TOKEN.findall(quote)) > 1
        or bool(_LABEL_NUMBER.search(quote))
        or _has_short_label(quote)
    )


def subject_words(quote: str) -> frozenset[str]:
    """The subject of a quoted figure: the content words BEFORE its first number (its label), lowercased, punctuation
    stripped, inflections folded, neutral words removed (units are never in a label). A bare value has an empty subject."""
    label = _label_before_number(quote)
    out = set()
    for raw in re.findall(r"[a-z]+", label.lower()):
        word = _stem(raw)
        if raw in NEUTRAL_WORDS or word in NEUTRAL_WORDS:
            continue
        out.add(word)
    return frozenset(out)


class FindingStore(Protocol):
    """Where accepted findings are kept. The loop's `agent_trace.FindingSink` (on disk) and `InMemoryFindings` fit it."""

    def add(self, item_id: str, finding: dict) -> None: ...

    def get(self, item_id: str) -> dict | None: ...

    def has(self, item_id: str) -> bool: ...

    def all(self) -> list[dict]: ...


class InMemoryFindings:
    """Default store, for tests and dry runs. Nothing survives the process."""

    def __init__(self) -> None:
        self._by_item: dict[str, dict] = {}

    def add(self, item_id: str, finding: dict) -> None:
        self._by_item[item_id] = finding

    def get(self, item_id: str) -> dict | None:
        return self._by_item.get(item_id)

    def has(self, item_id: str) -> bool:
        return item_id in self._by_item

    def all(self) -> list[dict]:
        return list(self._by_item.values())


@dataclass
class ToolContext:
    """What a tool may touch. `allowed_document_ids` is the ONLY door to document text (rule 5)."""

    allowed_document_ids: frozenset[str]
    document_id: str  # the document under review
    editions: Mapping[str, str] = field(
        default_factory=dict
    )  # standard -> contract edition
    findings: FindingStore = field(
        default_factory=InMemoryFindings
    )  # sink: accepted findings only
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


def _evidence_from(resolver) -> Callable[[str, str], dict]:
    """Edition evidence from an injected doc resolver (tests: no page quote); with nothing injected it FAILS CLOSED."""
    if resolver is None:
        # no resolver and no evidence function: fail closed, and never open the configured database
        return lambda _s, _e: _not_confirmed("no resolver given")

    def from_resolver(standard: str, edition: str) -> dict:
        doc = resolver(standard, edition)
        if doc is None:
            return _not_confirmed("not resolved")
        return {
            "status": "confirmed",
            "doc": doc,
            "page": None,
            "quote": None,
            "source": "resolver",
        }

    return from_resolver


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

    TOOL_SPECS = TOOL_SPECS  # the loop reads toolbox.TOOL_SPECS

    def __init__(
        self,
        ctx: ToolContext,
        *,
        page_reader: Callable[[str, int], str | None] | None = None,
        searcher: Callable[[str, frozenset[str]], dict] | None = None,
        standard_pages: Callable[[str], list[tuple[int, str]]] | None = None,
        standard_resolver: Callable[[str, str], str | None] | None = None,
        edition_evidence: Callable[[str, str], dict] | None = None,
    ) -> None:
        self.ctx = ctx
        self._page = page_reader or _default_page_reader
        self._search = searcher or _default_search
        self._standard_pages = standard_pages or _default_standard_pages
        self._evidence = edition_evidence or _evidence_from(standard_resolver)
        #: the edition evidence of each standard resolved by get_clause: {standard: evidence}
        self.edition_evidence_seen: dict[str, dict] = {}
        #: compare results this box has made: (clause_figure, doc_figure) -> normalised result
        self.compare_failures = 0
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
            recorded = type(
                exc
            ).__name__  # only the class is recorded, never the message
            return _refuse(f"tool_error:{recorded}")

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
        found = self._evidence(standard, edition)
        doc = found.get("doc") if found.get("status") == "confirmed" else None
        if doc is None or not self._in_scope(doc):
            return None, None, "not held: " + NOT_CONFIRMED
        self.edition_evidence_seen[standard] = {
            k: found.get(k) for k in ("page", "quote", "source")
        }
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
                "edition_evidence": self.edition_evidence_seen.get(standard),
                "text": shown,
                "truncated": len(shown) < len(body),
            },
            [{"doc": standard, "clause": str(clause)}],
        )

    # ---------------------------------------------------------------- compare_number

    def _call_figure_compare(self, doc_quote: str, clause_quote: str) -> object:
        """THE SINGLE CALL SITE of `figure_compare` (#1689): compare(document_quote, clause_quote) -> an object with
        `.verdict` True | False | None and `.reason`."""
        from . import (
            figure_compare,  # lazy: a missing module must give "cannot decide", never a verdict
        )

        return figure_compare.compare(doc_quote, clause_quote)

    @staticmethod
    def _normalise_compare(raw: object) -> dict:
        """True -> meets, False -> does_not_meet, None or any other shape -> cannot decide."""
        verdict = getattr(raw, "verdict", "unknown")
        reason = str(getattr(raw, "reason", "") or "")[:200]
        if verdict is True:
            return {"decided": True, "verdict": "meets", "reason": reason}
        if verdict is False:
            return {"decided": True, "verdict": "does_not_meet", "reason": reason}
        return {
            "decided": False,
            "verdict": "cannot decide",
            "reason": reason or "cannot decide",
        }

    def compare_number(
        self, doc_quote: object = None, clause_quote: object = None
    ) -> dict:
        if (
            not isinstance(doc_quote, str)
            or not isinstance(clause_quote, str)
            or not doc_quote.strip()
            or not clause_quote.strip()
        ):
            return _refuse("quotes_missing")
        if subject_ambiguous(doc_quote) or subject_ambiguous(clause_quote):
            outcome = {
                "decided": False,
                "verdict": "cannot decide",
                "reason": "subject_ambiguous",
            }
            self._compares[(doc_quote.strip(), clause_quote.strip())] = outcome
            return _res(True, outcome)
        doc_subject, clause_subject = (
            subject_words(doc_quote),
            subject_words(clause_quote),
        )
        if not doc_subject or doc_subject != clause_subject:
            # BEFORE figure_compare, whether or not it is importable: a figure is compared only with the same subject
            outcome = {
                "decided": False,
                "verdict": "cannot decide",
                "reason": "subject_mismatch",
                "detail": {
                    "doc_subject": sorted(doc_subject),
                    "clause_subject": sorted(clause_subject),
                },
            }
            self._compares[(doc_quote.strip(), clause_quote.strip())] = outcome
            return _res(True, outcome)
        try:
            outcome = self._normalise_compare(
                self._call_figure_compare(doc_quote, clause_quote)
            )
        except Exception:  # noqa: BLE001  not importable, or it failed: never a verdict
            self.compare_failures += 1  # counted
            outcome = {
                "decided": False,
                "verdict": "cannot decide",
                "reason": "compare unavailable -> cannot decide",
            }
        self._compares[(doc_quote.strip(), clause_quote.strip())] = outcome
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
        finding = {**finding, "color": self._colour(finding)}
        stored = {
            k: finding.get(k)
            for k in (
                "item",
                "color",
                "doc",
                "page",
                "doc_quote",
                "standard",
                "clause",
                "clause_quote",
                "value",
                "reason",
                "action",
                "priority",
            )
            if finding.get(k) not in (None, "")  # null renders as nothing, never 0
        }
        self.ctx.findings.add(str(stored["item"]), stored)
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
                "finding_verdict": stored.get("color"),
            },
            cites,
        )

    def _finding_problem(self, f: dict) -> str | None:
        """None when the finding stands, else the reason it is refused (first failure)."""
        item = str(f.get("item") or "").strip()
        verdict = self._colour(f)
        if not item:
            return "item_missing"
        if self.ctx.findings.has(item):
            return "already recorded"  # the first record stays
        if verdict not in VERDICTS:
            return "color_not_green_yellow_red_or_conflicting"
        if not f.get("doc"):
            return "doc_missing"
        if str(f.get("confidence") or "").strip().lower() == "high":
            return "confidence_never_high"
        if f.get("priority") not in (None, *PRIORITIES):
            return "priority_not_known"
        doc, page = f.get("doc"), _int(f.get("page"))
        quote = str(f.get("doc_quote") or "").strip()
        if doc is not None and not self._in_scope(doc):
            return "document_not_in_scope"
        mentioned = _fold(
            " ".join(
                str(f.get(k) or "") for k in ("reason", "comment", "value", "doc_quote")
            )
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

    @staticmethod
    def _colour(f: dict) -> str | None:
        """The verdict word: 'color' (canonical) or the alias 'verdict'; None when absent, unknown or the two differ."""
        found = {
            str(f[k]).strip().upper()
            for k in ("color", "verdict")
            if isinstance(f.get(k), str) and f[k].strip()
        }
        return (
            found.pop() if len(found) == 1 and next(iter(found)) in VERDICTS else None
        )

    def _numbers_problem(self, f: dict, verdict: str) -> str | None:
        """A number is decided only by code: a GREEN or RED that carries figures needs a decided compare_number that agrees."""
        figures = f.get("figures")
        if not figures:
            return None
        if verdict == "YELLOW":
            return None
        if not isinstance(figures, list):
            return "figures_malformed"
        expect = {"GREEN": "meets", "RED": "does_not_meet"}[verdict]
        for fig in figures:
            if not isinstance(fig, dict):
                return "figures_malformed"
            done = self._compares.get(
                (
                    str(fig.get("doc_quote") or "").strip(),
                    str(fig.get("clause_quote") or "").strip(),
                )
            )
            if done is None or not done["decided"]:
                return "number_not_decided_by_code"
            if done["verdict"] != expect:
                return "verdict_disagrees_with_code_comparison"
        return None

    def _through_verify(self, f: dict, doc: str, page: int, quote: str) -> str | None:
        """The #1667 gate: page, value, clause held, numbers in the words on the page, no verdict word without evidence."""
        standard = str(f.get("standard"))
        clause = str(f.get("clause"))
        proposal = {
            "type": "add",
            "confidence": "low",
            "reason": "finding recorded by the agent reviewer",
            "field": str(f.get("item")),
            "value": str(f.get("value") or "").strip() or quote,
            "text": str(f.get("reason") or f.get("comment") or f.get("item"))[
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
