"""THE ONE CALL SEAM of the nine-role review (owner order, 15 Nov 2026; SPEC sections B and F; strict by construction after reviews R63, R63b).

Every model call of roles 1 to 6 and 9 is made by `ask(...)` and by nothing else. Nothing a caller hands in is trusted as TEXT:

* THE ENGINE IS DERIVED FROM THE RUN, DEFAULT DENY (`engine_decision`). "claude" only when the run's own STORED decision says so: a stored
  choice that does not bar Claude, a stored plan with text leaving, a stored shown list, no bar in the context and none on the job.
  Anything else is Local, and a caller who asks for Claude is refused (`run_is_local`, or `no_engine_decision` when nothing is stored).
* THE STARTER'S ACCESS applies to every block on every engine (`outside_access`; rule 5: intersection); the shown list and the approval
  gate (`claude_approved.refusal`) apply on top for Claude.
* QUESTION AND SYSTEM WORDS ARE TEMPLATES (`template(id, text, **kinds)`), parameters only of the typed kinds `int`, `number`, `clause`,
  `standard`, `unit` (a unit of the fixed list), `role` (a role name), `id` (an id the app issues: `id_shape`, a document or run id) and
  `vocab:<name>` (a word of an app-owned vocabulary registered with `vocabulary`): never free text. A parameter of 12 or more
  characters (folded by `nine_record.hfold`: hyphens, underscores, colons, full stops and white space are all one space) that occurs in
  the stored text of a document the gate refuses in this run is refused (`text_from_held_document`). The template id and a digest of
  the parameters are written in the call's record row.
* TEXT BLOCKS ARE LOADED BY THE SEAM: `(document_id, pages[, char_from, char_to])` -> the stored page text; a picture block -> the page
  rendered by the seam. A caller cannot put other words under a document's id.
* A DERIVED BLOCK (`review_record`: the fact-sheet digest, the context note, earlier findings) names its `sources` and carries `items`, rows
  of cells, with the kind of each column declared (`kinds`: `id`, `number`, `clause`, `standard`, `enum`, `unit`, `source`,
  `vocab:<name>`). At send time, for Claude, EVERY CELL is checked: (a) it is a typed value: a number, a clause number, a standard id read
  by `standard_ids`, a unit of the fixed list, an id the app issues, a word of `DERIVED_ENUM` or of the app-owned vocabulary the column
  names (a plain dictionary word is not a code: a free token is refused `cell_not_in_vocabulary`), or (b) a `source` cell: it occurs (case
  and white space folded) in the stored text of one of the block's OWN declared sources; the source, the page and the span are written in
  `agent_review_role_cell`, and `scripts/nine_record_check.py` re-reads that span and compares its checksum. THE HELD-TEXT RULE comes
  first and applies to every cell, to each ROW's joined text and to every window of three consecutive cells (across rows too), all of 12 or
  more characters once folded by `hfold`: any of them found in the stored text of a document the gate refuses in this run drops the block
  (`text_from_held_document`) whatever the sources say. Every source must pass the gate or the whole block is dropped.

AFTER THIS CHANGE THE ONLY DOCUMENT-DERIVED TEXT THAT CAN REACH A BODY OUTSIDE A GATED DOCUMENT BLOCK IS (i) a `source` cell found in one of
the block's own declared, gated sources, and (ii) typed values (numbers, units, clause numbers, standard ids, app-issued ids, words of
app-owned vocabularies). That residue is accepted.

The SAME block list is (a) the request, (b) the declaration to the approval gate (`claude_approved.carrying`), and (c) the role record
(`nine_record`: one read row per block, one per source of a derived block, one cell row per cell). The `sent` row is written by a
transport wrapper only AFTER the spend reservation succeeded, so a call refused at the reservation has no read rows.

A HELD DOCUMENT NEVER REACHES A BODY: each document (and each source) is put to the one gate: not on the stored list, not approved, blocked
(the register), a contract without the explicit choice, or a barred run. A refused block is dropped before the request is built and named in
`Answer.not_sent`; none left = the call is `refused`, no body, no ledger line.

MONEY. One step name per role (`nine_contract.STEP_OF_ROLE`): its own ledger line and USD 5 cap in `claude_spend`, which is NOT changed.
A role's design budget (`ROLE_BUDGET_USD`, not a cap) counts known costs and, for a failed call of unknown cost, the reserved amount.

Claude goes through `agent_claude._call` (-> `reader_transport`): no other socket. Local goes through the injected `local_send` or
`model_transport`: a call row with the cost NULL and no ledger line. Nothing here logs document text; a failure is a code.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from . import agent_claude, claude_approved, claude_spend, nine_record
from .claude_image_tokens import json_counts
from .db import connect
from .nine_contract import ROLE_NAMES, STEP_OF_ROLE, ReadEntry

log = logging.getLogger(__name__)

#: design budgets per role (SPEC F.2): not a cap, under the USD 5 step cap; the run cap is the backstop
ROLE_BUDGET_USD: dict[int, float] = {
    1: 0.50,
    2: 1.00,
    3: 0.25,
    4: 4.00,
    5: 2.00,
    6: 3.00,
    9: 0.50,
}
DEFAULT_MODEL: dict[int, str] = {6: agent_claude.SECOND_MODEL}
DEFAULT_MAX_TOKENS = 2048
STORED_KINDS = ("paper", "rule_book", "project_document", "earlier_revision")
DERIVED_KIND = "review_record"
MAX_DERIVED_CHARS = 30_000  # a derived block is a digest, not a copy
MAX_CELL_CHARS = 200
MAX_TEMPLATE_CHARS = 20_000
TEXT_NOT_FROM_BLOCK = "text_not_from_block"
HELD_TEXT = "text_from_held_document"
NO_DECISION = "no_engine_decision"
OUTSIDE_ACCESS = "outside_access"
NOT_ON_LIST = "not_on_list"
CELL_NOT_FROM_SOURCES = "cell_not_from_sources"
CELL_WRONG_KIND = "cell_wrong_kind"
#: the words a derived cell may be without being found in a source (a fixed set, not prose)
DERIVED_ENUM = frozenset(
    {
        "met", "not_met", "pass", "fail", "partly", "partly_met", "unknown", "yes", "no", "true", "false",
        "paper", "rule_book", "project_document", "earlier_revision", "claude", "local", "code", "high", "medium", "low",
        "shall", "should", "may", "must", "held", "not_held", "related",
    }
)  # fmt: skip

_ID = re.compile(r"^[A-Za-z0-9_.:\-]{1,64}$")
_NUMBER = re.compile(r"^[+-]?\d{1,12}([.,]\d{1,9})?%?$")
_CLAUSE = re.compile(r"^\d{1,3}(\.\d{1,3}){1,5}[a-z]?$")
_LINE = re.compile(r"^[^\s\x00-\x1f][^\x00-\x1f]{0,%d}$" % (MAX_CELL_CHARS - 1))
DECLARED_KINDS = ("id", "number", "clause", "standard", "enum", "unit", "source")
PARAM_KINDS = ("id", "int", "role", "clause", "number", "unit", "standard")
CELL_NOT_IN_VOCAB = "cell_not_in_vocabulary"
PARAM_NOT_APP_ID = "param_not_app_id"

# ---------------------------------------------------------------------------------------- app-owned vocabularies and id shapes

_VOCAB: dict[str, frozenset[str]] = {}
_ID_SHAPES: dict[str, re.Pattern] = {}
UNITS = frozenset(
    "bar barg bara psi psig psia kpa mpa pa mbar mm cm m km in ft yd c f k kg g mg lb t kw w mw hp rpm hz khz v kv a ma kva l ml m3 "
    "m2 mm2 cm2 s ms min h hr day nm kn n kgf lbf j kj mj ppm ppb db dba pct % deg degc degf bpm gpm lpm cfm scfm nm3 mol kmol "
    "cst cp ohm".split()
)


_FROZEN = False
MAX_VOCAB_WORDS = 300
MAX_VOCAB_WORD_CHARS = 32
_VOCAB_WORD = re.compile(
    r"^[a-z0-9_]+$"
)  # an app key shape: 32 characters of it cannot carry a sentence
MAX_SHAPE_CHARS = 64
_ID_SOURCES: dict[str, tuple[re.Pattern, str | None, bool]] = {}


def freeze() -> None:
    """Close the registries (app startup, after every role module has been imported): `vocabulary`, `id_shape` and `id_source` raise
    afterwards. What a run may send as a typed word is fixed by the code that shipped, never by a run."""
    global _FROZEN
    _FROZEN = True


def _thaw_for_tests() -> None:
    global _FROZEN
    _FROZEN = False


def _closed() -> None:
    if _FROZEN:
        raise NineCallError(
            "the vocabularies and id shapes are frozen: they are registered at import only"
        )


def vocabulary(name: str, words) -> str:
    """Register an APP-OWNED vocabulary (called by app code at import, before `freeze`): the words a `vocab:<name>` column or parameter
    may hold: at most 300 words of at most 32 characters, each an app key of [a-z0-9_]. Folded by `nine_record.fold`. The same name with other words is refused."""
    _closed()
    folded = frozenset(nine_record.fold(w) for w in words)
    if (
        not _ID.match(name)
        or not folded
        or len(folded) > MAX_VOCAB_WORDS
        or any(
            len(w) > MAX_VOCAB_WORD_CHARS or not _VOCAB_WORD.match(w) for w in folded
        )
    ):
        raise NineCallError(
            "a vocabulary has a name and up to 300 app keys of [a-z0-9_] (32 characters at most)"
        )
    if _VOCAB.get(name, folded) != folded:
        raise NineCallError(f"vocabulary {name!r} already holds other words")
    _VOCAB[name] = folded
    return name


def _check_shape(pattern: str) -> re.Pattern:
    """A shape of ids is bounded and narrow: no `.`, no negated or word-wide class, no unbounded repeat, at most 64 characters wide."""
    from re import _constants as c
    from re import _parser

    parsed = _parser.parse(pattern)
    if parsed.getwidth()[1] > MAX_SHAPE_CHARS:
        raise NineCallError("an id shape is bounded: 64 characters wide at most")

    def walk(items) -> None:
        for op, arg in items:
            if op in (c.ANY, c.NOT_LITERAL):
                raise NineCallError("an id shape has no `.` and no negation")
            if op is c.IN:
                for sub_op, sub_arg in arg:
                    if sub_op is c.NEGATE or (
                        sub_op is c.CATEGORY and sub_arg is not c.CATEGORY_DIGIT
                    ):
                        raise NineCallError(
                            "an id shape names its characters: no negated class, no \\w, \\S"
                        )
            elif op in (c.MAX_REPEAT, c.MIN_REPEAT):
                _lo, hi, sub = arg
                if hi == c.MAXREPEAT:
                    raise NineCallError("an id shape has bounded repeats")
                walk(sub)
            elif op is c.SUBPATTERN:
                walk(arg[3])
            elif op is c.BRANCH:
                for branch in arg[1]:
                    walk(branch)
            elif op is c.CATEGORY and arg is not c.CATEGORY_DIGIT:
                raise NineCallError("an id shape names its characters")

    walk(parsed)
    return re.compile(pattern)


def id_source(
    name: str, pattern: str, lookup_sql: str | None, *, per_run: bool = True
) -> str:
    """Register ONE kind of id the app issues (before `freeze`): a bounded, narrow whole-id `pattern` AND a lookup that finds the id among
    the ids the app really issued: `lookup_sql` is `SELECT 1 FROM <table> WHERE ... = ?`, run with (run_id, id) when `per_run` (its
    first `?` is the run id) or with (id) alone; None = the ids come from the call itself (chapter codes of its blocks). A shape alone
    never admits an id."""
    _closed()
    compiled = _check_shape(pattern)
    if lookup_sql is not None and (
        not lookup_sql.startswith("SELECT 1 FROM ")
        or ";" in lookup_sql
        or lookup_sql.count("?") != (2 if per_run else 1)
    ):
        raise NineCallError(
            "an id lookup is one SELECT 1 FROM ... with the run id (when per run) and the id as parameters"
        )
    known = _ID_SOURCES.get(name)
    if known is not None and (known[0].pattern, known[1], known[2]) != (
        pattern,
        lookup_sql,
        per_run,
    ):
        raise NineCallError(f"id source {name!r} already holds another definition")
    _ID_SOURCES[name] = (compiled, lookup_sql, per_run)
    return name


def id_shape(name: str, pattern: str) -> str:
    """Removed: a shape alone admits nothing. Use `id_source` with a lookup."""
    raise NineCallError(
        "an id shape needs a lookup: register it with id_source(name, pattern, lookup_sql)"
    )


vocabulary("derived_enum", DERIVED_ENUM)
for _name, _pattern, _sql, _per_run in (
    (
        "document",
        r"[A-Za-z0-9_\-]{1,64}",
        "SELECT 1 FROM documents WHERE id = ?",
        False,
    ),
    (
        "document_sha",
        r"[0-9a-f]{64}",
        "SELECT 1 FROM documents WHERE sha256 = ?",
        False,
    ),
    ("run", r"[A-Za-z0-9_\-]{1,64}", "SELECT 1 FROM review_runs WHERE id = ?", False),
    (
        "call",
        r"[0-9a-f]{16}",
        "SELECT 1 FROM agent_review_role_call WHERE run_id = ? AND call_id = ?",
        True,
    ),
    (
        "read_sha",
        r"[0-9a-f]{64}",
        "SELECT 1 FROM agent_review_role_read WHERE run_id = ? AND text_sha256 = ?",
        True,
    ),
    (
        "rule",
        r"[A-Za-z0-9_:\-]{1,64}",
        "SELECT 1 FROM agent_review_rule WHERE run_id = ? AND rule_key = ?",
        True,
    ),
    ("chapter", r"c\d{1,4}", None, True),
):
    id_source(_name, _pattern, _sql, per_run=_per_run)


@dataclass(frozen=True)
class IdContext:
    """Where an id is looked up: the connection, the run, and the chapter codes of the call's own blocks."""

    conn: object
    run_id: str
    chapters: frozenset[str] = frozenset()


