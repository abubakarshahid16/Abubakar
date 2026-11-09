"""Quote by reference (#1690): the model names line and block ids, CODE writes the exact stored text.

A small local model retypes quotes and paraphrases them, so the code correctly refuses the finding. With this option the
page is shown as numbered lines (L1, L2, ...) and a clause as numbered blocks (C1, C2, ...). The model returns
`doc_quote_ref` = {page, lines} and `clause_quote_ref` = {standard, clause, blocks}; this module builds `doc_quote` /
`clause_quote` as the EXACT stored text of those ids (joined with one space) and hands the finding to the SAME
verification as a typed quote (`ToolBox.record_finding`). A reference replaces typing, never verification.

`RefToolBox` is a `ToolBox` with the option ON. `make_toolbox(ctx, quote_by_reference=False)` returns the plain ToolBox
when it is OFF, so every existing path is unchanged. Nothing here logs or returns text beyond what the tools already do;
a refusal carries a code and the expected shape only.
"""

from __future__ import annotations

import copy
import json
import re

from . import agent_tools
from .agent_tool_schemas import coerce_page

MAX_REF_ITEMS = 12  # lines or blocks in one reference
MAX_QUOTE_CHARS = 600  # one constructed quote, cut at a line boundary
PROMPT_NOTE = (
    "Quote by reference: when you record a finding give the page and the line ids (L..) or block ids (C..) you are "
    "quoting, as doc_quote_ref {page, lines} and clause_quote_ref {standard, clause, blocks}; do not retype text."
)
REF_SHAPE = {
    "doc_quote_ref": {"page": "integer", "lines": "L3-L5 or [L3, L4]"},
    "clause_quote_ref": {
        "standard": "string",
        "clause": "string",
        "blocks": "C2-C3 or [C2, C3]",
    },
}
_IDS = {
    "doc_quote_ref": {"type": "object", "properties": {"page": {"type": "integer", "minimum": 1}, "lines": {
        "anyOf": [{"type": "string"}, {"type": "array", "items": {"type": ["string", "integer"]}}]}}},
    "clause_quote_ref": {"type": "object", "properties": {"standard": {"type": "string"}, "clause": {"type": "string"}, "blocks": {
        "anyOf": [{"type": "string"}, {"type": "array", "items": {"type": ["string", "integer"]}}]}}},
}  # fmt: skip
_SENTENCE_END = re.compile(r"(?<=[.;:])\s+(?=[A-Z0-9(])")
_TOKEN = re.compile(
    r"^\s*[A-Za-z]?\s*(\d{1,6})\s*(?:[-\u2013\u2014]\s*[A-Za-z]?\s*(\d{1,6}))?\s*$"
)


def numbered_lines(text: str) -> list[tuple[str, str]]:
    """[(L1, line), ...] over the NON-BLANK lines of a page, stripped, in stored order; ids are 1-based and stable."""
    lines = [ln.strip() for ln in (text or "").split("\n")]
    return [(f"L{n}", ln) for n, ln in enumerate([ln for ln in lines if ln], 1)]


def numbered_blocks(text: str) -> list[tuple[str, str]]:
    """[(C1, block), ...]: a clause's text (lines joined by one space) split into sentence blocks, exact slices in order."""
    joined = " ".join(ln.strip() for ln in (text or "").split("\n") if ln.strip())
    return [
        (f"C{n}", b)
        for n, b in enumerate([b for b in _SENTENCE_END.split(joined) if b], 1)
    ]


def parse_ids(value: object) -> tuple[list[int] | None, str | None]:
    """'L3', 3, '3-5', 'L3-L5', 'L3,L4', ['L3','L4'], [3, 4] -> sorted ids (a range expands, at most MAX_REF_ITEMS)."""
    if isinstance(value, bool) or value is None:
        return None, "ids_unreadable"
    if isinstance(value, str):
        value = re.sub(r"\s*([-\u2013\u2014])\s*", r"\1", value)
    parts = (
        value
        if isinstance(value, (list, tuple))
        else re.split(r"[,;\s]+", str(value))
        if not isinstance(value, int)
        else [value]
    )
    ids: set[int] = set()
    for part in parts:
        found = _TOKEN.match(str(part))
        if not found:
            return None, "ids_unreadable"
        low = int(found.group(1))
        high = int(found.group(2) or low)
        if high < low or high - low + 1 > MAX_REF_ITEMS:
            return None, "range_too_long"
        ids.update(range(low, high + 1))
        if len(ids) > MAX_REF_ITEMS:
            return None, "range_too_long"
    if not ids:
        return None, "ids_unreadable"
    ordered = sorted(ids)
    if ordered != list(range(ordered[0], ordered[-1] + 1)):
        return (
            None,
            "ids_not_contiguous",
        )  # a quote is one unbroken stretch of the stored text
    return ordered, None


def build_quote(
    pairs: list[tuple[str, str]], ids: list[int], prefix: str
) -> tuple[str | None, str | None]:
    """The exact stored text of the ids, joined by one space and cut at a line boundary to MAX_QUOTE_CHARS."""
    by_id = dict(pairs)
    try:
        parts = [by_id[f"{prefix}{n}"] for n in ids]
    except KeyError:
        return None, "line_not_found" if prefix == "L" else "block_not_found"
    while len(" ".join(parts)) > MAX_QUOTE_CHARS and len(parts) > 1:
        parts.pop()
    text = " ".join(parts)
    return (
        (None, "quote_line_too_long") if len(text) > MAX_QUOTE_CHARS else (text, None)
    )


