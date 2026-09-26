"""The vision reader (#193 plan B4, item 1): a datasheet page read from its
IMAGE by the reasoning model, kept only where CODE can prove it.

WHAT IT IS FOR. The rule readers and the geometry reader read the page's
text layer by position. They miss fields whose layout they cannot
reassemble - a grid whose cells wrap, a label printed above its value, a
group heading shared by several rows. A model looking at the rendered page
sees those. It also invents, re-types and guesses, so nothing it says is
stored on its word.

THE MODEL PROPOSES; THE PAGE DECIDES. The model (Sonnet class, through
`reasoning_provider` and so through `reader_transport` - the one approved
lane) is sent one rendered page and asked for label / value / unit per
filled field. A proposal is KEPT only when every check below passes, and a
proposal that fails any of them is DROPPED - counted by reason, never
stored, never shown as a value:

  1. LABEL ON THE PAGE. Every part of the label ("GROUP - SUBLABEL" for a
     field inside a group or table) is on the page's text layer verbatim
     (`model_evidence.quote_verified`, the owner's closed normalisation
     list and nothing else - not case, not digits).
  2. VALUE ON THE PAGE, BESIDE ITS LABEL. Either the value is on the text
     layer verbatim AND one of its occurrences sits beside an occurrence of
     a label part (same line to its right, or directly below it), OR the
     geometry reader already read exactly that value in a cell under that
     label (`geometry_reader`, position and quote).
  3. UNIT ON THE PAGE. A unit, when the model gives one, is on the text
     layer verbatim and on the value's line, the label's line, or above the
     value in its column. An unprovable unit drops the whole reading: a
     number with the wrong unit is a wrong value.
  4. A VALUE, NOT A BLANK. A blank cannot be proved from a text layer (it is
     the absence of text), so the vision reader never records one.

Nothing here writes the database; `datasheets.extract_facts` writes what is
kept, behind `settings.geometry_reader_enabled` (OFF by default), after the
rule readers and the geometry reader, and a rule-reader or geometry fact
for the same page and label always wins.

PAGES. Each page gets a `page_kind` from the model - its word, unverified,
used only to say WHY a page produced no field ("cover", "revision record").
"""
from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field
from typing import Any

from .model_evidence import _collapse, quote_verified

#: The claude_spend step every vision call is charged to.
VISION_STEP = "b4-vision"
PROMPT_VERSION = "b4-vision-v3"
#: `submittal_facts.extraction_method` of a kept vision reading.
METHOD = "vision"
#: Modest resolution: the long edge in pixels, and a dpi ceiling. A datasheet
#: page at ~130 dpi is legible to the model and costs ~2,000 input tokens.
MAX_EDGE_PX = 1500
MAX_DPI = 130
#: Output budget for one page; a dense page lists ~150 fields.
MAX_OUTPUT_TOKENS = 8000
TIMEOUT_S = 300.0
#: Transcription, not reasoning: low effort (measured 2026-09-25: default
#: effort spent ~4x the answer's length in thinking on one page).
EFFORT = "low"
#: What the model may call a page. Its word, used only in a ledger reason.
PAGE_KINDS = ("datasheet", "cover", "revision_record", "contents", "notes",
              "drawing", "table", "other")

# Drop reasons - a closed list, so the counts can be read and compared.
EMPTY = "empty label or value"
LABEL_NOT_ON_PAGE = "label not on the page"
VALUE_NOT_ON_PAGE = "value not on the page"
VALUE_NOT_BESIDE_LABEL = "value not beside its label"
UNIT_NOT_PROVEN = "unit not on the page beside the value"
BLANK = "blank (never recorded from an image)"

_BLANKISH = re.compile(r"^[\s_*\-.–—/]*$")

_SCHEMA = {
    "type": "object", "required": ["page_kind", "fields"],
    "properties": {
        "page_kind": {"type": "string", "enum": list(PAGE_KINDS)},
        "fields": {"type": "array", "items": {
            "type": "object", "required": ["label", "value"],
            "properties": {"label": {"type": "string"}, "value": {"type": "string"},
                           "unit": {"type": ["string", "null"]}}}},
    },
}