def _is_unit(text: str) -> bool:
    t = text.strip().lower()
    parts = [p for p in re.split(r"[/\u00b7*^ ]+", t) if p]
    return (
        bool(parts)
        and len(t) <= 16
        and all(
            re.sub(r"[\d\u00b2\u00b3\-]+$", "", p) in UNITS or p in UNITS for p in parts
        )
    )


def _in_vocabulary(kind: str, text: str) -> bool:
    name = kind.split(":", 1)[1] if kind.startswith("vocab:") else ""
    return nine_record.fold(text) in _VOCAB.get(name, frozenset())


def _app_id(ctx: IdContext, text: str) -> bool:
    """An id the app really issued: it fits a registered bounded shape AND the lookup of that source finds it (for this run or in the
    library); a chapter code must be one of the chapter codes of this call's own blocks."""
    text = text.strip()
    for pattern, sql, per_run in _ID_SOURCES.values():
        if not pattern.fullmatch(text):
            continue
        if sql is None:
            if text in ctx.chapters:
                return True
            continue
        try:
            row = ctx.conn.execute(
                sql, (ctx.run_id, text) if per_run else (text,)
            ).fetchone()
        except (
            sqlite3.Error
        ):  # the table is not there yet (an older database): nothing is issued from it
            continue
        if row is not None:
            return True
    return False


