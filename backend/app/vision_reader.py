"""Issue #180: route each page, and read the pages the rule reader could not
with a LOCAL vision-language model - checked against the page before anything
it says is kept.

THREE PARTS, IN THE ORDER THEY RUN

  1. ROUTING (`route_document`). Every page gets one route and the reason for
     it, recorded whether or not the vision model is enabled:

       native_text   the rule reader read what this page prints
       needs_ocr     no native text; recognition (`ocr.py`) is the reader
       needs_layout  text exists (native or recognised) but the rule reader
                     left its values unread - a grid, a column header above
                     the values, a layout the pairing rules do not model
       needs_visual  little or no text at all; what the page means is drawn

     Only needs_layout and needs_visual are ever sent to the model. A page the
     rule reader read is `native_text` and can never reach it - the property
     #180's first acceptance test names.

  2. THE MODEL CALL (`read_page`). Through `reasoning_provider.OllamaProvider`,
     so through `model_transport` - loopback-validated, the one socket allowed
     to carry document content. This module opens nothing itself. The image
     sent is the unread REGION, cropped before it is rendered: prompt tokens
     scale with pixels (measured: 251 / 511 / 979 tokens for one full A4 page
     at 50 / 72 / 100 dpi on qwen3.5:4b).

  3. VALIDATION (`locate_on_page`). THE MODEL IS A PROPOSER, NEVER A SOURCE.
     A proposed value is kept as a fact only when the page's OWN TEXT holds
     the value, in the row of the label it was proposed for, under the column
     heading it names (or, with no heading, as the nearest value to the right
     of the label). That location is the fact's region. Anything that fails is
     NEEDS_ENGINEER_REVIEW when the value is at least printed on the page, and
     DROPPED when it is not - a number the page does not print is not put in
     front of an engineer as something to confirm.

     A recognised (OCR) page has text but no stored boxes, so no region can be
     located there: every value read from one is NEEDS_ENGINEER_REVIEW, with
     the reason stated, never a fact.

WHAT THIS IS NOT. It does not decide what counts as a fact (`datasheets` does,
with the same gates as every other tier), it does not store anything, and it
does not know the database exists.
"""
from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field

from . import extraction_schema
from .config import settings
from .reasoning_provider import OllamaProvider, Packet, ProviderRefused, ReasoningProvider

ROUTE_NATIVE_TEXT = "native_text"
ROUTE_NEEDS_OCR = "needs_ocr"
ROUTE_NEEDS_LAYOUT = "needs_layout"
ROUTE_NEEDS_VISUAL = "needs_visual"
ROUTES = (ROUTE_NATIVE_TEXT, ROUTE_NEEDS_OCR, ROUTE_NEEDS_LAYOUT, ROUTE_NEEDS_VISUAL)
#: The ONLY routes a model call may be made for.
VISION_ROUTES = (ROUTE_NEEDS_LAYOUT, ROUTE_NEEDS_VISUAL)

#: Below this many characters of native text a page is an image page.
MIN_NATIVE_CHARS = 20
#: A page is needs_layout when at least this many of its value-bearing words
#: were read into nothing...
LAYOUT_MIN_UNREAD = 4
#: ...and they are at least this share of all its value-bearing words. Both,
#: so a long, well-read page with three stray numbers is not sent, and a small
#: page whose only four numbers were missed is.
LAYOUT_MIN_UNREAD_SHARE = 0.5
#: A native page with fewer words than this and at least VISUAL_MIN_DRAWINGS
#: vector paths (or an image over half its area) is a drawing, not a form.
VISUAL_MAX_WORDS = 40
VISUAL_MIN_DRAWINGS = 150
VISUAL_MIN_IMAGE_SHARE = 0.5
#: Kept above the unread region so the column headings are in the image.
REGION_HEADER_MARGIN = 40.0
REGION_FOOT_MARGIN = 6.0

#: Validation outcomes on a proposed row.
VALIDATED = "validated"
REVIEW = "needs_engineer_review"
DROPPED = "dropped"

