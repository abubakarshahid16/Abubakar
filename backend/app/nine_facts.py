"""Role 1, the fact sheet: how the values of ONE paper are merged, stored per run and handed to the later roles (SPEC A.1/A.2 row 1, F.6).

Pure where it can be (`merge`, `digest`, `usable`), plus one small store (`ensure_schema`, `store`, `load`). Nothing here asks a model, opens a
socket or writes to `submittal_facts`: the sheet lives in its own tables, per run (a review never changes the live facts).

  * `merge(stored, read, pages, ...)`: the paper's STORED values (current ones only: `agent_review_calculator_reader.split_current`, #1824) and the
    values the Reader read, merged by `datasheet_ai.merge_readings` into agreed / conflict / ai_only / stored_only; a value read two ways, or the
    same field printed with two different values on two pages of one tag, is `conflict` and is never used; a stale stored value is `stale`.
  * `usable(sheet)`: the facts a later role may compare or cite (never a conflict, a stale value or a value an engineer has to decide).
  * `digest(sheet)`: the compact text later roles read, one line per usable value with its page and id, the conflicts apart.

No verdict class or word is made here (SPEC E). Ids, numbers, field labels and quotes only; a quote is kept only after code found it on the page.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import sqlite3
from collections import Counter
from collections.abc import Collection, Mapping, Sequence

from . import (
    agent_review_calculator_cells as cells_mod,
)
from . import (
    agent_review_calculator_reader as reader_mod,
)
from . import (
    datasheet_ai,
    datasheet_checks,
    form_reader,
    nine_call,
    nine_record,
    numparse,
    untrusted_value,
)
from .nine_contract import Engine, Fact, FactSheet, PageRead

#: the states a later role may use (a conflict, a stale value and a value for the engineer are never used)
USABLE_STATES = frozenset({"agreed", "ai_only", "stored_only"})
STALE_WORDS = reader_mod.STALE_WORDS


def _fold(text: object) -> str:
    return " ".join(str(text or "").lower().split())


def _identity(value: object, unit: object) -> tuple[str, str]:
    return numparse.fold_numbers(str(value or "")), _fold(unit)


def _role(label: str, rules: Mapping | None) -> str | None:
    if not label or rules is None:
        return None
    return datasheet_checks.role_of(label, dict(rules))


def _stored_state(f: Mapping, agreed: bool = False) -> str:
    """A stored value an engineer has to decide (a conflict recorded at ingest, a reading conflict, a kind not confirmed) is `needs_engineer`."""
    if untrusted_value.reason(f):
        return "needs_engineer"
    return "agreed" if agreed else "stored_only"


def _fact(
    n: tuple[int, int],
    *,
    label: str,
    value: str | None,
    unit: str | None,
    quote: str,
    quote_verified: bool,
    tag: str | None,
    cell_ref: str | None,
    source: str,
    state: str,
    sha: str | None,
    model: str | None,
    rules: Mapping | None,
) -> Fact:
    page, i = n
    return Fact(
        fact_id=f"f:{page}:{i}",
        page=page,
        field_label=label,
        field_role=_role(label, rules),
        value=value or None,
        unit=unit or None,
        quote=quote,
        quote_verified=quote_verified,
        tag=tag or None,
        cell_ref=cell_ref,
        source=source,
        state=state,
        page_text_sha=sha,
        model=model,  # type: ignore[arg-type]
    )


def _cell_refs(facts: Sequence[Mapping], tables: Mapping[int, list]) -> dict[str, str]:
    """fact id -> "t<table>r<row>c<col>" for a value that has exactly one table cell (the calculator's own locator, #1814)."""
    counts = cells_mod.page_tag_counts(facts)
    return {
        fid: f"t{c.table}r{c.row}c{c.value_col}"
        for fid, c in cells_mod.cells_of(facts, tables, counts).items()
    }


def _stored_shape(f: Mapping, n: int) -> dict:
    return {**f, "id": str(f.get("id") or f"s:{f.get('page')}:{n}")}


def _read_shape(f: Mapping, n: int) -> dict:
    """A verified reading in the shape the calculator's locator reads (`raw_value`, `source_text`, `equipment_tag`)."""
    return {
        "id": f"r:{f.get('page')}:{n}",
        "page": f.get("page"),
        "field_label": f.get("field"),
        "raw_value": f.get("value"),
        "source_text": f.get("quote"),
        "equipment_tag": f.get("tag"),
        "is_blank": 0 if f.get("value") else 1,
    }


def merge(
    stored: Sequence[Mapping],
    read: Sequence[Mapping],
    pages: Mapping[int, str],
    *,
    picture_pages: Collection[int] = (),
    model: str | None = None,
    tables: Mapping[int, list] | None = None,
    rules: Mapping | None = None,
) -> tuple[tuple[Fact, ...], dict[str, int]]:
    """(the facts of the sheet, counts). `stored` are the paper's facts as `datasheets.list_facts` gives them; `read` are the Reader's verified readings
    (`field`, `value`, `unit`, `quote`, `page`, optional `tag`, `kind`). A stored value of an earlier text of the page is `stale` and not merged."""
    current = [f for f in stored if reader_mod.is_current(f, pages)]
    stale = [f for f in stored if not reader_mod.is_current(f, pages)]
    n_stale = len(stale)
    cur = [_stored_shape(f, i) for i, f in enumerate(current)]
    # a read value counts only when its quote is on the page it names: checked HERE, so no caller can hand in an unverified reading
    ais = [
        dict(f, kind=f.get("kind") or "offered")
        for f in read
        if form_reader.quote_on_page(
            str(f.get("quote") or ""), pages.get(f.get("page") or 0, "")
        )
    ]
    unverified = len(read) - len(ais)
    cells = (
        _cell_refs(cur + [_read_shape(f, i) for i, f in enumerate(ais)], tables or {})
        if tables
        else {}
    )
    rule_cell = {id(f): cells.get(f["id"]) for f in cur}
    ai_cell = {id(f): cells.get(_read_shape(f, i)["id"]) for i, f in enumerate(ais)}
    decisions = datasheet_ai.merge_readings(cur, ais)
    counts = datasheet_ai.outcome_counts(decisions)
    seq: dict[int, int] = {}
    out: list[Fact] = []

    def nxt(page: int) -> tuple[int, int]:
        seq[page] = seq.get(page, 0) + 1
        return page, seq[page]

    def from_stored(f: Mapping, state: str) -> Fact:
        page = f.get("page") or 0
        raw = None if f.get("is_blank") else f.get("raw_value")
        text = pages.get(page, "")
        quote = str(f.get("source_text") or "")
        return _fact(
            nxt(page),
            label=str(f.get("field_label") or f.get("field_name") or ""),
            value=raw,
            unit=f.get("raw_unit") or f.get("unit"),
            quote=quote,
            quote_verified=form_reader.quote_on_page(quote, text) if quote else False,
            tag=f.get("equipment_tag"),
            cell_ref=rule_cell.get(id(f)),
            source="stored",
            state=state,
            sha=f.get("page_text_sha") or reader_mod.page_sha(text),
            model=None,
            rules=rules,
        )

    def from_read(a: Mapping, state: str) -> Fact:
        page = a.get("page") or 0
        return _fact(
            nxt(page),
            label=str(a.get("field") or ""),
            value=a.get("value"),
            unit=a.get("unit"),
            quote=str(a.get("quote") or ""),
            quote_verified=True,
            tag=a.get("tag"),
            cell_ref=ai_cell.get(id(a)),
            source="ai_picture" if page in picture_pages else "ai_text",
            state=state,
            sha=reader_mod.page_sha(pages.get(page, "")),
            model=model,
            rules=rules,
        )

    for d in decisions:
        kind = d["outcome"]
        if kind == datasheet_ai.AGREED:
            out.append(from_stored(d["rule"], _stored_state(d["rule"], agreed=True)))
        elif kind == datasheet_ai.CONFLICT:
            out.extend(from_stored(r, "conflict") for r in d["rules"])
            out.extend(from_read(a, "conflict") for a in d["ai"])
        elif kind == datasheet_ai.AI_ONLY:
            out.append(from_read(d["ai"], "ai_only"))
        else:
            out.append(from_stored(d["rule"], _stored_state(d["rule"])))
    out.extend(from_stored(f, "stale") for f in stale)
    out = _cross_page(out)
    counts = {
        **counts,
        "stale": n_stale,
        "unverified_dropped": unverified,
        "conflict_facts": sum(f.state == "conflict" for f in out),
    }
    return tuple(out), counts


def _cross_page(facts: list[Fact]) -> list[Fact]:
    """The same field printed with two different values on the paper (one page or two): both are `conflict`, UNLESS both values stand under different KNOWN tags
    (`agent_review_calculator_cells.other_tags`: both tagged, identifiers that do not overlap). A value with no tag, a tag list, or a tag that starts like the
    other's is never "another tag". Code compares; the engineer decides which is meant. The field is the registry's role when code found one, else the label."""
    groups: dict[str, list[int]] = {}
    for i, f in enumerate(facts):
        if f.state in USABLE_STATES and f.value is not None:
            groups.setdefault(f.field_role or _fold(f.field_label), []).append(i)
    bad: set[int] = set()
    for idx in groups.values():
        for n, i in enumerate(idx):
            for j in idx[n + 1 :]:
                a, b = facts[i], facts[j]
                if _identity(a.value, a.unit) != _identity(
                    b.value, b.unit
                ) and not cells_mod.other_tags(
                    {"equipment_tag": a.tag}, {"equipment_tag": b.tag}
                ):
                    bad.update((i, j))
    return [
        dataclasses.replace(f, state="conflict") if i in bad else f
        for i, f in enumerate(facts)
    ]


def sheet_of(
    run_id: str,
    paper_id: str,
    pages_total: int,
    pages: Sequence[PageRead],
    facts: Sequence[Fact],
    engine: Engine,
    models: Sequence[str],
) -> FactSheet:
    return FactSheet(
        run_id=run_id,
        paper_id=paper_id,
        pages_total=pages_total,
        pages=tuple(pages),
        facts=tuple(facts),
        conflicts=sum(f.state == "conflict" for f in facts),
        engine=engine,
        models=tuple(models),
    )


def usable(sheet: FactSheet) -> tuple[Fact, ...]:
    """The values a later role may compare or cite: never a conflict, a stale value or a value an engineer has to decide."""
    return tuple(
        f for f in sheet.facts if f.state in USABLE_STATES and f.quote_verified
    )


def digest(sheet: FactSheet, max_chars: int = 8000) -> str:
    """The compact text the later roles read: one line per usable value (id, page, label, value, unit, tag, cell), then the values read two ways
    (named as such, never to be compared), then the pages not read with why. Cut at `max_chars` on a line end and says how many lines it left out."""

    def line(f: Fact) -> str:
        shown = " ".join(p for p in (f.value, f.unit) if p) or "(printed, empty)"
        extra = "".join(
            f" [{k} {v}]" for k, v in (("tag", f.tag), ("cell", f.cell_ref)) if v
        )
        return f"{f.fact_id} p{f.page} {f.field_label}: {shown}{extra}"

    rows = [line(f) for f in sorted(usable(sheet), key=lambda f: (f.page, f.fact_id))]
    clash = [line(f) + f" ({f.source})" for f in sheet.facts if f.state == "conflict"]
    notread = [
        f"p{p.page}: {p.not_read_why}"
        for p in sheet.pages
        if not p.text_read and p.not_read_why
    ]
    out: list[str] = [f"FACT SHEET: {len(rows)} values of {sheet.pages_total} pages"]
    used = len(out[0]) + 1
    left = 0
    for r in rows:
        if used + len(r) + 1 > max_chars:
            left += 1
            continue
        out.append(r)
        used += len(r) + 1
    if left:
        out.append(f"({left} more values not shown here)")
    if clash:
        out.append(f"READ TWO WAYS, NOT USED ({len(clash)}):")
        out.extend(clash[:40])
    if notread:
        out.append("PAGES NOT READ:")
        out.extend(notread[:40])
    return "\n".join(out)


# ------------------------------------------------------------------ the digest as a DERIVED block for the seam


#: the app's own vocabularies, fixed at import (`nine_call.vocabulary`): the field keys of the reference data (+ "unknown" for a value no role names), the
#: states of a fact, and the form of a tag the paper does not print as the sheet has it
_ROLE_WORDS = frozenset(datasheet_checks.load_rules()["roles"])
#: Each field of the registry goes to the model as a SHORT STABLE CODE (`k` + 6 hex digits of the field's name: 7 characters, `[a-z0-9]+`, the same
#: code whatever else the registry holds). The words themselves ("set pressure") are ordinary phrases that occur in many held documents, and the
#: held-text guard (12 characters and more) would drop the whole block for them; a code of fewer than 12 characters is not text, and the legend (code =
#: the registry's field name) is app text that goes in the reviewer's own fixed words, never as a document block.
UNKNOWN_CODE = "unknown"


def role_code(role: str) -> str:
    return "k" + hashlib.sha256(str(role).encode("utf-8")).hexdigest()[:6]


ROLE_CODES: dict[str, str] = {r: role_code(r) for r in sorted(_ROLE_WORDS)}
if len(set(ROLE_CODES.values())) != len(
    ROLE_CODES
):  # a collision is a defect of the registry's names, found at import, never in a run
    raise RuntimeError("two registry fields have the same short code")
FIELD_KEYS = nine_call.vocabulary(
    "nine_field_keys", [*ROLE_CODES.values(), UNKNOWN_CODE]
)


def legend() -> str:
    """`code = field name` for every field of the registry, one per line: the app's own words (not a document's)."""
    return "\n".join(f"{c} = {r.replace('_', ' ')}" for r, c in ROLE_CODES.items())


def codes_of(roles) -> set[str]:
    """The short codes of the registry fields named in `roles` (a name the registry does not hold has no code and is left out)."""
    return {ROLE_CODES[r] for r in roles if r in ROLE_CODES}


STATES = nine_call.vocabulary(
    "nine_fact_states",
    ["agreed", "conflict", "ai_only", "stored_only", "needs_engineer", "stale"],
)
TAG_FORMS = nine_call.vocabulary("nine_tag_forms", ["none", "not_printed"])
#: the columns, each with its declared kind (`nine_call.Block.kinds`). Fact id: an id the app issues ("f:<page>:<n>"). Field key and state: words of the
#: vocabularies above. Value as printed and the TAG are DOCUMENT TEXT: kind `source`, found in the paper's own stored text. The page: a number.
#: Two blocks: facts WITH a tag printed on the paper (a `source` tag column), and facts without one (a tag-form word: "none", or "not_printed" when the
#: sheet has a tag the page does not print in that spelling).
#: fact ids are ids the app issued: an id cell is accepted only when this lookup finds it among the facts STORED for this run (`store` first, then build the
#: digest blocks). Registered at import; `nine_call.freeze()` closes the registries at app start, so this module must be imported by then.
FACT_ID = nine_call.id_source(
    "nine_fact_sheet",
    r"f:[0-9]{1,9}(:[0-9]{1,9}){0,3}",
    "SELECT 1 FROM agent_review_fact WHERE run_id = ? AND fact_id = ?",
)
TAGGED_KINDS = (
    "id",
    f"vocab:{FIELD_KEYS}",
    "source",
    "number",
    "source",
    f"vocab:{STATES}",
)
UNTAGGED_KINDS = (
    "id",
    f"vocab:{FIELD_KEYS}",
    "source",
    "number",
    f"vocab:{TAG_FORMS}",
    f"vocab:{STATES}",
)


def _whole(cand: str, text: str) -> bool:
    """`cand` stands in `text` as a whole token or number: "5" is not found inside "150" or "1.5"."""
    pat = (
        r"(?<![0-9a-z])(?<![0-9][.,])"
        + re.escape(fold_text(cand))
        + r"(?![0-9a-z])(?![.,][0-9])"
    )
    return re.search(pat, text) is not None


def _printed(f: Fact, pages: Mapping[int, str]) -> str | None:
    """The value as the page prints it (value and unit when they stand together), or None when the page does not hold it as a whole token: a cell of kind
    `source` must be found in the paper's stored text, so a value that is not is left out of the block, and counted."""
    text = fold_text(pages.get(f.page, ""))
    for cand in (f"{f.value} {f.unit}".strip() if f.unit else "", str(f.value or "")):
        if cand and _whole(cand, text):
            return cand if len(cand) <= 60 and "\n" not in cand else None
    return None


def fold_text(text: object) -> str:
    return nine_record.fold(str(text or ""))


def _row_priority(row: tuple[str, ...]) -> int:
    """0: a value of a field the app knows (a role) that is not in conflict; 1: a value of an unknown field; 2: a value read two ways (it is kept
    only to say "do not take this for a value", so it goes last)."""
    return 2 if row[-1] == "conflict" else (0 if row[1] != "unknown" else 1)


def fit_rows(
    rows: Sequence[tuple[str, ...]], limit: int | None = None
) -> tuple[list[tuple[str, ...]], int]:
    """(the rows that fit one derived block, how many were left out). A derived block is a digest, not a copy: the seam refuses more than
    `nine_call.MAX_DERIVED_CHARS` characters of cells in one block, and a real sheet can be several times that. Rows are kept by priority (a known
    field first, then an unknown one, then values read two ways), each priority in its own page order, whole rows only; the kept rows go back to
    page order. The cap is never raised and the block is never split to get round it: what does not fit is COUNTED, and the record says so."""
    cap = nine_call.MAX_DERIVED_CHARS if limit is None else limit
    keep: set[int] = set()
    used = 0
    for i in sorted(range(len(rows)), key=lambda i: (_row_priority(rows[i]), i)):
        cost = sum(len(c) + 3 for c in rows[i])
        if used + cost <= cap:
            keep.add(i)
            used += cost
    return [r for i, r in enumerate(rows) if i in keep], len(rows) - len(keep)


def digest_rows(
    sheet: FactSheet, pages: Mapping[int, str]
) -> tuple[list[tuple[str, ...]], list[tuple[str, ...]], Counter]:
    """(tagged rows, untagged rows, what was left out and why), in page order, BEFORE any size fitting. A row per fact that is not stale and has a
    value the page prints; conflicts stay in with the state "conflict" so no later role takes them for a value."""
    tagged: list[tuple[str, ...]] = []
    untagged: list[tuple[str, ...]] = []
    left_out: Counter = Counter()
    for f in sorted(sheet.facts, key=lambda f: (f.page, f.fact_id)):
        if f.state == "stale":
            left_out["stored value belongs to an earlier text of the page"] += 1
            continue
        if f.value is None:
            left_out["printed but empty (no value)"] += 1
            continue
        if (
            not f.quote_verified
        ):  # a value whose own quote is not on its page is never read as a fact
            left_out["quote not verified"] += 1
            continue
        shown = _printed(f, pages)
        if shown is None:
            left_out["value not printed on the page"] += 1
            continue
        key = ROLE_CODES.get(f.field_role or "", UNKNOWN_CODE)
        head = (f.fact_id, key, shown, str(f.page))
        if (
            f.tag
            and len(f.tag) <= 60
            and "\n" not in f.tag
            and fold_text(f.tag) in fold_text(pages.get(f.page, ""))
        ):
            tagged.append((*head, f.tag, f.state))
        else:
            untagged.append((*head, "not_printed" if f.tag else "none", f.state))
    return tagged, untagged, left_out


def _cost(rows: Sequence[tuple[str, ...]]) -> int:
    return sum(len(c) + 3 for r in rows for c in r)


def digest_fits(tagged: Sequence, untagged: Sequence) -> bool:
    """Whether each of the two digest blocks is within ONE derived block (`nine_call.MAX_DERIVED_CHARS`)."""
    return (
        _cost(tagged) <= nine_call.MAX_DERIVED_CHARS
        and _cost(untagged) <= nine_call.MAX_DERIVED_CHARS
    )


def rows_blocks(
    paper_id: str, tagged: Sequence, untagged: Sequence
) -> list[nine_call.Block]:
    out = []
    for name, kinds, rows in (
        ("fact_sheet", TAGGED_KINDS, tagged),
        ("fact_sheet_untagged", UNTAGGED_KINDS, untagged),
    ):
        if rows:
            out.append(
                nine_call.Block(
                    "review_record", name=name, sources=(paper_id,), kinds=kinds, items=tuple(rows)
                )
            )  # fmt: skip
    return out


def split_by_page(
    rows: Sequence[tuple[str, ...]],
) -> tuple[list[list[tuple[str, ...]]], int]:
    """(chunks, rows left out): the rows (in page order) cut into chunks that each fit ONE derived block, on a page boundary. Only a single page
    that is larger than a block by itself is cut inside (`fit_rows`: known fields first), and what it loses is counted."""
    chunks: list[list[tuple[str, ...]]] = []
    cut = 0
    by_page: dict[str, list[tuple[str, ...]]] = {}
    for r in rows:
        by_page.setdefault(r[3], []).append(r)
    cap = nine_call.MAX_DERIVED_CHARS
    now: list[tuple[str, ...]] = []
    for page_rows in by_page.values():
        if _cost(page_rows) > cap:
            page_rows, lost = fit_rows(page_rows)
            cut += lost
        if now and _cost(now) + _cost(page_rows) > cap:
            chunks.append(now)
            now = []
        now = [*now, *page_rows]
    if now:
        chunks.append(now)
    return chunks, cut


def digest_parts(
    paper_id: str,
    tagged: Sequence[tuple[str, ...]],
    untagged: Sequence[tuple[str, ...]],
    roles: Collection[str] | None = None,
) -> tuple[list[list[nine_call.Block]], Counter]:
    """(the parts, what was left out and why) of the facts ONE request needs. `roles` (the field roles of the rules asked from this chapter's book)
    narrows the rows to those fields; none = every row. If what is left does not fit ONE block per kind, the rows go into several PARTS on page
    boundaries (the caller sends the chapter once per part and says so). Nothing is dropped without a count and a reason."""
    left: Counter = Counter()

    def narrow(rows):
        if not roles:
            return list(rows)
        keep = [r for r in rows if r[1] in roles]
        left["field not asked from this chapter's book"] += len(rows) - len(keep)
        return keep

    t_chunks, t_cut = split_by_page(narrow(tagged))
    u_chunks, u_cut = split_by_page(narrow(untagged))
    if t_cut + u_cut:
        left["over the size limit of a derived block"] += t_cut + u_cut
    parts = []
    for k in range(max(len(t_chunks), len(u_chunks), 1)):
        blocks = rows_blocks(
            paper_id,
            t_chunks[k] if k < len(t_chunks) else (),
            u_chunks[k] if k < len(u_chunks) else (),
        )
        if blocks:
            parts.append(blocks)
    return parts, left


BLANK_KINDS = ("id", f"vocab:{FIELD_KEYS}", "number")


def blank_rows(sheet: FactSheet) -> tuple[list[tuple[str, ...]], Counter]:
    """(rows, left out): the fields the paper PRINTS and leaves EMPTY, one row per (field, page): fact id, the field's short code, the page. No value (there is
    none): the block's name, `fact_sheet_blank`, says "printed, blank". A reviewer needs these rows to find a required item the paper leaves blank. A blank
    of a field the registry has no code for, or whose label is not on its page, is counted, not listed."""
    out: list[tuple[str, ...]] = []
    left: Counter = Counter()
    seen: set[tuple[str, int]] = set()
    for f in sorted(sheet.facts, key=lambda f: (f.page, f.fact_id)):
        if f.state == "stale" or f.value is not None:
            continue
        code = ROLE_CODES.get(f.field_role or "")
        if code is None:
            left["blank of a field the registry does not name"] += 1
            continue
        if not f.quote_verified:
            left["blank whose label is not on its page"] += 1
            continue
        if (code, f.page) in seen:
            continue
        seen.add((code, f.page))
        out.append((f.fact_id, code, str(f.page)))
    return out, left


def blank_block(
    paper_id: str, rows: Sequence[tuple[str, ...]]
) -> nine_call.Block | None:
    """The blank fields as ONE derived block, `fact_sheet_blank` (its own words say "printed, blank"; the reviewer's fixed text explains the name)."""
    if not rows:
        return None
    return nine_call.Block(
        "review_record",
        name="fact_sheet_blank",
        sources=(paper_id,),
        kinds=BLANK_KINDS,
        items=tuple(rows),
    )


def digest_blocks(
    sheet: FactSheet, pages: Mapping[int, str]
) -> tuple[list[nine_call.Block], dict[str, int]]:
    """(Call AFTER `store`: the seam looks each fact id up among this run's stored facts.) The whole fact sheet as DERIVED blocks of the seam
    (`review_record`, the paper its only source), fitted to ONE block per kind when it is bigger (rows kept by priority, the rest COUNTED). A caller
    that must not lose rows uses `digest_rows` and `digest_parts` instead. Returns (the blocks, counts)."""
    tagged, untagged, left_out = digest_rows(sheet, pages)
    cut_rows = 0
    kept: dict[str, int] = {}
    fitted = []
    for name, rows in (("fact_sheet", tagged), ("fact_sheet_untagged", untagged)):
        rows, cut = fit_rows(rows)
        if cut:
            left_out["over the size limit of a derived block"] += cut
            cut_rows += cut
        kept[name] = len(rows)
        fitted.append(rows)
    return rows_blocks(sheet.paper_id, *fitted), {
        "rows_tagged": kept["fact_sheet"],
        "rows_untagged": kept["fact_sheet_untagged"],
        "rows_cut_for_size": cut_rows,
        "left_out": sum(left_out.values()),
        "left_out_reasons": dict(left_out),
    }


# ------------------------------------------------------------------ the store (per run; never `submittal_facts`)

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS agent_review_fact_sheet (
        run_id TEXT PRIMARY KEY, paper_id TEXT NOT NULL, pages_total INTEGER NOT NULL, engine TEXT NOT NULL, models_json TEXT NOT NULL,
        conflicts INTEGER NOT NULL, produced_json TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS agent_review_fact (
        run_id TEXT NOT NULL, fact_id TEXT NOT NULL, page INTEGER NOT NULL, field_label TEXT NOT NULL, field_role TEXT, value TEXT, unit TEXT,
        quote TEXT NOT NULL, quote_verified INTEGER NOT NULL, tag TEXT, cell_ref TEXT, source TEXT NOT NULL, state TEXT NOT NULL, page_text_sha TEXT, model TEXT,
        PRIMARY KEY (run_id, fact_id))""",
    """CREATE TABLE IF NOT EXISTS agent_review_page_read (
        run_id TEXT NOT NULL, page INTEGER NOT NULL, text_read INTEGER NOT NULL, picture_read INTEGER NOT NULL, not_read_why TEXT,
        PRIMARY KEY (run_id, page))""",
)


def ensure_schema(conn: sqlite3.Connection | None = None) -> None:
    if conn is None:
        from .db import connect

        conn = connect()
    for sql in _SCHEMA:
        conn.execute(sql)


def store(
    conn: sqlite3.Connection, sheet: FactSheet, produced: Mapping | None = None
) -> None:
    """Replace this run's sheet (a restart writes the same sheet again, never a second one). One transaction."""
    ensure_schema(conn)
    with conn:
        for t in (
            "agent_review_fact",
            "agent_review_page_read",
            "agent_review_fact_sheet",
        ):
            conn.execute(f"DELETE FROM {t} WHERE run_id = ?", (sheet.run_id,))
        conn.execute(
            "INSERT INTO agent_review_fact_sheet VALUES (?,?,?,?,?,?,?)",
            (
                sheet.run_id,
                sheet.paper_id,
                sheet.pages_total,
                sheet.engine,
                json.dumps(list(sheet.models)),
                sheet.conflicts,
                json.dumps(dict(produced or {})),
            ),
        )
        conn.executemany(
            "INSERT INTO agent_review_fact VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    sheet.run_id,
                    f.fact_id,
                    f.page,
                    f.field_label,
                    f.field_role,
                    f.value,
                    f.unit,
                    f.quote,
                    int(f.quote_verified),
                    f.tag,
                    f.cell_ref,
                    f.source,
                    f.state,
                    f.page_text_sha,
                    f.model,
                )
                for f in sheet.facts
            ],
        )
        conn.executemany(
            "INSERT INTO agent_review_page_read VALUES (?,?,?,?,?)",
            [
                (
                    sheet.run_id,
                    p.page,
                    int(p.text_read),
                    int(p.picture_read),
                    p.not_read_why,
                )
                for p in sheet.pages
            ],
        )