#: THE CLOSED LIST of reasons a wrong use of the seam names (stored with the role's record; the sheet words each one). Codes only: never a value,
#: never a word of a document.
FAILURE_REASONS = (
    "derived_block_too_large",  # the cells of one derived block are more than MAX_DERIVED_CHARS
    "derived_row_not_a_short_line",  # a cell is empty, has a line break or is longer than MAX_CELL_CHARS
    "derived_block_malformed",  # no name, no sources, no rows, or a document id on a derived block
    "declared_kinds_invalid",  # a declared cell kind that does not exist, or a row with another number of cells than kinds
    "stored_block_malformed",  # a stored-text block without a document or pages, or with derived parts
    "unknown_block_kind",
    "template_unknown",
    "template_parameters_differ",  # a template used with other parameters than it declares
    "template_parameter_not_of_its_kind",
    "other",
)


class NineCallError(ValueError):
    """A wrong use of the seam: a programming error, never a document fact. `reason` is from `FAILURE_REASONS`; `template` is the template or
    derived block NAME (app-owned) and `cell_kind` the declared kind that was refused, so the record can say what failed without a value."""

    reason: str = "other"
    template: str | None = None
    cell_kind: str | None = None

    def __init__(
        self,
        message: str = "",
        *,
        reason: str | None = None,
        template: str | None = None,
        cell_kind: str | None = None,
    ):
        super().__init__(message)
        if reason is not None:
            self.reason = reason if reason in FAILURE_REASONS else "other"
        self.template, self.cell_kind = template, cell_kind


class TemplateError(NineCallError):
    """A template parameter that is not an id, a count, a short token or a role name (`text_not_from_block`)."""

    code = TEXT_NOT_FROM_BLOCK


# --------------------------------------------------------------------------------------------------------- templates

_TEMPLATES: dict[str, tuple[str, dict[str, str]]] = {}
_PLACEHOLDER = re.compile(r"(?<!\{)\{([a-z][a-z0-9_]*)\}(?!\})")


def template(template_id: str, text: str, **params: str) -> str:
    """Register the FIXED words of a question or system prompt. `params` maps each `{name}` placeholder of `text` to its typed kind: `id`
    (an id the app issued), `int`, `role`, `clause`, `number`, `unit`, `standard` or `vocab:<registered vocabulary>`; there is no free-text
    kind. Called by a role module at import with a string literal, before `freeze`: a later call raises (a template is free text that goes
    into every body). The same id with other words is refused. Returns the id."""
    _closed()
    if (
        not isinstance(text, str)
        or not _ID.match(template_id)
        or len(text) > MAX_TEMPLATE_CHARS
    ):
        raise NineCallError(
            "a template has an id of letters and digits and words under 20,000 characters"
        )
    names = set(_PLACEHOLDER.findall(text))
    if names != set(params) or any(
        k not in PARAM_KINDS and not (k.startswith("vocab:") and k[6:] in _VOCAB)
        for k in params.values()
    ):
        raise NineCallError(
            "a template names exactly its parameters, each of a typed kind: "
            + ", ".join(PARAM_KINDS)
            + ", vocab:<registered vocabulary>"
        )
    try:  # a trial render with dummy values of the declared kinds: a stray brace, `{0}` or `{x.attr}` fails here, at import
        text.format(**{k: ("1" if v == "int" else "x") for k, v in params.items()})
    except (KeyError, IndexError, ValueError, AttributeError, TypeError) as exc:
        raise NineCallError(
            f"template {template_id!r} does not render: only plain {{name}} placeholders (a literal brace is doubled)"
        ) from exc
    known = _TEMPLATES.get(template_id)
    if known is not None and known != (text, dict(params)):
        raise NineCallError(f"template {template_id!r} already holds other words")
    _TEMPLATES[template_id] = (text, dict(params))
    return template_id


def _is_standard(text: str) -> bool:
    from . import standard_ids

    found = standard_ids.find_citations(text)
    return (
        len(text) <= nine_record.MAX_TYPED_CELL
        and len(found) == 1
        and found[0][1] <= 1
        and found[0][2] >= len(text.rstrip()) - 1
    )


def _check_param(kind: str, value) -> str:
    if kind == "int":
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 0 <= value <= 10**9
        ):
            raise TemplateError(
                "an int parameter is a count",
                reason="template_parameter_not_of_its_kind",
                cell_kind="int",
            )
        return str(value)
    text = value if isinstance(value, str) else ""
    ok = (
        (kind == "id" and _ID.match(text))
        or (kind == "role" and text in ROLE_NAMES.values())
        or (kind == "clause" and _CLAUSE.match(text))
        or (kind == "number" and _NUMBER.match(text))
        or (kind == "unit" and _is_unit(text))
        or (kind == "standard" and text and _is_standard(text))
        or (kind.startswith("vocab:") and _in_vocabulary(kind, text))
    )
    if not ok:
        raise TemplateError(
            f"a {kind} parameter is not from the app's own words",
            reason="template_parameter_not_of_its_kind",
            cell_kind=kind.split(":")[0],
        )
    return text