SYSTEM = (
    "You read ONE page of an engineering datasheet from its image and list its FILLED "
    "fields. Rules:\n"
    "1. Copy every label, value and unit EXACTLY as printed - same characters, same case, "
    "same punctuation. Never paraphrase, translate, expand an abbreviation, convert a unit "
    "or compute anything.\n"
    "2. List only fields that carry a printed value. Skip a field whose value is empty, "
    "an asterisk, underscores, a dash, or left for the vendor/contractor to fill.\n"
    "3. Skip page furniture: the title block, revision history, document and sheet "
    "numbers, page numbers, signatures, names, dates, logos, row-number rulers.\n"
    "4. When a field sits inside a group or a table (a group heading, or a row heading "
    "and a column heading), write the label as 'GROUP - SUBLABEL' (row heading first, "
    "then column heading), each part copied exactly from the page.\n"
    "5. `unit`: the unit printed beside the value or in the field's unit column, copied "
    "exactly; null when none is printed. Do not repeat the unit inside `value`.\n"
    "5a. A value printed in two unit systems ('60.0 (140)' with units '°C (°F)'): give "
    "only the FIRST value and the FIRST unit ('60.0', '°C').\n"
    "5b. A condition printed after the value ('0.85 @ 150 °F'): give only the value "
    "('0.85'); the condition is not part of it.\n"
    "5c. Several values in one row under column headings (MIN / MAX, NORMAL / RATED): one "
    "field per value, labelled 'ROW LABEL - COLUMN HEADING'.\n"
    "6. Checkboxes and option lists: report only the option that is visibly marked, and "
    "only when the mark is unambiguous. If unsure, omit the field.\n"
    "7. Never guess. A field you cannot read with certainty is omitted.\n"
    "Also give `page_kind`: datasheet, cover, revision_record, contents, notes, drawing, "
    "table or other.")


@dataclass
class PageReading:
    """What the vision reader did with one page."""

    page: int
    asked: bool = False
    page_kind: str | None = None
    proposed: int = 0
    kept: list[dict[str, Any]] = field(default_factory=list)
    dropped: dict[str, int] = field(default_factory=dict)
    refused: str | None = None
    model_tag: str | None = None

    def drop(self, reason: str) -> None:
        self.dropped[reason] = self.dropped.get(reason, 0) + 1


# --------------------------------------------------------------- rendering

def render(page: Any):
    """The page as a PNG `PageImage` at modest resolution (<= MAX_DPI, long
    edge <= MAX_EDGE_PX)."""
    import pymupdf

    from .reasoning_provider import PageImage

    zoom = min(MAX_DPI / 72.0, MAX_EDGE_PX / max(page.rect.width, page.rect.height))
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
    return PageImage(media_type="image/png",
                     data=base64.b64encode(pix.tobytes("png")).decode("ascii"),
                     width=pix.width, height=pix.height)


def packet_for(image, page_no: int):
    from .reasoning_provider import Packet

    return Packet(prompt=f"Page {page_no}. List the filled fields as JSON.",
                  num_ctx=32768, num_predict=MAX_OUTPUT_TOKENS, json_schema=_SCHEMA,
                  system=SYSTEM, step=VISION_STEP, prompt_version=PROMPT_VERSION,
                  images=(image,), timeout_s=TIMEOUT_S, effort=EFFORT)


def parse(text: str) -> tuple[str | None, list[dict]]:
    body = (text or "").strip()
    fence = re.match(r"^```[a-zA-Z]*\s*\n(.*)\n```$", body, re.DOTALL)
    if fence:
        body = fence.group(1)
    try:
        value = json.loads(body)
    except json.JSONDecodeError:
        return None, []
    if not isinstance(value, dict):
        return None, []
    kind = value.get("page_kind") if value.get("page_kind") in PAGE_KINDS else None
    fields = value.get("fields")
    return kind, [f for f in fields if isinstance(f, dict)] if isinstance(fields, list) else []


# ------------------------------------------------------ the page's evidence

Box = tuple[float, float, float, float]


@dataclass
class PageText:
    """The text layer of one page: its text and its words with boxes."""

    text: str
    words: list[tuple[Box, str]]

    @classmethod
    def of(cls, page: Any) -> PageText:
        words = [((w[0], w[1], w[2], w[3]), _collapse(w[4]))
                 for w in page.get_text("words")]
        return cls(text=page.get_text(), words=[w for w in words if w[1]])