def load(conn: sqlite3.Connection, run_id: str) -> FactSheet | None:
    """The stored sheet of a run, or None when the Reader did not store one (an older run, or the role did not run)."""
    try:
        head = conn.execute(
            "SELECT paper_id, pages_total, engine, models_json FROM agent_review_fact_sheet WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if head is None:
            return None
        facts = conn.execute(
            "SELECT fact_id, page, field_label, field_role, value, unit, quote, quote_verified, tag, cell_ref, source, state, page_text_sha, model "
            "FROM agent_review_fact WHERE run_id = ? ORDER BY page, rowid",
            (run_id,),
        ).fetchall()
        pages = conn.execute(
            "SELECT page, text_read, picture_read, not_read_why FROM agent_review_page_read WHERE run_id = ? ORDER BY page",
            (run_id,),
        ).fetchall()
    except sqlite3.OperationalError:
        return None  # the tables do not exist: a review made before the Reader
    return sheet_of(
        run_id,
        head[0],
        head[1],
        [PageRead(r[0], bool(r[1]), bool(r[2]), r[3]) for r in pages],
        [
            Fact(
                r[0],
                r[1],
                r[2],
                r[3],
                r[4],
                r[5],
                r[6],
                bool(r[7]),
                r[8],
                r[9],
                r[10],
                r[11],
                r[12],
                r[13],
            )
            for r in facts
        ],
        head[2],
        json.loads(head[3]),
    )