def render_full(use: tuple[str, dict]) -> tuple[str, str, str, list[str], list[str]]:
    """(id, the words, the digest of id + parameters, the parameter values as strings, the ids among them) of one template use. Raises `TemplateError` for
    any value that is not of its kind."""
    template_id, params = use
    if template_id not in _TEMPLATES:
        raise TemplateError("an unknown template", reason="template_unknown")
    text, kinds = _TEMPLATES[template_id]
    if set(params) != set(kinds):
        raise TemplateError(
            "a template use gives exactly its parameters",
            reason="template_parameters_differ",
            template=template_id,
        )
    try:
        values = {k: _check_param(kinds[k], params[k]) for k in kinds}
    except TemplateError as exc:
        exc.template = template_id
        raise
    digest = hashlib.sha256(
        json.dumps([template_id, values], sort_keys=True).encode("utf-8")
    ).hexdigest()
    ids = [values[k] for k in kinds if kinds[k] == "id"]
    return template_id, text.format(**values), digest, list(values.values()), ids


def render(use: tuple[str, dict]) -> tuple[str, str, str]:
    """(id, the words, the digest) of one template use."""
    return render_full(use)[:3]


# ------------------------------------------------------------------------------------------------------------ blocks


@dataclass(frozen=True)
class Block:
    """One block of a request. A STORED-TEXT block names where its words are stored (the seam loads them); a picture block names one page;
    a DERIVED block (`review_record`) names its sources and carries rows of short cells, each typed or found in a source (checked at send time). Nothing here is free text."""

    document_kind: str
    document_id: str = (
        ""  # stored-text and picture blocks; derived blocks name `sources` instead
    )
    pages: tuple[int, ...] = ()
    char_from: int | None = (
        None  # offsets into the joined text of `pages` (a chapter part)
    )
    char_to: int | None = None
    picture: bool = False  # one page, rendered by the seam (Claude only)
    chapter_id: str | None = None
    part_no: int | None = None
    part_of: int | None = None
    cache: bool = False
    # derived
    name: str = ""
    sources: tuple[str, ...] = ()
    items: tuple[tuple[str, ...], ...] = ()
    kinds: tuple[
        str, ...
    ] = ()  # optional: the declared kind of each column of `items` (DECLARED_KINDS)

    def __post_init__(self) -> None:
        if self.document_kind in STORED_KINDS:
            if not self.document_id or not self.pages or self.items or self.sources:
                raise NineCallError(
                    "a stored-text block names a document and its pages, and nothing derived",
                    reason="stored_block_malformed",
                )
            if self.picture and len(self.pages) != 1:
                raise NineCallError(
                    "a picture block names one page", reason="stored_block_malformed"
                )
        elif self.document_kind == DERIVED_KIND:
            if (
                not _ID.match(self.name)
                or not self.sources
                or not self.items
                or self.document_id
                or self.picture
            ):
                raise NineCallError(
                    "a derived block has a name, its source documents and rows of tokens",
                    reason="derived_block_malformed",
                    template=self.name if _ID.match(self.name or "") else None,
                )
            for row in self.items:
                if not row or any(
                    not isinstance(c, str) or not _LINE.match(c) for c in row
                ):
                    raise TemplateError(
                        "a derived row holds short one-line cells",
                        reason="derived_row_not_a_short_line",
                        template=self.name,
                    )
            if self.kinds and (
                any(
                    k not in DECLARED_KINDS
                    and not (k.startswith("vocab:") and k[6:] in _VOCAB)
                    for k in self.kinds
                )
                or any(len(row) != len(self.kinds) for row in self.items)
            ):
                raise NineCallError(
                    "declared cell kinds are of "
                    + ", ".join(DECLARED_KINDS)
                    + ", vocab:<registered vocabulary>"
                    + " and every row has one cell per kind",
                    reason="declared_kinds_invalid",
                    template=self.name,
                )
            if sum(len(c) + 3 for row in self.items for c in row) > MAX_DERIVED_CHARS:
                raise TemplateError(
                    "a derived block is a digest, not a copy",
                    reason="derived_block_too_large",
                    template=self.name,
                )
        else:
            raise NineCallError(
                f"unknown block kind {self.document_kind!r}",
                reason="unknown_block_kind",
            )

    def gate_ids(self) -> tuple[str, ...]:
        return (
            tuple(self.sources)
            if self.document_kind == DERIVED_KIND
            else (self.document_id,)
        )


@dataclass(frozen=True)
class RoleGate:
    """A role's design budget. `fits(worst)` is asked before every call; the role's own spend comes from the record."""

    role_no: int
    budget_usd: float

    @classmethod
    def for_role(cls, role_no: int, budget_usd: float | None = None) -> RoleGate:
        return cls(
            role_no,
            ROLE_BUDGET_USD[role_no] if budget_usd is None else float(budget_usd),
        )

    def fits(self, run_id: str, worst_usd: float, conn=None) -> bool:
        return (
            nine_record.role_spend(run_id, self.role_no, conn) + float(worst_usd)
            <= self.budget_usd
        )


@dataclass(frozen=True)
class Answer:
    ok: bool
    call_id: str
    role_no: int
    #: answered | failed | refused (a call that never left, or was stopped by a gate) | reused
    state: str
    error_code: str | None
    text: (
        str | None
    )  # the model's words, for the caller to parse; never stored by this module
    data: dict | None  # the first JSON object in the text, or None
    usd: float | None  # None on the local model and for a call that did not happen
    model: str | None
    engine: str  # derived from the run
    kept: tuple[str, ...]  # document ids whose blocks were sent
    not_sent: tuple[
        tuple[str, str], ...
    ]  # (document id, code): blocks dropped before the request was built
    reads: tuple[ReadEntry, ...] = field(default=())
    #: one entry per read, in the same order: (char_from, char_to) of the stored text actually sent (the slice of a chapter part, or the
    #: whole joined text of the pages: (0, chars)); None for a picture or a derived block
    ranges: tuple[tuple[int, int] | None, ...] = field(default=())


# ------------------------------------------------------------------------------------------------------- the engine


def _decision(run_id: str, conn) -> tuple[str, str | None]:
    """(engine, the starter's user id). DEFAULT DENY: "claude" only when the run's own stored decision says so (a stored choice that does
    not bar Claude, a stored plan with text leaving and a stored shown list) and nothing bars it; "none" when no decision is stored."""
    from . import review_engine, review_shown

    got = review_engine.stored(conn, run_id)
    starter = (got or {}).get("requested_by")
    if review_engine.claude_barred():
        return "local", starter
    job = conn.execute(
        "SELECT id FROM jobs WHERE review_run_id = ? ORDER BY started_at DESC LIMIT 1",
        (run_id,),
    ).fetchone()
    if job is not None and review_engine.bar_state(conn, job["id"])[0]:
        return "local", starter
    if got is None:
        return "none", None
    if got["bar_claude"]:
        return "local", starter
    leaves = (got.get("plan") or {}).get("text_leaves") is True
    if leaves and review_shown.shown_ids(conn, run_id) is not None:
        return "claude", starter
    return "local", starter