#: Stripped from a word's EDGES only. The underscore is here because a form
#: prints its answer INSIDE a drawn slot - `____OH2____` is one printed word -
#: and without it every such value read as "not printed" (measured, #180).
_EDGE_PUNCT = "()[]{},;:*_"
_ROW_NUMBER = re.compile(r"^\d{1,3}$")
_DATE = re.compile(r"^(?:\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2}|\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})$")
_DIGIT = re.compile(r"\d")


def norm_token(text: str) -> str:
    """One word as compared: edge punctuation off, case folded."""
    return (text or "").strip().strip(_EDGE_PUNCT).casefold()


def tokens(text: str) -> list[str]:
    """Words of a label or value, split on space and on parentheses, so a
    printed `24.8(109)` is the two tokens `24.8` and `109`."""
    out = []
    for raw in re.split(r"[\s()\[\]]+", text or ""):
        token = norm_token(raw)
        if token:
            out.append(token)
    return out


def is_value_word(token: str) -> bool:
    """A word that carries a value the rule reader should have read.

    Contains a digit, and is not a bare one-to-three digit integer (row
    numbers, the revision column, "SHEET 3 OF 11") and not a date. Words with
    no digit are not counted at all: a categorical answer left unread is not
    visible to this signal, which is a stated limit of it, not a claim.
    """
    return bool(_DIGIT.search(token)) and not _ROW_NUMBER.match(token) \
        and not _DATE.match(token)


@dataclass(frozen=True)
class PageRoute:
    route: str
    reason: str
    #: PDF user-space (x0, y0, x1, y1) of what the model should look at; None
    #: for routes that are never sent.
    region: tuple[float, float, float, float] | None = None
    value_words: int | None = None
    unread_value_words: int | None = None
    #: False for an image page: its values are checked against RECOGNISED
    #: text, which has no stored boxes, so nothing read there is a fact.
    native: bool = True

    def __post_init__(self) -> None:
        if self.route not in ROUTES:
            raise ValueError(f"unknown route {self.route!r}")
        if not self.reason:
            raise ValueError("a route without a reason is not recorded")