def _union(boxes: list[Box]) -> Box:
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def occurrences(needle: str, words: list[tuple[Box, str]], limit: int = 50) -> list[Box]:
    """Boxes where `needle` is printed as a run of consecutive words: the first
    token may end a word, the last may start one ("85" in "<85"), every middle
    token is a whole word. Exact characters after the closed normalisation."""
    tokens = _collapse(needle).split(" ")
    if not tokens or not tokens[0]:
        return []
    out: list[Box] = []
    n = len(tokens)
    for i in range(len(words) - n + 1):
        run = words[i:i + n]
        texts = [w[1] for w in run]
        if n == 1:
            ok = _token_is(tokens[0], texts[0])
        else:
            ok = (_ends_with(texts[0], tokens[0]) and _starts_with(texts[-1], tokens[-1])
                  and all(t == w for t, w in zip(tokens[1:-1], texts[1:-1])))
        if ok:
            out.append(_union([w[0] for w in run]))
            if len(out) >= limit:
                break
    return out


#: What may surround a printed token inside one word of the text layer: a
#: drawn blank ("__-03__"), a colon, brackets, a comparison sign ("<85").
#: Never a letter or a digit - "2" is not found inside "250".
_WRAP = "_*:()[]<>=~≤≥"


def _token_is(token: str, word: str) -> bool:
    return word == token or word.strip(_WRAP) == token or (
        token in word and word.replace(token, "", 1).strip(_WRAP) == "")


def _ends_with(word: str, token: str) -> bool:
    return word == token or (word.endswith(token) and word[: -len(token)].strip(_WRAP) == "")


def _starts_with(word: str, token: str) -> bool:
    return word == token or (word.startswith(token) and word[len(token):].strip(_WRAP + ".,;") == "")


def _height(b: Box) -> float:
    return max(1.0, b[3] - b[1])


def same_line(a: Box, b: Box) -> bool:
    """`b` shares a line with `a`: vertical overlap of at least half the
    shorter box."""
    overlap = min(a[3], b[3]) - max(a[1], b[1])
    return overlap >= 0.5 * min(_height(a), _height(b))


def beside(label: Box, value: Box, page_width: float) -> bool:
    """The value sits where a form prints a label's answer: on the label's
    line to its right (within half the page), or directly below it (within
    two and a half lines, overlapping it horizontally)."""
    if same_line(label, value):
        return value[0] >= label[0] and value[0] - label[2] <= 0.5 * page_width
    line = _height(label)
    below = value[1] >= label[1] + 0.5 * line and value[1] - label[3] <= 2.5 * line
    overlaps = min(label[2] + 2 * line, value[2]) - max(label[0] - 2 * line, value[0]) > 0
    return below and overlaps


def unit_belongs(value: Box, unit: Box) -> bool:
    """`unit` is the value's: in its column above it (a unit header), on its
    line to its LEFT (the form's unit column), or immediately after it. A unit
    further right on the line belongs to something else - "0.85 @ 150 OF"
    prints a temperature's unit, not the gravity's."""
    if above_in_column(value, unit):
        return True
    if unit[2] <= value[0] + 1:
        # Left of the value, in the value's row band: a form's unit column,
        # often printed stacked ("m3/h" over "(USGPM)"), so the band is the
        # value's line widened by most of a line each way.
        h = _height(value)
        centre = (unit[1] + unit[3]) / 2
        return value[1] - 0.9 * h <= centre <= value[3] + 0.9 * h
    if not same_line(value, unit):
        return False
    return 0 <= unit[0] - value[2] <= 2 * _height(value)


def above_in_column(value: Box, unit: Box) -> bool:
    """`unit` is printed above `value` in the same column (a unit header)."""
    return unit[3] <= value[1] + 1 and min(unit[2], value[2]) - max(unit[0], value[0]) > 0


#: The degree sign as these sheets' text layers print it: a capital or
#: lower-case O, or the masculine ordinal (`datasheets.normalise_degree_glyph`
#: reads `121OC` as 121 °C). A model reading the IMAGE sees "°C"; the text
#: layer says "OC". Only this glyph - nothing else about a unit is relaxed.
_DEGREE_SPELLINGS = ("O", "o", "º")