def engine_of_run(run_id: str, conn=None) -> str:
    """ "claude" only on an explicit stored decision that says so (see `_decision`); "local" when the run is kept on this computer;
    "none" when no decision is stored for it (a caller then gets `no_engine_decision` unless it asks for the local model)."""
    return _decision(run_id, conn or connect())[0]


# ------------------------------------------------------------------------------------------------------ the gate


def _dropped(
    run_id: str, blocks: list[Block], conn, starter: str | None, engine: str
) -> dict[str, str]:
    """{document id: code} for each document (and each source of a derived block) this run may not use on THIS engine. On every engine:
    outside the starter's access (rule 5: intersection) and, where a shown list is stored, not on it. On Claude also the one gate."""
    from . import review_jobs, review_shown

    allowed = review_jobs._scope_of(starter)
    listed = review_shown.shown_ids(conn, run_id)
    ids = list(dict.fromkeys(i for b in blocks for i in b.gate_ids()))
    out: dict[str, str] = {}
    for doc in ids:
        if doc not in allowed:
            out[doc] = OUTSIDE_ACCESS
        elif engine != "claude" and listed is not None and doc not in listed:
            out[doc] = NOT_ON_LIST
    if engine == "claude":
        for doc, code in nine_record.refused_documents(
            run_id, [i for i in ids if i not in out]
        ).items():
            out[doc] = code
    return out


# ------------------------------------------------------------------------------------------------------- loading


@dataclass(frozen=True)
class Loaded:
    block: Block
    text: str | None = None
    picture: dict | None = None  # {"media_type", "data"}
    cells: tuple[
        nine_record.CellEntry, ...
    ] = ()  # a derived block sent to Claude: how each cell was admitted


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _derived_text(b: Block) -> str:
    return "\n".join(" | ".join(row) for row in b.items)


def _load(
    conn, blocks: list[Block], engine: str
) -> tuple[list[Loaded], dict[str, str]]:
    """Read the words and pictures each block names, from the stored pages. A block whose pages are not stored is dropped and named."""
    from . import agent_review_pages, agent_review_standards

    books: dict[str, object] = {}
    out: list[Loaded] = []
    missing: dict[str, str] = {}
    for b in blocks:
        if b.document_kind == DERIVED_KIND:
            out.append(Loaded(b, text=_derived_text(b)))
            continue
        if b.picture:
            if engine != "claude":
                missing[b.document_id] = "picture_not_read_locally"
                continue
            try:
                ref = agent_review_pages.document_ref(conn, b.document_id)
                png = agent_review_pages.page_image(ref, b.pages[0])
                block = agent_review_pages.image_block({"png": png})
                out.append(
                    Loaded(
                        b,
                        picture={
                            "media_type": block["source"]["media_type"],
                            "data": block["source"]["data"],
                        },
                    )
                )
            except agent_review_pages.PageImageUnavailable as exc:
                missing[b.document_id] = "picture_" + str(exc)
            continue
        book = books.setdefault(
            b.document_id, agent_review_standards.read_book(conn, b.document_id)
        )
        pages = getattr(book, "pages", {})
        if any(p not in pages or not str(pages[p]).strip() for p in b.pages):
            missing[b.document_id] = "no_stored_text"
            continue
        text = "\n".join(pages[p] for p in sorted(b.pages))
        if b.char_from is not None or b.char_to is not None:
            text = text[
                b.char_from or 0 : b.char_to if b.char_to is not None else len(text)
            ]
        if not text.strip():
            missing[b.document_id] = "no_stored_text"
            continue
        out.append(Loaded(b, text=text))
    return out, missing


# ---------------------------------------------------------------------------------------------------- derived cells


def _declared_ok(ctx: IdContext, kind: str, cell: str) -> str | None:
    """The recorded kind when `cell` is a value of its DECLARED kind, else None. `source` is checked elsewhere (it must occur in a source)."""
    text = cell.strip()
    if kind == "id":
        return "id" if _ID.match(text) and _app_id(ctx, text) else None
    if kind == "number":
        return "number" if _NUMBER.match(text) else None
    if kind == "clause":
        return "clause" if _CLAUSE.match(text) else None
    if kind == "unit":
        return "unit" if _is_unit(text) else None
    if kind == "enum":
        return "enum" if fold(text) in DERIVED_ENUM else None
    if kind == "standard":
        return "standard" if _is_standard(text) else None
    if kind.startswith("vocab:"):
        return "vocab" if _in_vocabulary(kind, text) else None
    return None


def _typed_kind(ctx: IdContext, cell: str) -> str | None:
    """The kind of an UNDECLARED cell that is a typed value (never prose), or None. A plain word is not a code."""
    text = cell.strip()
    if _NUMBER.match(text):
        return "number"
    if _CLAUSE.match(text):
        return "clause"
    if fold(text) in DERIVED_ENUM:
        return "enum"
    if _is_standard(text):
        return "standard"
    if _is_unit(text):
        return "unit"
    if _ID.match(text) and _app_id(ctx, text):
        return "id"
    return None


def fold(text: str) -> str:
    return nine_record.fold(text)


def _source_pages(conn, doc: str, cache: dict) -> dict[int, str]:
    """The folded text of each page of a source document: the SAME words a stored block of that document would send (`read_book`: the stored page
    text, and for a page with none the recognised text of its picture). A scanned book has no stored text at all, so reading the `pages` table
    alone refused every cell that was copied from it (found on the first real run). The text is still only that document's own, and only when
    it is a declared and gated source."""
    if doc not in cache:
        from . import agent_review_standards

        try:
            pages = dict(agent_review_standards.read_book(conn, doc).pages)
        except Exception:  # noqa: BLE001 - a document the reader cannot open falls back to the stored page text alone
            pages = {}
        if not any(str(t).strip() for t in pages.values()):
            pages = {
                r["page_no"]: r["text"]
                for r in conn.execute(
                    "SELECT page_no, text FROM pages WHERE document_id = ? ORDER BY page_no",
                    (doc,),
                )
            }
        cache[doc] = {n: fold(t) for n, t in sorted(pages.items())}
    return cache[doc]