def _furniture_keys(doc) -> set[tuple[str, int, int]]:
    """(word, x, y) that recur at the same place on three or more pages.

    The title block and the revision column print the same value-bearing
    words on every sheet; counting them as "unread" would route every page
    of a multi-page form. Position is rounded to 10 pt, which absorbs
    rendering jitter and nothing else.
    """
    counts: dict[tuple[str, int, int], int] = {}
    for page in doc:
        seen = set()
        for w in page.get_text("words"):
            key = (norm_token(w[4]), int(w[0] // 10), int(w[1] // 10))
            if key not in seen:
                seen.add(key)
                counts[key] = counts.get(key, 0) + 1
    if doc.page_count < 3:
        return set()
    return {key for key, n in counts.items() if n >= 3}


def _image_share(page) -> float:
    area = abs(page.rect) or 1.0
    covered = 0.0
    for info in page.get_image_info():
        x0, y0, x1, y1 = info.get("bbox", (0, 0, 0, 0))
        covered += max(0.0, x1 - x0) * max(0.0, y1 - y0)
    return min(1.0, covered / area)


def route_page(page, *, read_pairs: list[tuple[str, str]],
               ocr_text: str | None, ocr_ran: bool, ocr_pairs: bool,
               furniture: set | frozenset = frozenset()) -> PageRoute:
    """One page's route and the reason, in the page's own numbers.

    `read_pairs` are the rule reader's pairs that survived its own fact gates
    on this page - what it READ. `ocr_text` / `ocr_ran` / `ocr_pairs` say
    whether recognition ran, what it produced, and whether the OCR tier made
    pairs of it.
    """
    full = (0.0, 0.0, float(page.rect.width), float(page.rect.height))
    native = page.get_text("text") or ""
    if len(native.strip()) < MIN_NATIVE_CHARS:
        if not ocr_ran:
            return PageRoute(ROUTE_NEEDS_OCR,
                             "no native text on this page; recognition has not run on it",
                             native=False)
        if ocr_pairs:
            return PageRoute(ROUTE_NEEDS_OCR,
                             "no native text; read by the OCR tier from recognised text",
                             native=False)
        if (ocr_text or "").strip():
            return PageRoute(
                ROUTE_NEEDS_LAYOUT,
                f"no native text; recognised text has {len(ocr_text.strip())} "
                "characters and no 'LABEL: VALUE' line the OCR tier can pair",
                region=full, native=False)
        return PageRoute(ROUTE_NEEDS_VISUAL,
                         "no native text and recognition found none; whatever this "
                         "page carries is drawn", region=full, native=False)

    words = page.get_text("words")
    drawings = len(page.get_drawings())
    image_share = _image_share(page)
    if len(words) < VISUAL_MAX_WORDS and (drawings >= VISUAL_MIN_DRAWINGS
                                         or image_share >= VISUAL_MIN_IMAGE_SHARE):
        return PageRoute(
            ROUTE_NEEDS_VISUAL,
            f"{len(words)} words against {drawings} vector paths and "
            f"{image_share:.0%} image cover; this page is a drawing, not a form",
            region=full)

    read: dict[str, int] = {}
    for label, value in read_pairs:
        for token in tokens(label) + tokens(value):
            read[token] = read.get(token, 0) + 1
    value_words = []
    for w in words:
        token = norm_token(w[4])
        if (token, int(w[0] // 10), int(w[1] // 10)) in furniture:
            continue
        for part in tokens(w[4]):
            if is_value_word(part):
                value_words.append((part, w))
    unread = []
    for token, w in value_words:
        if read.get(token, 0) > 0:
            read[token] -= 1
        else:
            unread.append(w)
    total = len(value_words)
    if total and len(unread) >= LAYOUT_MIN_UNREAD \
            and len(unread) / total >= LAYOUT_MIN_UNREAD_SHARE:
        y0 = max(0.0, min(w[1] for w in unread) - REGION_HEADER_MARGIN)
        y1 = min(full[3], max(w[3] for w in unread) + REGION_FOOT_MARGIN)
        return PageRoute(
            ROUTE_NEEDS_LAYOUT,
            f"{len(unread)} of {total} value-bearing words on this page were not "
            "read into any pair by the rule reader",
            region=(0.0, round(y0, 1), full[2], round(y1, 1)),
            value_words=total, unread_value_words=len(unread))
    return PageRoute(
        ROUTE_NATIVE_TEXT,
        (f"native text; {total - len(unread)} of {total} value-bearing words "
         "read by the rule reader") if total else
        "native text with no value-bearing words",
        value_words=total, unread_value_words=len(unread))


def route_document(stored_path: str, *, read_pairs_by_page: dict[int, list],
                   ocr_by_page: dict[int, tuple[bool, str | None, bool]]) -> dict[int, PageRoute]:
    """Every page in `read_pairs_by_page`, routed. Opens the PDF once."""
    import pymupdf
    out: dict[int, PageRoute] = {}
    with pymupdf.open(stored_path) as doc:
        furniture = _furniture_keys(doc)
        for page_no, pairs in sorted(read_pairs_by_page.items()):
            if not (1 <= page_no <= doc.page_count):
                continue
            ran, text, paired = ocr_by_page.get(page_no, (False, None, False))
            out[page_no] = route_page(doc[page_no - 1], read_pairs=pairs,
                                      ocr_text=text, ocr_ran=ran, ocr_pairs=paired,
                                      furniture=furniture)
    return out


# ---------------------------------------------------------------- the call

PROMPT = """You are reading part of page {page} of an engineering datasheet.
List every field in the image that has a value printed in it.
Return ONLY a JSON array, one element per printed value:
["label", "column", "value", "unit"]
- label: the row's field label exactly as printed (keep typos; no row number).
- column: the column heading the value is printed under (for example Rated, Normal, Maximum, Minimum), or "" if the field has only one value.
- value: exactly as printed, without the unit.
- unit: the unit printed for that value, or "".
Skip empty cells, '*' marks and drawn blank lines. Do not guess, and do not add anything the image does not show."""


_COMPACT_KEYS = {"label", "column", "value", "unit"}


@dataclass
class ProposedRow:
    """One row the model proposed, and what validation made of it."""

    label: str
    column_header: str
    value: str
    unit: str
    outcome: str = DROPPED
    note: str = ""
    bbox: tuple[float, float, float, float] | None = None
    #: The PAGE's own words in the located region when validated; otherwise
    #: the model's reading, composed from its own fields.
    source_text: str = ""


@dataclass
class VisionReading:
    page: int
    route: str
    model_tag: str | None = None
    rows: list[ProposedRow] = field(default_factory=list)
    refusals: list[str] = field(default_factory=list)
    #: Set when the page produced nothing usable at all, with the reason.
    page_refused: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    wall_time_s: float | None = None
    prompt_sha256: str | None = None
    region: tuple[float, float, float, float] | None = None
    dpi: int | None = None


def make_provider() -> ReasoningProvider:
    """The provider the extraction path uses. Tests replace this function."""
    return OllamaProvider(model=settings.vision_model)


def render_region(stored_path: str, page_no: int,
                  region: tuple[float, float, float, float] | None, dpi: int) -> bytes:
    import pymupdf
    with pymupdf.open(stored_path) as doc:
        page = doc[page_no - 1]
        clip = pymupdf.Rect(*region) if region else page.rect
        pix = page.get_pixmap(matrix=pymupdf.Matrix(dpi / 72, dpi / 72), clip=clip)
        return pix.tobytes("png")


def parse_rows(text: str, page_no: int) -> tuple[list[ProposedRow], list[str], str | None]:
    """The model's answer as rows, through `extraction_schema` - never coerced.

    The compact 4-element form is expanded into an ExtractedRow with the page
    the CODE sent (not a model claim) and `is_blank` false (the prompt asks
    for printed values only). Returns (rows, row refusals, page refusal).
    """
    body = (text or "").strip()
    if body.startswith("```"):
        body = body.split("```")[1] if body.count("```") >= 2 else body
        body = body[4:].strip() if body.lower().startswith("json") else body.strip()
    if not body:
        return [], [], f"{extraction_schema.PAGE_UNPARSEABLE}: the response was empty"
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        return [], [], f"{extraction_schema.PAGE_UNPARSEABLE}: {exc.msg} at position {exc.pos}"
    if not isinstance(parsed, list):
        return [], [], f"{extraction_schema.PAGE_NOT_A_LIST}: got {type(parsed).__name__}"
    rows: list[ProposedRow] = []
    refusals: list[str] = []
    for index, raw in enumerate(parsed):
        # The SAME four fields, named: measured on qwen3.5:4b, which answered
        # the array prompt with objects keyed exactly label/column/value/unit.
        # Only that exact key set is read this way - nothing is renamed,
        # guessed or defaulted, and every value still goes through the schema.
        if isinstance(raw, dict) and set(raw) == _COMPACT_KEYS \
                and all(isinstance(x, str) for x in raw.values()):
            raw = [raw["label"], raw["column"], raw["value"], raw["unit"]]
        if isinstance(raw, list) and len(raw) == 4 and all(isinstance(x, str) for x in raw):
            label, column, value, unit = raw
            raw = {"label": label, "column_header": column, "value": value,
                   "unit": unit, "is_blank": False, "page": page_no,
                   "source_text": " ".join(x for x in (label, value, unit) if x)}
        row, reason = extraction_schema.validate_row(raw)
        if row is None:
            refusals.append(f"row {index}: {reason}")
            continue
        if row.page != page_no:
            refusals.append(f"row {index}: page {row.page} is not the page sent ({page_no})")
            continue
        rows.append(ProposedRow(label=row.label.strip(), column_header=row.column_header.strip(),
                                value=row.value.strip(), unit=row.unit.strip(),
                                source_text=row.source_text))
    return rows, refusals, None


def read_page(stored_path: str, page_no: int, route: PageRoute, *,
              ocr_text: str | None = None,
              provider: ReasoningProvider | None = None) -> VisionReading:
    """Ask the model about one ROUTED page and validate every row it proposes.

    Refuses to run for a route that is not a vision route - the routing rule
    is enforced here too, not only by the caller. A provider refusal (model
    down, host refused) is recorded on the reading, never raised through the
    extraction: the page then stays exactly where it was, in engineer review.
    """
    if route.route not in VISION_ROUTES:
        raise ValueError(f"route {route.route!r} is never sent to the vision model")
    reading = VisionReading(page=page_no, route=route.route, region=route.region,
                            dpi=settings.vision_dpi)
    image = render_region(stored_path, page_no, route.region, settings.vision_dpi)
    packet = Packet(prompt=PROMPT.format(page=page_no),
                    num_ctx=settings.vision_num_ctx,
                    num_predict=settings.vision_num_predict,
                    temperature=0.0, think=False, seed=0,
                    images=(base64.b64encode(image).decode("ascii"),),
                    timeout_s=settings.vision_timeout_seconds)
    reading.prompt_sha256 = packet.sha256
    try:
        response = (provider or make_provider()).reason(packet)
    except ProviderRefused as exc:
        reading.page_refused = f"provider_refused: {exc}"
        return reading
    reading.model_tag = response.model_tag
    reading.tokens_in, reading.tokens_out = response.tokens_in, response.tokens_out
    reading.wall_time_s = response.wall_time_s
    if response.truncated:
        # A cut-off array can still parse up to a point; reading it would
        # present part of a page as all of it.
        reading.page_refused = "truncated: the output cap ended the answer"
        return reading
    rows, refusals, page_refusal = parse_rows(response.text, page_no)
    reading.refusals = refusals
    if page_refusal:
        reading.page_refused = page_refusal
        return reading
    if ocr_text is not None:
        for row in rows:
            validate_on_ocr_text(row, ocr_text)
    else:
        import pymupdf
        with pymupdf.open(stored_path) as doc:
            words = doc[page_no - 1].get_text("words")
        for row in rows:
            locate_on_page(row, words)
    reading.rows = rows
    return reading


# ----------------------------------------------------------- validation

@dataclass(frozen=True)
class _Word:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    index: int
    #: The word as the page prints it, for `source_text`, and which printed
    #: word it came from (a word split on its parentheses is several tokens).
    raw: str = ""
    word_no: int = -1


def _page_tokens(words) -> list[_Word]:
    """Page words in reading order, split the way `tokens` splits a value."""
    out: list[_Word] = []
    ordered = sorted(words, key=lambda w: (w[5], w[6], w[7]))
    for word_no, w in enumerate(ordered):
        for part in re.split(r"[\s()\[\]]+", w[4]):
            token = norm_token(part)
            if token:
                out.append(_Word(token, w[0], w[1], w[2], w[3], len(out), w[4], word_no))
    return out


def _find_sequences(page: list[_Word], wanted: list[str]) -> list[list[_Word]]:
    """Every run of consecutive page tokens equal to `wanted`."""
    if not wanted:
        return []
    hits = []
    n = len(wanted)
    for i in range(len(page) - n + 1):
        if all(page[i + k].text == wanted[k] for k in range(n)):
            hits.append(page[i:i + n])
    return hits


def _box(ws: list[_Word]) -> tuple[float, float, float, float]:
    return (min(w.x0 for w in ws), min(w.y0 for w in ws),
            max(w.x1 for w in ws), max(w.y1 for w in ws))


def _label_hits(page: list[_Word], label: str) -> list[list[_Word]]:
    wanted = tokens(label)
    hits = _find_sequences(page, wanted)
    if not hits and len(wanted) > 3:
        # A long label wraps and the pieces land out of reading order; its
        # first three words are still distinctive enough to find its row.
        hits = _find_sequences(page, wanted[:3])
    return hits


def locate_on_page(row: ProposedRow, words) -> ProposedRow:
    """Validate one proposed row against the page's NATIVE words.

    Kept (VALIDATED) only if, for some printed occurrence of the label and of
    the value:
      * the value's vertical centre lies within the label's row band, and it
        starts to the RIGHT of the label;
      * with a column heading named: that heading is printed ABOVE the value
        and overlaps it horizontally;
      * with no heading named: no other value-bearing word sits between the
        label and the value on that row - otherwise the model picked one of
        several columns without saying which.
    """
    page = _page_tokens(words)
    if not tokens(row.value):
        # Nothing but markers ('*', '____'): the model reported a blank slot,
        # and it was asked for printed values only.
        row.outcome, row.note = DROPPED, "the proposed value is only a blank marker"
        return row
    if any(piece and not norm_token(piece) for piece in re.split(r"\s+", row.value)):
        # A piece that is ONLY a marker - '*', a drawn '____' - is the sheet
        # saying "not filled in". Measured: `* to * m3/h` validated on its
        # remaining words and was stored as a filled value (#180).
        row.outcome = REVIEW
        row.note = "the proposed value contains a blank marker, not a printed value"
        return row
    value_hits = _find_sequences(page, tokens(row.value))
    if not value_hits:
        row.outcome, row.note = DROPPED, "value is not printed on this page"
        return row
    label_hits = _label_hits(page, row.label)
    if not label_hits:
        row.outcome, row.note = REVIEW, "value is printed but the label was not found on this page"
        return row
    header_hits = _find_sequences(page, tokens(row.column_header)) if row.column_header else []
    if row.column_header and not header_hits:
        row.outcome, row.note = REVIEW, "column heading named by the model is not printed on this page"
        return row

    best = None
    for lab in label_hits:
        lx0, ly0, lx1, ly1 = _box(lab)
        heights = [w.y1 - w.y0 for w in lab]
        tol = 0.5 * (sum(heights) / len(heights))
        for val in value_hits:
            vx0, vy0, vx1, vy1 = _box(val)
            cy = (vy0 + vy1) / 2
            if not (ly0 - tol <= cy <= ly1 + tol) or vx0 < lx1 - 1.0:
                continue
            region = [lx0, min(ly0, vy0), vx1, max(ly1, vy1)]
            if row.column_header:
                ok = False
                for head in header_hits:
                    hx0, hy0, hx1, hy1 = _box(head)
                    above = hy1 <= vy0 + tol
                    overlaps = min(hx1, vx1) - max(hx0, vx0) > -6.0
                    if above and overlaps:
                        ok = True
                        region = [min(region[0], hx0), min(region[1], hy0),
                                  max(region[2], hx1), region[3]]
                        break
                if not ok:
                    continue
            else:
                used = {w.index for w in lab} | {w.index for w in val}
                between = [w for w in page
                           if w.index not in used and is_value_word(w.text)
                           and lx1 - 1.0 <= w.x0 < vx0
                           and ly0 - tol <= (w.y0 + w.y1) / 2 <= ly1 + tol]
                if between:
                    continue
            distance = vx0 - lx1
            if best is None or distance < best[0]:
                best = (distance, lab, val, region)
    if best is None:
        row.outcome = REVIEW
        row.note = ("label and value are both printed but not in one row"
                    + (" under the named column" if row.column_header else
                       " with nothing between them"))
        return row
    _d, lab, val, region = best
    row.outcome = VALIDATED
    row.bbox = tuple(round(v, 1) for v in region)
    band = [w for w in page
            if w.x0 >= region[0] - 0.5 and w.x1 <= region[2] + 0.5
            and region[1] - 0.5 <= (w.y0 + w.y1) / 2 <= region[3] + 0.5]
    raw: dict[int, str] = {}
    for w in band:
        # A word split on its parentheses is several tokens of ONE printed
        # word; print it once.
        raw.setdefault(w.word_no, w.raw)
    row.source_text = " ".join(raw.values())
    row.note = ("value printed in the label's row"
                + (f" under the column '{row.column_header}'" if row.column_header
                   else ", nearest to the label"))
    return row


def validate_on_ocr_text(row: ProposedRow, ocr_text: str) -> ProposedRow:
    """A recognised page: text, no stored boxes, so NEVER a fact.

    The value must be on the label's recognised line or the next one to
    reach engineer review at all; otherwise it is dropped.
    """
    lines = [tokens(line) for line in (ocr_text or "").splitlines()]
    label, value = tokens(row.label), tokens(row.value)

    def holds(line: list[str], wanted: list[str]) -> bool:
        n = len(wanted)
        return bool(n) and any(line[i:i + n] == wanted for i in range(len(line) - n + 1))

    for i, line in enumerate(lines):
        if holds(line, label[:3] if len(label) > 3 else label):
            nearby = line + (lines[i + 1] if i + 1 < len(lines) else [])
            if holds(nearby, value):
                row.outcome = REVIEW
                row.note = ("value found beside its label in recognised text; "
                            "OCR boxes are not stored, so no region can be cited")
                return row
    if any(holds(line, value) for line in lines):
        row.outcome = REVIEW
        row.note = "value is in the recognised text but not beside its label"
        return row
    row.outcome, row.note = DROPPED, "value is not in this page's recognised text"
    return row