def unit_spellings(unit: str) -> list[str]:
    """`unit`, then the text-layer spellings of its degree sign, if it has one."""
    out = [unit]
    if "°" in unit:
        out += [unit.replace("°", glyph) for glyph in _DEGREE_SPELLINGS]
    return out


def label_parts(label: str) -> list[str]:
    return [p.strip() for p in re.split(r"\s+-\s+", label or "") if p.strip()]


def part_boxes(part: str, text: PageText) -> list[Box]:
    """Where a label part is printed: verbatim on one run of words, or
    WRAPPED - its head on one line and the rest directly below it (a label
    column too narrow for the words). [] when neither is on the page."""
    if quote_verified(part, text.text):
        return occurrences(part, text.words)
    tokens = _collapse(part).split(" ")
    out: list[Box] = []
    for k in range(1, len(tokens)):
        head, tail = " ".join(tokens[:k]), " ".join(tokens[k:])
        if not (quote_verified(head, text.text) and quote_verified(tail, text.text)):
            continue
        for hb in occurrences(head, text.words):
            h = _height(hb)
            for tb in occurrences(tail, text.words):
                below = hb[3] - 1 <= tb[1] <= hb[3] + 1.2 * h
                aligned = abs(tb[0] - hb[0]) <= 2 * h or min(hb[2], tb[2]) - max(hb[0], tb[0]) > 0
                if below and aligned:
                    out.append(_union([hb, tb]))
    return out


def _fold(text: str | None) -> str:
    return " ".join(_collapse(text).split()).casefold()


def _geometry_proof(label: str, value: str, geometry_rows: list[dict]) -> dict | None:
    """A geometry reading of exactly this value under this label (its last
    part, or the whole label), or None."""
    names = {_fold(label), _fold(label_parts(label)[-1] if label_parts(label) else label)}
    for row in geometry_rows or ():
        if row.get("is_blank"):
            continue
        if _fold(row.get("label")) in names and _fold(value) in (
                _fold(row.get("value_text")), _fold(row.get("value"))):
            return row
    return None


_LIST_MARK = re.compile(r"^\d{1,2}[.)]\s+(?=[A-Za-z])")
_PAIRED = re.compile(r"^(.+?)\s*\(([^()]*)\)$")


def reduce(value: str, unit: str) -> tuple[str, str, bool]:
    """The model's value and unit cut down to the FIELD's value, by fixed
    rules - never by the model. What remains is still checked against the
    page like any other proposal.

      - a condition after the value is not the value: "0.85 @ 150" -> "0.85";
      - a value printed in two unit systems keeps the first: "12.0 (53)" with
        "m3/h (USGPM)" -> "12.0", "m3/h";
      - a unit printed in brackets is the unit: "(dBA)" -> "dBA";
      - a list-item number before free text is dropped: "1. PUMPS ..." -> "PUMPS ...".

    The third item says a condition was cut: the unit the model gave may then
    be the CONDITION's ("0.85 @ 150 °F"), and `verify` drops it rather than
    the reading when the page does not put it beside the value.
    """
    condition_cut = False
    # A list-item number opening a free-text value ("1. PUMPS SHALL ...") is
    # the list's marker, not the value. Only before a LETTER - "1. 5" is
    # never touched.
    value = _LIST_MARK.sub("", value, count=1)
    if "@" in value:
        value = value.split("@", 1)[0].strip()
        condition_cut = True
    m = _PAIRED.match(value)
    if m and re.search(r"\d", m.group(1)) and re.search(r"\d", m.group(2)):
        value = m.group(1).strip()
    u = _PAIRED.match(unit)
    if u and u.group(1).strip():
        unit = u.group(1).strip()
    elif unit.startswith("(") and unit.endswith(")"):
        unit = unit[1:-1].strip()
    return value, unit, condition_cut