def _verify_derived(
    conn, run_id: str, b: Block, chapters: frozenset[str] = frozenset()
) -> tuple[tuple[nine_record.CellEntry, ...], str | None]:
    """Admit each cell of a derived block or name why not: (the cell rows, None) or ((), the code that drops the whole block).
    1. a cell of 12 or more characters that occurs in the stored text of a document the gate refuses in this run: `text_from_held_document`
       (whatever the sources say);
    2. else the cell is a typed token (`_typed_kind`);
    3. else it must occur in the stored text of one of the block's OWN sources: the first source and page that hold it are recorded;
    4. else `cell_not_from_sources`."""
    ctx = IdContext(conn, run_id, chapters)
    flat = [c for row in b.items for c in row]
    probes = set(
        flat
    )  # every cell, every row joined, every window of three consecutive cells (across rows)
    probes |= {" ".join(row) for row in b.items}
    probes |= {" ".join(flat[i : i + 3]) for i in range(max(0, len(flat) - 2))}
    if nine_record.held_text_hits(conn, run_id, probes):
        return (), HELD_TEXT
    cache: dict = {}
    out: list[nine_record.CellEntry] = []
    for r, row in enumerate(b.items):
        for c, cell in enumerate(row):
            probe = fold(cell)
            sha = _sha(probe)
            declared = b.kinds[c] if b.kinds else None
            if declared is None or declared == "source":
                kind = (
                    _typed_kind(ctx, cell)
                    if declared is None and len(cell) <= nine_record.MAX_TYPED_CELL
                    else None
                )
            else:  # declared typed: it must be a value of that kind, or the block is dropped (never read as prose)
                kind = (
                    _declared_ok(ctx, declared, cell)
                    if len(cell) <= nine_record.MAX_TYPED_CELL
                    else None
                )
                if kind is None:
                    return (), (
                        CELL_NOT_IN_VOCAB
                        if declared.startswith("vocab:")
                        else CELL_WRONG_KIND
                    )
            if kind is not None:
                out.append(nine_record.CellEntry(b.name, r, c, kind, len(cell), sha))
                continue
            found = None
            for doc in b.sources:
                for page, text in _source_pages(conn, doc, cache).items():
                    at = text.find(probe) if probe else -1
                    if at >= 0:
                        found = (doc, page, at)
                        break
                if found:
                    break
            if (
                found is None
            ):  # one plain token is a word that is not a code; a longer cell is text that is not in a source
                return (), (
                    CELL_NOT_IN_VOCAB
                    if len(probe.split()) == 1
                    else CELL_NOT_FROM_SOURCES
                )
            out.append(
                nine_record.CellEntry(
                    b.name,
                    r,
                    c,
                    "source",
                    len(cell),
                    sha,
                    found[0],
                    found[1],
                    found[2],
                    len(probe),
                )
            )
    return tuple(out), None


# ------------------------------------------------------------------------------------------------------- the request


def _label(n: int, b: Block) -> str:
    """Words from the block's own metadata (never a file name or a title): which kind of document, which pages."""
    if b.document_kind == DERIVED_KIND:
        return f"[derived block {n}: {b.name}]"
    pages = ""
    if b.pages:
        pages = (
            f", page {b.pages[0]}"
            if len(b.pages) == 1
            else f", pages {b.pages[0]} to {b.pages[-1]}"
        )
    chap = f", chapter {b.chapter_id}" if b.chapter_id else ""
    part = f", part {b.part_no} of {b.part_of}" if b.part_no and b.part_of else ""
    return (
        f"[document block {n}: {b.document_kind.replace('_', ' ')}{pages}{chap}{part}]"
    )


def _content(loaded: list[Loaded], question: str) -> list[dict]:
    """The message content, serialised FROM the loaded blocks, in order, then the question. One function: a block cannot enter a request
    without being in `loaded`, and the read rows are derived from the same list."""
    out: list[dict] = []
    for n, item in enumerate(loaded, 1):
        out.append({"type": "text", "text": _label(n, item.block)})
        if item.text is not None:
            block: dict = {"type": "text", "text": item.text}
            if item.block.cache:
                block["cache_control"] = dict(agent_claude._CACHE)
            out.append(block)
        if item.picture is not None:
            out.append({"type": "image", "source": {"type": "base64", **item.picture}})
    out.append({"type": "text", "text": question})
    return out


def _reads(role_no: int, call_id: str, loaded: list[Loaded]) -> list[ReadEntry]:
    rows: list[ReadEntry] = []
    for item in loaded:
        b = item.block
        text = item.text or ""
        common = dict(
            role_no=role_no,
            call_id=call_id,
            chars=len(text),
            text_sha256=_sha(text),
            pictures=1 if item.picture else 0,
        )
        if (
            b.document_kind == DERIVED_KIND
        ):  # one row per source: the gate and the checker see every document the words came from
            rows += [
                ReadEntry(
                    document_id=s,
                    document_kind=DERIVED_KIND,
                    pages=(),
                    chapter_id=b.name,
                    part_no=None,
                    part_of=None,
                    **common,
                )  # type: ignore[arg-type]
                for s in b.sources
            ]
        else:
            rows.append(
                ReadEntry(
                    document_id=b.document_id,
                    document_kind=b.document_kind,
                    pages=tuple(b.pages),
                    chapter_id=b.chapter_id,  # type: ignore[arg-type]
                    part_no=b.part_no,
                    part_of=b.part_of,
                    **common,
                )
            )
    return rows


def _ranges(loaded: list[Loaded]) -> list[tuple[int, int] | None]:
    """One entry per row of `_reads`: the character range of the stored text actually sent (a slice starts at its `char_from`)."""
    out: list[tuple[int, int] | None] = []
    for item in loaded:
        b = item.block
        if b.document_kind == DERIVED_KIND:
            out += [None] * len(b.sources)
        elif item.text is None:
            out.append(None)
        else:
            start = b.char_from or 0
            out.append((start, start + len(item.text)))
    return out


def _json_of(text: str) -> dict | None:
    return agent_claude.parse_json_object(text)


# --------------------------------------------------------------------------------------------------------------- ask