def ref_tool_specs() -> list[dict]:
    """TOOL_SPECS with the two reference fields on record_finding (the typed quotes stay optional)."""
    specs = copy.deepcopy(agent_tools.TOOL_SPECS)
    for spec in specs:
        if spec["name"] == "record_finding":
            props = spec["input_schema"]["properties"]["finding"]["properties"]
            props.update(copy.deepcopy(_IDS))
            spec["description"] += (
                " Quote by reference: give doc_quote_ref and clause_quote_ref (ids), not typed text."
            )
    return specs


class RefToolBox(agent_tools.ToolBox):
    """A ToolBox with quote-by-reference ON."""

    quote_by_reference = True
    prompt_note = PROMPT_NOTE

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.TOOL_SPECS = ref_tool_specs()
        self._opened: set[tuple[str, int]] = set()
        self._built: dict[str, dict] = {}

    # ---- numbered output

    def open_page(self, doc: object = None, page: object = None) -> dict:
        out = super().open_page(doc, page)
        if not out["ok"]:
            return out
        result = out["result"]
        pairs = numbered_lines(self._page(result["doc"], result["page"]) or "")
        shown, size = [], 0
        for key, line in pairs:
            size += len(line) + len(key) + 3
            if size > agent_tools.MAX_PAGE_CHARS:
                break
            shown.append(f"{key}: {line}")
        result.update(
            text="\n".join(shown), lines=len(pairs), truncated=len(shown) < len(pairs)
        )
        self._opened.add((result["doc"], result["page"]))
        return out

    def get_clause(self, standard: object = None, clause: object = None) -> dict:
        out = super().get_clause(standard, clause)
        if not out["ok"]:
            return out
        body, _doc, _why = self._clause_text(standard, str(clause))
        pairs = numbered_blocks(body or "")
        shown, size = [], 0
        for key, block in pairs:
            size += len(block) + len(key) + 3
            if size > agent_tools.MAX_CLAUSE_CHARS:
                break
            shown.append(f"{key}: {block}")
        out["result"].update(
            text="\n".join(shown), blocks=len(pairs), truncated=len(shown) < len(pairs)
        )
        return out

    # ---- references -> exact text, then the same verification

    def _refuse_ref(self, code: str) -> dict:
        return agent_tools._res(
            False,
            {
                "verdict": "refused",
                "accepted": False,
                "reason": code,
                "ref_expect": REF_SHAPE,
            },
        )

    def _doc_ref(self, finding: dict) -> tuple[dict | None, str | None]:
        ref = finding["doc_quote_ref"]
        if not isinstance(ref, dict):
            return None, "doc_quote_ref_not_an_object"
        page, bad = coerce_page(ref.get("page"))
        doc = finding.get("doc") or self.ctx.document_id
        if page is None:
            return None, bad
        if (doc, page) not in self._opened:
            return None, "page_not_opened"
        ids, bad = parse_ids(ref.get("lines"))
        if ids is None:
            return None, bad
        quote, bad = build_quote(numbered_lines(self._page(doc, page) or ""), ids, "L")
        return (
            ({"doc_quote": quote, "page": page, "doc": doc}, None)
            if quote
            else (None, bad)
        )

    def _clause_ref(self, finding: dict) -> tuple[dict | None, str | None]:
        ref = finding["clause_quote_ref"]
        if not isinstance(ref, dict):
            return None, "clause_quote_ref_not_an_object"
        standard, clause = ref.get("standard"), ref.get("clause")
        if isinstance(clause, (int, float)) and not isinstance(clause, bool):
            clause = str(clause)
        ids, bad = parse_ids(ref.get("blocks"))
        if ids is None:
            return None, bad
        body, _doc, _why = self._clause_text(standard, clause)
        if body is None:
            return None, "clause_not_found"
        quote, bad = build_quote(numbered_blocks(body), ids, "C")
        return (
            ({"clause_quote": quote, "standard": standard, "clause": clause}, None)
            if quote
            else (None, bad)
        )

    def record_finding(self, finding: object = None) -> dict:
        if isinstance(finding, str):
            try:
                finding = json.loads(finding)
            except ValueError:
                finding = None
        if not isinstance(finding, dict):
            return super().record_finding(finding)
        f = dict(finding)
        for ref_key, build in (
            ("doc_quote_ref", self._doc_ref),
            ("clause_quote_ref", self._clause_ref),
        ):
            if f.get(ref_key) in (None, "", {}, []):
                f.pop(ref_key, None)
                continue
            built, bad = build(f)
            f.pop(ref_key)
            if built is None:
                return self._refuse_ref(bad or "ref_unreadable")
            f.update(
                built
            )  # the reference wins: typed text for the same quote is replaced, never mixed
        out = super().record_finding(f)
        if out["ok"]:
            self._built[str(f.get("item") or self.ctx.current_item)] = f
        return out

    def built_finding(self, finding: dict) -> dict:
        """The finding as verified: references replaced by the exact text (the loop stores this one)."""
        item = str(finding.get("item") or self.ctx.current_item)
        keep = ("doc_quote", "clause_quote", "page", "standard", "clause")
        built = {k: v for k, v in self._built.get(item, {}).items() if k in keep}
        return {k: v for k, v in {**finding, **built}.items() if not k.endswith("_ref")}


def make_toolbox(
    ctx, *, quote_by_reference: bool = False, **readers
) -> agent_tools.ToolBox:
    """The plain ToolBox when the option is OFF (default), the RefToolBox when ON."""
    return (RefToolBox if quote_by_reference else agent_tools.ToolBox)(ctx, **readers)


__all__ = [
    "RefToolBox",
    "make_toolbox",
    "numbered_blocks",
    "numbered_lines",
    "parse_ids",
]