def verify(proposal: dict, text: PageText, page_width: float,
           geometry_rows: list[dict] | None = None) -> tuple[dict | None, str | None]:
    """All four checks on ONE proposal. Returns (kept reading, None) or
    (None, drop reason)."""
    label = _collapse(proposal.get("label") if isinstance(proposal.get("label"), str) else "")
    value = _collapse(proposal.get("value") if isinstance(proposal.get("value"), str) else "")
    unit_raw = proposal.get("unit")
    unit = _collapse(unit_raw) if isinstance(unit_raw, str) else ""
    value, unit, condition_cut = reduce(value, unit)
    if not label or not value:
        return None, EMPTY
    if _BLANKISH.match(value):
        return None, BLANK
    parts = label_parts(label)
    boxes = {part: part_boxes(part, text) for part in parts}
    if not parts or not all(boxes.values()):
        return None, LABEL_NOT_ON_PAGE
    proof = None
    value_box = label_box = None
    if quote_verified(value, text.text):
        value_boxes = occurrences(value, text.words)
        for part in parts:
            for lb in boxes[part]:
                vb = next((v for v in value_boxes if beside(lb, v, page_width)
                           and not (v == lb)), None)
                if vb is not None:
                    proof, value_box, label_box = "text layer, beside its label", vb, lb
                    break
            if proof:
                break
    if proof is None:
        row = _geometry_proof(label, value, geometry_rows or [])
        if row is not None:
            proof = "geometry cell"
            value_box, label_box = row.get("bbox"), row.get("label_bbox")
    if proof is None:
        return None, (VALUE_NOT_BESIDE_LABEL if quote_verified(value, text.text)
                      else VALUE_NOT_ON_PAGE)
    if unit:
        vb = tuple(value_box) if value_box else None
        lb = tuple(label_box) if label_box else None
        ok = False
        for spelling in unit_spellings(unit):
            if not quote_verified(spelling, text.text):
                continue
            for ub in occurrences(spelling, text.words):
                if (vb and unit_belongs(vb, ub)) or (
                        lb and same_line(lb, ub) and not (vb and same_line(lb, vb))):
                    ok = True
                    break
            if ok:
                break
        if not ok and not condition_cut:
            return None, UNIT_NOT_PROVEN
        if not ok:
            unit = ""
    return {"label": label, "value": value, "unit": unit or None, "proof": proof,
            "value_bbox": list(value_box) if value_box else None,
            "label_bbox": list(label_box) if label_box else None}, None


# ------------------------------------------------------------------ one page

def read_page(page: Any, page_no: int, provider, *,
              geometry_rows: list[dict] | None = None) -> PageReading:
    """Ask `provider` for `page`'s filled fields and keep what the page proves.

    A provider refusal (budget, egress, engine) is recorded on the reading,
    never raised: the rule and geometry readers' facts stand without it."""
    from .reasoning_provider import ProviderRefused

    reading = PageReading(page=page_no)
    try:
        response = provider.reason(packet_for(render(page), page_no))
    except (ProviderRefused, RuntimeError) as exc:
        # BudgetExceeded is a RuntimeError; the type and message only.
        reading.refused = f"{type(exc).__name__}: {exc}"
        return reading
    reading.asked = True
    reading.model_tag = response.model_tag
    if response.schema_errors or response.truncated:
        reading.refused = ("truncated answer" if response.truncated
                           else "answer did not satisfy the schema")
        return reading
    reading.page_kind, proposals = parse(response.text)
    reading.proposed = len(proposals)
    text = PageText.of(page)
    seen: set[tuple[str, str]] = set()
    for proposal in proposals:
        kept, reason = verify(proposal, text, float(page.rect.width), geometry_rows)
        if kept is None:
            reading.drop(reason or "unverified")
            continue
        key = (_fold(kept["label"]), _fold(kept["value"]))
        if key in seen:
            reading.drop("duplicate")
            continue
        seen.add(key)
        kept["model_tag"] = response.model_tag
        reading.kept.append(kept)
    return reading


def provider():
    """The reasoning provider for page images - Claude only. None (and the
    reason) when Claude is not available: the local engine reads no images,
    and a fallback here would be a silent no-op that looks like a reading."""
    from .reasoning_provider import claude_available, get_provider

    ok, why = claude_available()
    if not ok:
        return None, why
    return get_provider("reasoning", step=VISION_STEP), None