def ask(
    run_id: str,
    role_no: int,
    blocks: list[Block],
    question: tuple[str, dict],
    *,
    system: tuple[str, dict] | None = None,
    engine: str | None = None,
    model: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    send: Callable | None = None,
    local_send: Callable[[dict], dict] | None = None,
    env: dict | None = None,
    meter: agent_claude.SpendMeter | None = None,
    gate: RoleGate | None = None,
    call_id: str | None = None,
    should_stop: Callable[[], bool] | None = None,
    conn=None,
) -> Answer:
    """Make ONE model call of a nine-role request and record it. `should_stop` (a cancel check) is asked right before the reservation or the
    send: when it returns true nothing is sent and the answer is `refused` / `cancelled` (no body, no ledger line, no read rows). `engine` is DERIVED from the run; a caller may ask for "local" but never
    for Claude over a Local run. Never raises for a refusal or a failed call: the answer says which (`state`, `error_code`) and what was
    left out (`not_sent`); a wrong use (including a text that is not from a template or a block) raises `NineCallError`."""
    conn = conn or connect()
    if role_no not in ROLE_NAMES:
        raise NineCallError(f"no role {role_no!r}")
    if role_no not in STEP_OF_ROLE:
        raise NineCallError(f"role {role_no} is code: it makes no model call")
    if not blocks:
        raise NineCallError("a request holds at least one block")
    question_id, question_text, q_digest, q_values, q_ids = render_full(question)
    system_id, system_text, s_digest, s_values, s_ids = (
        render_full(system) if system else (None, None, "", [], [])
    )
    params_sha = _sha(q_digest + s_digest)
    nine_record.ensure_schema(conn)
    step = STEP_OF_ROLE[role_no]
    derived, starter = _decision(run_id, conn)
    wanted = engine or ("local" if derived == "none" else derived)
    if wanted not in ("claude", "local"):
        raise NineCallError("a model call is on Claude or on the local model")
    call_id = call_id or uuid.uuid4().hex[:16]
    model = (
        model
        or DEFAULT_MODEL.get(role_no)
        or (agent_claude.LEAD_MODEL if wanted == "claude" else _local_model())
    )
    gate = gate or RoleGate.for_role(role_no)

    def refused(code: str, kept=(), dropped=()) -> Answer:
        nine_record.call_refused(
            run_id,
            role_no,
            call_id,
            step=step,
            engine=wanted,
            model=model,
            error_code=code,
            conn=conn,
        )
        return Answer(
            False,
            call_id,
            role_no,
            "refused",
            code,
            None,
            None,
            None,
            model,
            wanted,
            kept,
            tuple(dropped),
        )

    if derived == "none" and engine is None:
        return refused(NO_DECISION)  # no stored decision: default deny
    if wanted == "claude" and derived != "claude":
        return refused(
            NO_DECISION if derived == "none" else "run_is_local"
        )  # a caller cannot choose Claude: only the run's stored decision can
    if wanted == "claude" and nine_record.held_text_hits(
        conn, run_id, [*q_values, *s_values]
    ):
        return refused(
            HELD_TEXT
        )  # a parameter holds words of a document the gate refuses
    ctx = IdContext(
        conn,
        run_id,
        frozenset(b.chapter_id for b in blocks if getattr(b, "chapter_id", None)),
    )
    if any(not _app_id(ctx, i) for i in [*q_ids, *s_ids]):
        return refused(
            PARAM_NOT_APP_ID
        )  # an id parameter is an id the app issues, never a word

    not_sent: dict[str, str] = _dropped(run_id, blocks, conn, starter, wanted)
    gated = [b for b in blocks if not any(i in not_sent for i in b.gate_ids())]
    loaded, missing = _load(conn, gated, wanted)
    not_sent.update(missing)
    cells: list[nine_record.CellEntry] = []
    if wanted == "claude":
        checked: list[Loaded] = []
        for item in loaded:
            if item.block.document_kind != DERIVED_KIND:
                checked.append(item)
                continue
            got, why = _verify_derived(conn, run_id, item.block, ctx.chapters)
            if why:
                not_sent["derived:" + item.block.name] = why
                continue
            cells += got
            checked.append(Loaded(item.block, text=item.text, cells=got))
        loaded = checked
    dropped = tuple(sorted(not_sent.items()))
    if not loaded:
        return refused("no_block_left", dropped=dropped)

    content = _content(loaded, question_text)
    reads = _reads(role_no, call_id, loaded)
    kept_ids = tuple(dict.fromkeys(i for item in loaded for i in item.block.gate_ids()))
    parts: dict = {"messages": [{"role": "user", "content": content}]}
    if system_text:
        parts["system"] = [
            {
                "type": "text",
                "text": system_text,
                "cache_control": dict(agent_claude._CACHE),
            }
        ]
    meta = dict(
        question_id=question_id,
        system_id=system_id,
        params_sha256=params_sha,
        ranges=tuple(_ranges(loaded)),
    )
    if should_stop is not None and should_stop():
        return refused(
            "cancelled", kept_ids, dropped
        )  # a cancel stops the call before the reservation and the send
    if wanted == "claude":
        meta["cells"] = tuple(cells)
        return _ask_claude(
            run_id,
            role_no,
            call_id,
            step,
            model,
            max_tokens,
            parts,
            reads,
            kept_ids,
            dropped,
            send,
            env,
            meter,
            gate,
            conn,
            meta,
        )
    return _ask_local(
        run_id,
        role_no,
        call_id,
        step,
        model,
        max_tokens,
        parts,
        reads,
        kept_ids,
        dropped,
        local_send,
        conn,
        meta,
    )


def _ask_claude(
    run_id,
    role_no,
    call_id,
    step,
    model,
    max_tokens,
    parts,
    reads,
    kept_ids,
    dropped,
    send,
    env,
    meter,
    gate,
    conn,
    meta,
) -> Answer:
    chars, images = json_counts(parts.get(k) for k in ("messages", "system"))
    worst = claude_spend.worst_case_usd(
        model, chars, int(max_tokens), image_tokens=images
    )
    if not gate.fits(run_id, worst, conn):
        nine_record.call_refused(
            run_id,
            role_no,
            call_id,
            step=step,
            engine="claude",
            model=model,
            error_code="role_budget",
            conn=conn,
        )
        return Answer(
            False,
            call_id,
            role_no,
            "refused",
            "role_budget",
            None,
            None,
            None,
            model,
            "claude",
            kept_ids,
            dropped,
        )
    written = {"sent": False}
    try:
        raw = agent_claude._transport(send)
    except agent_claude.AgentGateClosed as exc:
        nine_record.call_refused(
            run_id,
            role_no,
            call_id,
            step=step,
            engine="claude",
            model=model,
            error_code=exc.code,
            conn=conn,
        )
        return Answer(
            False,
            call_id,
            role_no,
            "refused",
            exc.code,
            None,
            None,
            None,
            model,
            "claude",
            kept_ids,
            dropped,
        )

    def wrapped(url, *, headers, body, timeout):
        # reached only AFTER the spend reservation succeeded (claude_spend.metered reserves first): the rows are written now, from the
        # blocks, with the digest of the finished body, just before it leaves
        nine_record.call_sent(
            run_id,
            role_no,
            call_id,
            step=step,
            engine="claude",
            model=model,
            request_sha256=agent_claude.request_digest(body),
            reads=reads,
            conn=conn,
            **meta,
        )
        written["sent"] = True
        return raw(url, headers=headers, body=body, timeout=timeout)

    try:
        with (
            claude_approved.carrying(kept_ids),
            claude_approved.reviewing(run_id),
            claude_spend.for_run(run_id),
        ):
            answer, usd = agent_claude._call(
                model, parts, max_tokens, wrapped, env, meter, step=step
            )
    except agent_claude.AgentBadReply as exc:
        return _finish(
            run_id,
            role_no,
            call_id,
            conn,
            written,
            "failed",
            exc.code,
            getattr(exc, "usd", None),
            worst,
            model,
            kept_ids,
            dropped,
            reads,
            step,
            meta,
        )
    except (agent_claude.AgentBudgetStop, agent_claude.AgentGateClosed) as exc:
        return _finish(
            run_id,
            role_no,
            call_id,
            conn,
            written,
            "refused",
            exc.code,
            None,
            None,
            model,
            kept_ids,
            dropped,
            reads,
            step,
            meta,
        )
    except agent_claude.AgentTransportError as exc:
        return _finish(
            run_id,
            role_no,
            call_id,
            conn,
            written,
            "failed",
            exc.code,
            None,
            worst,
            model,
            kept_ids,
            dropped,
            reads,
            step,
            meta,
        )
    text = "".join(
        str(b.get("text") or "")
        for b in answer.get("content") or []
        if isinstance(b, dict) and b.get("type") == "text"
    )
    return _finish(
        run_id,
        role_no,
        call_id,
        conn,
        written,
        "answered",
        None,
        usd,
        None,
        agent_claude._answered_model(answer),
        kept_ids,
        dropped,
        reads,
        step,
        meta,
        text=text,
    )


