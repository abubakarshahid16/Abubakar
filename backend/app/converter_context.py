"""What the standards converter shows the model besides the sentence, and what it checks of the answer (order 305.1).

A sentence alone hides its conditions: the heading above it ("Single-device installation"), the page it sits on (an
appendix, a special part, a worked example) and the sentence just before it ("Where the fluid is a liquid:").
`DocContext` gives each stored rule those four things from the library itself; no new extraction, no model, no network:

  * `heading_path` - the stored section titles of the clause's parents (clause 5.3.4.1: the titles stored for 5, 5.3 and
    5.3.4), else the chunk's own section; at most 4, 80 characters each;
  * `page`, `scope` and `region` - `page_scope.tag_pages` over the document's page text; a page that is not main body,
    or that holds a worked example, means the rule is NOT SENT to the model (`scope_not_main_body`, counted by region):
    it can only decide through an approved card;
  * `before` and `after` - the neighbouring sentences of the same chunk, 240 characters each.

The model must name the words that say when the limit holds (`condition`) and copy them exactly (`condition_quote`)
from the sentence, the heading path, `before` or `after`. `condition_refusal` is the code's side: a condition with no
quote, a quote found nowhere in what was shown, or a quote found only OUTSIDE the sentence is "unproven" with a named
reason. It cannot prove that "none" is right: a second question (order 305.4) and the hand check stay.

Pure apart from `load`, which only reads."""

from __future__ import annotations

import re

from . import converter_gates, page_scope

#: Longest neighbouring sentence, and longest heading, shown to the model.
NEIGHBOUR_CHARS = 240
HEADING_CHARS = 80
MAX_HEADINGS = 4
MAIN = page_scope.MAIN
_SECTION = re.compile(r"^\s*([A-Z]{0,2}\d+(?:\.\d+)*)\.?\s+(\S.*)$")
_SENTENCE_END = re.compile(r"(?<=[.;:!?])\s+|\n+")


def _clean(text: str, size: int) -> str:
    return " ".join((text or "").split())[:size]


class DocContext:
    """The context of the rules of ONE standard document."""

    def __init__(self, tags: dict[int, dict], titles: dict[str, str]):
        self.tags = tags
        self.titles = titles

    @classmethod
    def load(cls, conn, document_id: str) -> DocContext:
        pages = {
            r["page_no"]: r["text"]
            for r in conn.execute(
                "SELECT page_no, text FROM pages WHERE document_id = ?", (document_id,)
            )
        }
        titles: dict[str, str] = {}
        for r in conn.execute(
            "SELECT DISTINCT section FROM chunks WHERE document_id = ? AND section IS NOT NULL",
            (document_id,),
        ):
            m = _SECTION.match(r["section"] or "")
            if m:
                titles.setdefault(m.group(1), _clean(m.group(2), HEADING_CHARS))
        return cls(page_scope.tag_pages(pages), titles)

    def heading_path(self, clause: str | None, section: str | None) -> list[str]:
        parts = str(clause or "").strip().rstrip(".").split(".")
        path = []
        for n in range(1, len(parts) + 1):
            title = self.titles.get(".".join(parts[:n]))
            if title and title not in path:
                path.append(title)
        if not path:
            m = _SECTION.match(section or "")
            own = _clean(m.group(2) if m else section or "", HEADING_CHARS)
            path = [own] if own else []
        return path[-MAX_HEADINGS:]

    def scope_of(self, page) -> tuple[str, str | None, bool]:
        """(scope, region label, in a worked example) of a stored page; a page with no tag is main body (the
        library holds no text for it, so nothing says otherwise; the gate says so in `scope_known`)."""
        tag = self.tags.get(page) if isinstance(page, int) else None
        if tag is None:
            return MAIN, None, False
        return tag["scope"], tag["region"], bool(tag["example"])

    def context_for(self, row: dict) -> dict:
        scope, region, example = self.scope_of(row.get("page"))
        before, after = neighbours(row.get("chunk_text"), row.get("requirement_text"))
        return {
            "heading_path": self.heading_path(row.get("clause"), row.get("section")),
            "page": row.get("page"),
            "scope": scope,
            "region": region,
            "example": example,
            "before": before,
            "after": after,
        }