def _ask_local(
    run_id,
    role_no,
    call_id,
    step,
    model,
    max_tokens,
    parts,
    reads,
    kept_ids,
    dropped,
    local_send,
    conn,
    meta,
) -> Answer:
    digest = _sha(json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str))
    nine_record.call_sent(
        run_id,
        role_no,
        call_id,
        step=step,
        engine="local",
        model=model,
        request_sha256=digest,
        reads=reads,
        conn=conn,
        **meta,
    )
    sender = local_send or _ollama_send
    try:
        got = sender({"model": model, "max_tokens": int(max_tokens), **parts})
    except Exception as exc:  # noqa: BLE001 - a code only: the text of an error may carry document words
        log.warning("nine local call failed (%s)", type(exc).__name__)
        return _finish(
            run_id,
            role_no,
            call_id,
            conn,
            {"sent": True},
            "failed",
            "local_" + type(exc).__name__,
            None,
            None,
            model,
            kept_ids,
            dropped,
            reads,
            step,
            meta,
            engine="local",
        )
    text = str((got or {}).get("text") or "")
    return _finish(
        run_id,
        role_no,
        call_id,
        conn,
        {"sent": True},
        "answered",
        None,
        None,
        None,
        str((got or {}).get("model") or model),
        kept_ids,
        dropped,
        reads,
        step,
        meta,
        text=text,
        engine="local",
    )


def _finish(
    run_id,
    role_no,
    call_id,
    conn,
    written,
    state,
    code,
    usd,
    reserved,
    model,
    kept_ids,
    dropped,
    reads,
    step,
    meta,
    *,
    text=None,
    engine="claude",
) -> Answer:
    ok = state == "answered"
    if written["sent"]:
        nine_record.call_end(
            run_id,
            call_id,
            state,
            error_code=code,
            usd=usd,
            usd_reserved=reserved if usd is None else None,
            model=model if ok else None,
            conn=conn,
        )
    else:  # it never reached the transport (the reservation or a gate refused it): a refused call with no read rows
        nine_record.call_refused(
            run_id,
            role_no,
            call_id,
            step=step,
            engine=engine,
            model=model,
            error_code=code or state,
            conn=conn,
        )
        state = "refused"
    return Answer(
        ok,
        call_id,
        role_no,
        state,
        code,
        text if ok else None,
        _json_of(text or "") if ok else None,
        usd,
        model,
        engine,
        kept_ids,
        dropped,
        tuple(reads) if written["sent"] else (),
        tuple(meta.get("ranges") or ()) if written["sent"] else (),
    )


def _local_model() -> str:
    from . import agent_local_lead

    return agent_local_lead.DEFAULT_MODEL


def _ollama_send(parts: dict) -> dict:
    """The local lane: the ONE local socket, `model_transport`. The system words and the user content are plain text (no pictures)."""
    from . import model_transport

    system = "".join(str(s.get("text") or "") for s in parts.get("system") or [])
    user = "\n\n".join(
        str(c.get("text") or "")
        for m in parts["messages"]
        for c in m["content"]
        if isinstance(c, dict) and c.get("type") == "text"
    )
    body = {
        "model": parts["model"],
        "stream": False,
        "think": False,
        "options": {"temperature": 0, "num_predict": int(parts["max_tokens"])},
        "messages": ([{"role": "system", "content": system}] if system else [])
        + [{"role": "user", "content": user}],
    }
    answer = model_transport.post_json_retrying("/api/chat", body, timeout=300.0)
    msg = answer.get("message") if isinstance(answer, dict) else None
    return {
        "text": (msg or {}).get("content") or "",
        "model": (answer or {}).get("model") or parts["model"],
    }


def record_reused(
    run_id: str,
    role_no: int,
    blocks: list[Block],
    request_sha256: str,
    *,
    engine: str = "claude",
    model: str | None = None,
    conn=None,
) -> str:
    """A role that finds a stored answer of the SAME request (a restart) does not call again: it records the call as `reused` (the
    request digest and the blocks it read, no cost, no ledger line) and returns the call id. Never paid twice."""
    conn = conn or connect()
    if role_no not in STEP_OF_ROLE:
        raise NineCallError(f"role {role_no} is code: it makes no model call")
    call_id = uuid.uuid4().hex[:16]
    loaded, _missing = _load(conn, list(blocks), engine)
    nine_record.call_sent(
        run_id,
        role_no,
        call_id,
        step=STEP_OF_ROLE[role_no],
        engine=engine,
        model=model or agent_claude.LEAD_MODEL,
        request_sha256=request_sha256,
        reads=_reads(role_no, call_id, loaded),
        ranges=_ranges(loaded),
        conn=conn,
    )
    nine_record.call_end(run_id, call_id, "reused", usd=None, conn=conn)
    return call_id


# ------------------------------------------------------------------------------------------------------ for the tests


class FakeTransport:
    """A Messages transport that answers from a queue and keeps the bodies it was handed (tests only: no network, no key).
    `answers` are strings (the model's words) or dicts (the whole reply). `ENV` opens the lane for it."""

    ENV = {
        "REASONING_PROVIDER": "claude",
        "AGENT_REVIEW_ENGINE": "claude",
        "STANDARDS_READER_ENABLED": "1",
        "STANDARDS_READER_ALLOW_PUBLIC_EGRESS": "1",
        "ANTHROPIC_API_KEY": "test-key-not-real",
    }
    USAGE = {
        "input_tokens": 1000,
        "output_tokens": 100,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }

    def __init__(
        self,
        answers=("{}",),
        usage: dict | None = None,
        raises: Exception | None = None,
    ) -> None:
        self.answers = list(answers)
        self.usage = dict(usage or self.USAGE)
        self.raises = raises
        self.bodies: list[dict] = []

    def __call__(self, url, *, headers, body, timeout):  # noqa: ARG002
        self.bodies.append(json.loads(json.dumps(body, default=str)))
        if self.raises is not None:
            raise self.raises
        item = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(item, dict):
            return item
        return {
            "model": body["model"],
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": str(item)}],
            "usage": dict(self.usage),
        }