def neighbours(chunk_text: str | None, sentence: str | None) -> tuple[str, str]:
    """The sentence before and the sentence after `sentence` in its chunk ("" when the chunk does not hold it)."""
    chunk = str(chunk_text or "")
    key = converter_gates.fold(sentence)[:60]
    flat = converter_gates.fold(chunk)
    at = flat.find(key) if key else -1
    if at < 0:
        return "", ""
    pieces = [p.strip() for p in _SENTENCE_END.split(chunk) if p and p.strip()]
    run, found = 0, None
    for n, piece in enumerate(pieces):
        run_end = run + len(converter_gates.fold(piece)) + 1
        if run <= at < run_end:
            found = n
            break
        run = run_end
    if found is None:
        return "", ""
    prev_ = pieces[found - 1] if found > 0 else ""
    next_ = pieces[found + 1] if found + 1 < len(pieces) else ""
    return _clean(prev_, NEIGHBOUR_CHARS), _clean(next_, NEIGHBOUR_CHARS)


def not_main_body(context: dict) -> str | None:
    """The region label (or the scope word) when the rule must not be sent to the model, else None."""
    if context.get("example"):
        return "worked example"
    if context.get("scope") != MAIN:
        return str(context.get("region") or context.get("scope"))
    return None


def with_context(
    rows: list[dict], doc: DocContext
) -> tuple[list[dict], list[tuple[dict, str]]]:
    """(rows to ask, each with its `context`, and (row, region label) for the rules on a page that is not main body)."""
    asked: list[dict] = []
    outside: list[tuple[dict, str]] = []
    for row in rows:
        context = doc.context_for(row)
        label = not_main_body(context)
        if label:
            outside.append((row, label))
        else:
            asked.append({**row, "context": context})
    return asked, outside


def shown(context: dict) -> dict:
    """The part of the context the model sees (no label for what is main body, no empty field)."""
    out = {}
    if context.get("heading_path"):
        out["heading_path"] = context["heading_path"]
    if context.get("page") is not None:
        out["page"] = context["page"]
    for key in ("before", "after"):
        if context.get(key):
            out[key] = context[key]
    return out


#: The shortest condition quote taken seriously (the first answer's quote rule is 8 as well), and the words that
#: tie nothing to nothing when two texts are compared.
MIN_QUOTE_CHARS = 8
_FUNCTION_WORDS = frozenset(
    ["the", "a", "an", "of", "for", "in", "on", "at", "to", "is", "are", "be", "shall", "should", "must", "when", "where", "if", "and", "or", "with", "by", "as", "that", "this"]
)


def _tied(condition: str, quote: str) -> bool:
    """Does the quote say the condition? The condition is inside the quote, or the quote inside the condition, or
    they share at least two content words and at least half of the shorter's (cloud-3 on #1454: any three letters of
    the sentence used to pass as the quote of any condition)."""
    c, q = converter_gates.fold(condition), quote
    if c in q or q in c:
        return True
    cw = {w for w in c.split() if w not in _FUNCTION_WORDS}
    qw = {w for w in q.split() if w not in _FUNCTION_WORDS}
    shared = cw & qw
    return len(shared) >= 2 and len(shared) * 2 >= min(len(cw), len(qw))


def condition_refusal(answer: dict, sentence: str, context: dict | None) -> str | None:
    """The reason a stated condition is not proven (order 305.1), else None. A row asked with context must quote its
    condition: found word for word in the sentence is the only place a condition is kept; found only in the heading
    path or a neighbouring sentence it is named and refused (`condition_outside_sentence`), found nowhere (or
    not quoted at all) it is `condition_not_quoted`. Without context (a file made before v2.3) nothing is asked."""
    condition = (answer.get("condition") or "").strip()
    if context is None or not condition:
        return None
    quote = converter_gates.fold(answer.get("condition_quote"))
    if len(quote) < MIN_QUOTE_CHARS or not _tied(condition, quote):
        return "condition_not_quoted"
    if quote in converter_gates.fold(sentence):
        return None
    elsewhere = " ".join(
        [
            *context.get("heading_path", []),
            context.get("before", ""),
            context.get("after", ""),
        ]
    )
    return (
        "condition_outside_sentence"
        if quote in converter_gates.fold(elsewhere)
        else "condition_not_quoted"
    )
