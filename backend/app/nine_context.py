"""Role 2 of the nine-role reviewer: the project context (B3).

Code finds the project's papers and decides which may be read (the shown list, the starter's access, the engine choice, the
register, a contract). A model reads each allowed paper in windows and may only NAME a standard or a project override with a page
quote. Code finds the quote on that page of that paper; a name or override whose quote is not found is dropped and counted.
The note always says what was not available, filled by code, never by the model.

No model is called directly: `seam_ask` builds the one adapter over B1's seam (`nine_call.ask`): a project paper goes as a stored-text
Block (kind, document id, pages, NO text; the seam loads and gates it per document) and the question is a registered template. The
note's parts go on as per-source derived blocks of short tokens (`context_blocks`), never a sentence of a document. A failed call
leaves what code found. No database, no network, no document names in this file.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from . import agent_general_review, applicability, nine_call, rule_labels
from .nine_contract import (
    ContextNote,
    EarlierComment,
    EarlierRevision,
    NotAvailable,
    Override,
    SourceQuote,
    StandardNamed,
)

log = logging.getLogger(__name__)


# The five things a note says about, in this order.
WHATS = (
    "contract",
    "project specification",
    "related papers",
    "earlier revision",
    "earlier comments",
)
KIND_CONTRACT = "contract"
KIND_SPEC = "project specification"
KIND_RELATED = "related papers"
LOCAL_WINDOW_TOKENS = 2_600  # the general review's local window
CLAUDE_WINDOW_TOKENS = 30_000
MAX_NAMED = 40  # standards and overrides kept per paper; the rest is counted

WHY_NONE_HELD = "none held for this project"
WHY_NOT_SHOWN = "held, not on the list shown before the start"
WHY_NO_ACCESS = "held, outside the access of the user who started the review"
WHY_AUTOMATIC = "goes to Claude only when you choose Claude"
WHY_NO_TEXT = "held, no stored text"
WHY_UNSCORED = "a kind of paper not scored against an answer key goes to Claude only when you choose Claude"
WHY_NO_REVISION = "no earlier revision of this paper is held"
WHY_NO_COMMENTS = "the earlier revision has no stored comments"
WHY_NOT_READ = "no project paper was read, so no comment could be followed"


@dataclass(frozen=True)
class ProjectPaper:
    """One candidate, as the job found it (ids, never names). `kind` is one of KIND_*. `register` is the client's register:
    it is never listed, never read."""

    document_id: str
    kind: str
    pages: Mapping[int, str]
    shown: bool
    accessible: bool
    register: bool = False
    scored: bool = True  # the paper's kind is scored against an answer key (`kind_review_table.scored`)
    earlier: bool = (
        False  # the revision this paper replaced (its block kind is earlier_revision)
    )


@dataclass(frozen=True)
class Admission:
    readable: tuple[ProjectPaper, ...]
    not_available: tuple[NotAvailable, ...]
    counts: Mapping[
        str, int
    ]  # reason words -> how many papers (counts only; never names)


def admit(papers: Iterable[ProjectPaper], *, engine: str) -> Admission:
    """Which candidates may be read now. `engine` is "automatic", "claude" or "local". A contract is read only when the user
    chose Claude (the explicit button) or Local (nothing leaves); Automatic never sends one. The register is never listed:
    it is dropped without a line. A paper outside the starter's access is counted, never named."""
    readable: list[ProjectPaper] = []
    reasons: dict[str, list[str]] = {}
    counts: dict[str, int] = {}
    for p in papers:
        if p.register:
            continue
        why = None
        if not p.accessible:
            why = WHY_NO_ACCESS
        elif not p.shown:
            why = WHY_NOT_SHOWN
        elif p.kind == KIND_CONTRACT and engine == "automatic":
            why = WHY_AUTOMATIC
        elif p.kind == KIND_RELATED and not p.scored and engine == "automatic":
            why = WHY_UNSCORED
        elif not any((t or "").strip() for t in p.pages.values()):
            why = WHY_NO_TEXT
        if why is None:
            readable.append(p)
            continue
        reasons.setdefault(p.kind, []).append(why)
        counts[why] = counts.get(why, 0) + 1
    lines = []
    for what in (KIND_CONTRACT, KIND_SPEC, KIND_RELATED):
        if any(p.kind == what for p in readable):
            continue
        why_list = reasons.get(what)
        lines.append(NotAvailable(what, why_list[0] if why_list else WHY_NONE_HELD))
    return Admission(tuple(readable), tuple(lines), counts)


# ---------------------------------------------------------------- the earlier revision, by code


def earlier_revision(paper: Mapping, rows: Iterable[Mapping]) -> Mapping | None:
    """The row of the revision this paper replaced: a row whose `superseded_by` is this paper; else, when the paper has a
    document number and a project, the one row with the same number and project and another revision that is not newer by
    its own `superseded_by`. Several equal candidates: none (code does not guess)."""
    pid = paper.get("document_id")
    direct = [
        r for r in rows if r.get("superseded_by") == pid and r.get("document_id") != pid
    ]
    if len(direct) == 1:
        return direct[0]
    if direct:
        return None
    number, project, rev = (
        paper.get("document_number"),
        paper.get("project"),
        paper.get("revision"),
    )
    if not number or not project:
        return None
    same = [
        r
        for r in rows
        if r.get("document_id") != pid
        and r.get("document_number") == number
        and r.get("project") == project
        and r.get("revision") != rev
        and not r.get("superseded_by")
    ]
    return same[0] if len(same) == 1 else None


def _norm(v: object) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip().casefold()


def follow_up(
    earlier_points: Iterable[Mapping], new_values: Mapping[str, object]
) -> tuple[EarlierComment, ...]:
    """Earlier comments followed by code: the same field in the new fact sheet. `still_open` is True when the value is the
    same as the one the comment was about, False when it changed, None when the field is not in the new sheet or the earlier
    point recorded no value. The stored word and the engineer's decision are copied unchanged."""
    out = []
    for pt in earlier_points:
        fld = pt.get("field")
        old = pt.get("value")
        still: bool | None = None
        if fld and fld in new_values and old not in (None, ""):
            still = _norm(new_values[fld]) == _norm(old)
        out.append(
            EarlierComment(
                point_id=str(pt.get("point_id")),
                field=fld,
                status_word=str(pt.get("status_word") or ""),
                engineer_decision=pt.get("engineer_decision"),
                still_open=still,
            )
        )
    return tuple(out)


# ---------------------------------------------------------------- the model's names, checked by code


def quote_found(pages: Mapping[int, str], page: int, quote: str) -> bool:
    """The quote is on THAT page of that paper (whitespace and case ignored). An empty or one-word quote is not a quote."""
    q = _norm(quote)
    if len(q.split()) < 3:
        return False
    return q in _norm(pages.get(page, ""))


def windows(pages: Mapping[int, str], *, engine: str) -> list[list[int]]:
    limit = LOCAL_WINDOW_TOKENS if engine == "local" else CLAUDE_WINDOW_TOKENS
    return agent_general_review.window_pages(pages, limit)


Ask = Callable[["ProjectPaper", Sequence[int]], Mapping | None]
"""`ask(paper, pages) -> {"standards": [{name, page, quote}], "overrides": [{subject, general_ref, page, quote, precedence}]}` or
None. The adapter sends NO text: only (kind, document id, pages) as a Block; `seam_ask` is the one adapter."""

#: the app-owned vocabularies of the derived blocks of this role (registered once, at import)
FIELDS_VOCAB = nine_call.vocabulary(
    "ctx_fields", rule_labels.field_list()
)  # all of them: each is an app key
CODES_VOCAB = nine_call.vocabulary(
    "ctx_codes",
    (
        "held", "not_held", "related", "project_over_general", "not_stated", "still_open", "changed", "cannot_tell",
        "none", "keep", "edit", "remove", "pass", "fail", "met", "not_met", "partly", "unknown", "query",
    ),
)  # fmt: skip
KEY_KIND, CODE_KIND = f"vocab:{FIELDS_VOCAB}", f"vocab:{CODES_VOCAB}"

QUESTION_ID = nine_call.template(
    "nine_context_read",
    "Read the project document in the block. Name the standards it says apply to the equipment under review, and any project rule "
    "that replaces or tightens a general one, with the order of precedence when it states one. Answer with JSON only: "
    '{{"standards": [{{"name": "", "page": 0, "quote": ""}}], "overrides": [{{"subject": "", "general_ref": "", "page": 0, '
    '"quote": "", "precedence": ""}}]}}. A quote is copied exactly from that page; page is the page number shown for it. '
    "Name nothing the document does not say.",
)
QUESTION_ID_STATEMENTS = nine_call.template(
    "nine_context_read_statements",
    "Read the project document in the block. Name the standards it says apply to the paper under review, and any project rule "
    "that replaces or tightens a general one, with the order of precedence when it states one. Answer with JSON only: "
    '{{"standards": [{{"name": "", "page": 0, "quote": ""}}], "overrides": [{{"subject": "", "general_ref": "", "page": 0, '
    '"quote": "", "precedence": ""}}]}}. A quote is copied exactly from that page; page is the page number shown for it. '
    "Name nothing the document does not say.",
)
#: wording (`kind_review_table.wording`) -> the registered question: a closed set
QUESTION_OF = {"fields": QUESTION_ID, "statements": QUESTION_ID_STATEMENTS}


def seam_ask(run_id: str, *, engine: str | None = None, wording: str = "fields", **seam) -> Ask:
    """The adapter the job gives `read_papers`: ONE call of role 2 through `nine_call.ask`, the paper as a block by reference.
    `seam` passes `send`, `env`, `gate`, `conn` ... to the seam (tests give a FakeTransport). A refused or failed call: None."""

    def ask(paper: ProjectPaper, pages: Sequence[int]) -> Mapping | None:
        kind = "earlier_revision" if paper.earlier else "project_document"
        block = nine_call.Block(kind, paper.document_id, tuple(pages))
        got = nine_call.ask(
            run_id, 2, [block], (QUESTION_OF[wording], {}), engine=engine, **seam
        )
        return got.data if got.ok else None

    return ask


@dataclass
class Tally:
    read: list[str] = field(default_factory=list)
    windows: int = 0
    failed_windows: int = 0
    standards_dropped: int = 0
    overrides_dropped: int = 0
    unheld_standards: int = 0
    standards_unrecognised: int = 0  # named with a true whole-token citation, of a family the app's reader does not know
    parts_not_passed: int = (
        0  # rows left out of the blocks for the reviewer: not provable by code
    )


def read_papers(
    papers: Sequence[ProjectPaper],
    ask: Ask | None,
    library: list[dict],
    *,
    engine: str,
) -> tuple[tuple[StandardNamed, ...], tuple[Override, ...], Tally]:
    """Read each readable paper in windows. Keep a name only with a verified quote; resolve it to a held book through
    `applicability.find_standard` (the one lookup). Names repeated across windows are kept once."""
    tally = Tally()
    standards: dict[tuple[str, str], StandardNamed] = {}
    overrides: dict[tuple[str, str], Override] = {}
    if ask is None:
        return (), (), tally
    for p in papers:
        tally.read.append(p.document_id)
        for win in windows(p.pages, engine=engine):
            tally.windows += 1
            try:
                got = ask(p, win)
            except Exception as exc:  # noqa: BLE001 - a failed window leaves what code found
                log.warning("project context window failed: %s", type(exc).__name__)
                got = None
            if not got:
                tally.failed_windows += 1
                continue
            for raw in got.get("standards") or ():
                _keep_standard(raw, p, library, standards, tally)
            for raw in got.get("overrides") or ():
                _keep_override(raw, p, overrides, tally)
    return (
        tuple(standards.values())[:MAX_NAMED],
        tuple(overrides.values())[:MAX_NAMED],
        tally,
    )


def _quote(raw: Mapping, p: ProjectPaper) -> SourceQuote | None:
    try:
        page = int(raw.get("page"))
    except (TypeError, ValueError):
        return None
    text = str(raw.get("quote") or "")
    if not quote_found(p.pages, page, text):
        return None
    return SourceQuote(
        document_id=p.document_id, page=page, quote=text.strip(), verified=True
    )


def _matched_citation(name: str, quote: str) -> str | None:
    """The citation, as printed in the quote, that the app's own identifier reader (`standard_ids.cited_standards`, whole tokens of
    the raw quote) finds and that is `same_standard` as the name; None when the quote does not cite it. A bare letter group or number
    inside another word ("API" in "rapid", "610" in "1610") is not a citation."""
    from . import standard_ids

    return next(
        (
            c
            for c in standard_ids.cited_standards(quote)
            if standard_ids.same_standard(name, c)
        ),
        None,
    )


def _printed_whole(name: str, quote: str) -> bool:
    """An identifier-like name (letters AND digits) printed in the quote as whole tokens, in order, though the app's reader does not
    know its family: said apart from a dropped name ("not recognised by the app's reader"), never silent."""
    if not (re.search(r"[A-Za-z]", name) and re.search(r"\d", name)):
        return False
    toks = re.findall(r"[A-Za-z0-9]+", name)
    pat = (
        r"(?<![A-Za-z0-9])"
        + r"[^A-Za-z0-9]{0,3}".join(re.escape(t) for t in toks)
        + r"(?![A-Za-z0-9])"
    )
    return bool(re.search(pat, quote, re.I))


_CLAUSE_NUMBER = re.compile(r"(?<![0-9A-Za-z.])\d+(?:\.\d+)+(?![0-9A-Za-z])")


def _field_anchor(subject: str, quote: str) -> str | None:
    """The app's field-list name (`rule_labels.field_list`, e.g. design_pressure) that stands in BOTH the subject and the quote."""
    from . import rule_labels

    def flat(t):
        return " " + " ".join(re.findall(r"[a-z0-9]+", t.casefold())) + " "

    s_, q_ = flat(subject), flat(quote)
    for role in rule_labels.field_list():
        phrase = " " + role.replace("_", " ") + " "
        if phrase in s_ and phrase in q_:
            return role
    return None


def _standard_anchor(general_ref: str | None, quote: str) -> str | None:
    """The citation in the quote that is the standard being overridden: the one the override's own general reference names."""
    from . import standard_ids

    refs = standard_ids.cited_standards(general_ref or "")
    return next(
        (
            c
            for c in standard_ids.cited_standards(quote)
            if any(standard_ids.same_standard(r, c) for r in refs)
        ),
        None,
    )


def _subject_in_quote(subject: str, quote: str, general_ref: str | None = None) -> bool:
    """Every word of the subject (3 letters or more) is a WHOLE word of the quote, and the anchor BELONGS to the subject: the
    field-list name in both the subject and the quote, or the quote cites the standard the override says it overrides. A clause
    number alone is not an anchor (a stray "see 3.2" would carry any override)."""
    words = [w for w in re.findall(r"[a-z0-9]+", subject.casefold()) if len(w) >= 3]
    q_words = set(re.findall(r"[a-z0-9]+", quote.casefold()))
    if not words or not all(w in q_words for w in words):
        return False
    return bool(_field_anchor(subject, quote) or _standard_anchor(general_ref, quote))


def _keep_standard(raw, p, library, out, tally) -> None:
    name = str((raw or {}).get("name") or "").strip()
    src = _quote(raw or {}, p) if name else None
    cited = _matched_citation(name, src.quote) if src is not None else None
    if cited is None:
        if src is not None and _printed_whole(name, src.quote):
            tally.standards_unrecognised += 1
        else:
            tally.standards_dropped += 1
        return
    name = cited  # the citation as the paper prints it, not the model's spelling
    entry = applicability.find_standard(library, name)
    book = str(entry.get("id") or entry.get("document_id")) if entry else None
    if book is None:
        tally.unheld_standards += 1
    out.setdefault(
        (_norm(name), p.document_id), StandardNamed(name, book, book is not None, src)
    )


def _keep_override(raw, p, out, tally) -> None:
    subject = str((raw or {}).get("subject") or "").strip()
    src = _quote(raw or {}, p) if subject else None
    ref = (raw.get("general_ref") or None) and str(raw.get("general_ref")).strip()
    if src is None or not _subject_in_quote(subject, src.quote, ref):
        tally.overrides_dropped += 1
        return
    prec = (raw.get("precedence") or None) and str(raw.get("precedence")).strip()
    out.setdefault(
        (_norm(subject), _norm(src.quote)), Override(subject, ref, src, prec)
    )


# ---------------------------------------------------------------- the note


def build_note(
    run_id: str,
    *,
    project: str | None,
    admission: Admission,
    standards: tuple[StandardNamed, ...],
    overrides: tuple[Override, ...],
    earlier: EarlierRevision | None,
    earlier_held: bool,
) -> ContextNote:
    """The note. `not_available` always carries a line for each of the five things that is missing, said plainly by code."""
    lines = list(admission.not_available)
    if earlier is None:
        lines.append(NotAvailable("earlier revision", WHY_NO_REVISION))
        lines.append(NotAvailable("earlier comments", WHY_NO_REVISION))
    elif not earlier.comments:
        lines.append(
            NotAvailable(
                "earlier comments", WHY_NO_COMMENTS if earlier_held else WHY_NO_REVISION
            )
        )
    order = {w: i for i, w in enumerate(WHATS)}
    lines.sort(key=lambda n: order[n.what])
    related = tuple(p.document_id for p in admission.readable if p.kind == KIND_RELATED)
    return ContextNote(
        run_id=run_id,
        project=project,
        documents_read=tuple(p.document_id for p in admission.readable),
        standards=standards,
        overrides=overrides,
        related_papers=related,
        earlier=earlier,
        not_available=tuple(lines),
    )


def produced(note: ContextNote, tally: Tally | None = None) -> dict:
    """`produced_json` of role 2: counts and ids only."""
    out: dict = {
        "documents_read": len(note.documents_read),
        "standards": len(note.standards),
        "standards_held": sum(1 for s in note.standards if s.held),
        "overrides": len(note.overrides),
        "related_papers": len(note.related_papers),
        "not_available": [n.what for n in note.not_available],
    }
    if tally is not None:
        out.update(
            windows=tally.windows,
            failed_windows=tally.failed_windows,
            dropped_no_quote=tally.standards_dropped + tally.overrides_dropped,
            standards_unrecognised=tally.standards_unrecognised,
            parts_not_passed=tally.parts_not_passed,
        )
    return out


def run(
    run_id: str,
    *,
    project: str | None,
    papers: Iterable[ProjectPaper],
    paper_row: Mapping,
    rows: Iterable[Mapping],
    earlier_points: Callable[[str], Iterable[Mapping]] | None,
    new_values: Mapping[str, object],
    library: list[dict],
    engine: str,
    ask: Ask | None,
) -> tuple[ContextNote, Tally]:
    """The whole role: admit, read, follow the earlier comments by code, build the note. Nothing held: no call, a note with
    the five lines."""
    adm = admit(papers, engine=engine)
    standards, overrides, tally = read_papers(adm.readable, ask, library, engine=engine)
    prior = earlier_revision(paper_row, list(rows))
    earlier = None
    if prior is not None:
        pts = list(
            earlier_points(str(prior.get("document_id"))) if earlier_points else ()
        )
        earlier = EarlierRevision(
            document_id=str(prior.get("document_id")),
            revision=prior.get("revision"),
            run_id=prior.get("run_id"),
            comments=follow_up(pts, new_values),
        )
    note = build_note(
        run_id,
        project=project,
        admission=adm,
        standards=standards,
        overrides=overrides,
        earlier=earlier,
        earlier_held=prior is not None,
    )
    return note, tally


# ---------------------------------------------------------------- the one finder the job calls


def is_register(filename: str | None, sha256: str | None) -> bool:
    """The client's register, by name OR by checksum. A block list that cannot be read counts as blocked (fail closed)."""
    from . import claude_approved

    try:
        if claude_approved.blocked_by_name(filename):
            return True
        return bool(sha256) and str(sha256).lower() in claude_approved.blocked_hashes()
    except Exception as exc:  # noqa: BLE001 - an unreadable block list blocks
        log.warning(
            "block list unreadable, the paper is treated as blocked: %s",
            type(exc).__name__,
        )
        return True


def paper_scored(conn, document_id: str) -> bool:
    """The paper's kind is scored against an answer key (an unknown kind is not)."""
    from . import agent_review_kind, kind_review_table

    got = agent_review_kind.read_kind(conn, document_id)
    return bool(
        got.get("known") and got.get("kind") and kind_review_table.scored(got["kind"])
    )


def find_papers(
    conn, document_id: str, allowed: Iterable[str], shown: Iterable[str]
) -> list[ProjectPaper]:
    """THE finder: the other papers of the paper's own project and the paper it replaced, with `shown`, `accessible`,
    `register` (name or checksum) and `scored` worked out HERE, so a caller cannot forget one. A rule book is not a project
    paper. The register is returned flagged (never read, never listed); the text of a paper is loaded only when it may be read."""
    allowed_set, shown_set = frozenset(allowed), frozenset(shown)
    mine = conn.execute(
        "SELECT project FROM document_classification WHERE document_id = ?",
        (document_id,),
    ).fetchone()
    project = (mine["project"] if mine else None) or None
    rows = conn.execute(
        "SELECT d.id AS id, d.filename AS filename, d.sha256 AS sha256, c.document_role AS role, c.project AS project,"
        " c.superseded_by AS superseded_by FROM documents d LEFT JOIN document_classification c ON c.document_id = d.id"
        " WHERE d.id != ? AND d.id NOT IN (SELECT DISTINCT standard_document_id FROM standard_requirements) ORDER BY d.id",
        (document_id,),
    ).fetchall()
    out: list[ProjectPaper] = []
    for r in rows:
        earlier = r["superseded_by"] == document_id
        if not earlier and not (project and r["project"] == project):
            continue
        kind = (
            KIND_CONTRACT
            if r["role"] == "CONTRACT_DOCUMENT"
            else KIND_SPEC
            if r["role"] == "SPECIFICATION"
            else KIND_RELATED
        )
        register = is_register(r["filename"], r["sha256"])
        ok = not register and r["id"] in allowed_set and r["id"] in shown_set
        pages = (
            {
                int(x["page_no"]): x["text"] or ""
                for x in conn.execute(
                    "SELECT page_no, text FROM pages WHERE document_id = ? ORDER BY page_no",
                    (r["id"],),
                )
            }
            if ok
            else {}
        )
        out.append(
            ProjectPaper(
                r["id"],
                kind,
                pages,
                r["id"] in shown_set,
                r["id"] in allowed_set,
                register,
                paper_scored(conn, r["id"]) if ok and kind == KIND_RELATED else True,
                earlier,
            )
        )
    return out


# ---------------------------------------------------------------- the note's parts, per source, as derived blocks (provable cells only)

#: the fixed set of precedence codes (the model's free words are never passed on)
PRECEDENCE_CODES = ("project_over_general", "not_stated")
_PRECEDES = re.compile(
    r"project.*(prevail|overrid|preced|govern|supersed|take)|(prevail|overrid|preced).*project",
    re.I,
)


def precedence_code(text: str | None) -> str:
    return "project_over_general" if text and _PRECEDES.search(text) else "not_stated"


@dataclass(frozen=True)
class Parts:
    blocks: tuple[nine_call.Block, ...]
    not_passed: int  # rows left out because code cannot prove every cell: counted, said in the note and the record


def _cell_ok(value: object) -> str | None:
    text = str(value or "")
    return (
        text
        if text
        and len(text) <= nine_call.MAX_CELL_CHARS
        and text == text.strip()
        and "\n" not in text
        else None
    )


def context_blocks(note: ContextNote, tally: Tally | None = None) -> Parts:
    """One derived block (kind review_record) per part, per source document and per column shape, every cell something code can prove
    and every column declared (`kinds`, checked by the seam at send time):
    standards (the citation as printed in the quote: `source`; held/not_held: `enum`; the page: `number`);
    overrides (the anchor: the app's field-list name `key`, or the printed citation `source`; the clause number `clause` when one is in
    both the reference and the quote, else that column is left out; a precedence code `enum`; the page `number`);
    related papers (document id `id`, `enum`); the earlier-revision follow-up (field-list key, the stored word, decision and still-open
    codes: `key`, `enum`, `enum`, `enum`). Never a model paraphrase or a sentence of the paper. `sources` is the document each part
    came from (the seam gates each)."""
    by_doc: dict[tuple[str, str, tuple[str, ...]], list] = {}
    left = 0

    def add(part: str, doc: str, cells, kinds: tuple[str, ...]) -> None:
        nonlocal left
        if cells is None or any(c is None for c in cells):
            left += 1
            return
        by_doc.setdefault((part, doc, kinds), []).append(tuple(cells))

    def enum(word: object) -> str | None:
        text = _cell_ok(word)
        return (
            text
            if text
            and nine_call.nine_record.fold(text) in nine_call._VOCAB[CODES_VOCAB]
            else None
        )

    for s in note.standards:
        add(
            "ctx_standards",
            s.source.document_id,
            (
                _cell_ok(s.name),
                "held" if s.held else "not_held",
                str(int(s.source.page)),
            ),
            ("source", CODE_KIND, "number"),
        )
    for o in note.overrides:
        q = o.project_rule.quote
        field = _field_anchor(o.subject, q)
        anchor = field or _standard_anchor(o.general_ref, q)
        clause = next(
            (c for c in _CLAUSE_NUMBER.findall(o.general_ref or "") if c in q), None
        )
        cells = [_cell_ok(anchor)] + ([clause] if clause else [])
        cells += [precedence_code(o.order_of_precedence), str(int(o.project_rule.page))]
        kinds = (
            (KEY_KIND if field else "source",)
            + (("clause",) if clause else ())
            + (CODE_KIND, "number")
        )
        add("ctx_overrides", o.project_rule.document_id, cells, kinds)
    for d in note.related_papers:
        add("ctx_related", d, (_cell_ok(d), "related"), ("id", CODE_KIND))
    if note.earlier is not None:
        fields = set(rule_labels.field_list())
        decisions = {"keep", "edit", "remove"}
        for c in note.earlier.comments:
            key = re.sub(r"[^a-z0-9]+", "_", (c.field or "").casefold()).strip("_")
            add(
                "ctx_earlier",
                note.earlier.document_id,
                (
                    key if key in fields else None,
                    enum(c.status_word),
                    c.engineer_decision if c.engineer_decision in decisions else "none",
                    {True: "still_open", False: "changed", None: "cannot_tell"}[
                        c.still_open
                    ],
                ),
                (KEY_KIND, CODE_KIND, CODE_KIND, CODE_KIND),
            )
    if tally is not None:
        tally.parts_not_passed += left
    blocks = []
    for (part, doc, kinds), rows in sorted(
        by_doc.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2])
    ):
        name = part + (
            "_" + "_".join(k[:3] for k in kinds) if part == "ctx_overrides" else ""
        )
        blocks.append(
            nine_call.Block(
                "review_record",
                name=name,
                sources=(doc,),
                kinds=kinds,
                items=tuple(rows),
            )
        )
    return Parts(tuple(blocks), left)


def count_lines(tally: Tally) -> tuple[str, ...]:
    """The counted lines the sheet says beside the note (each only when it is more than none): the role never looks as if the
    project documents named less than they did."""
    lines = []
    if tally.standards_unrecognised:
        lines.append(
            f"{tally.standards_unrecognised} named standards not recognised by the app's reader"
        )
    if tally.standards_dropped or tally.overrides_dropped:
        lines.append(
            f"{tally.standards_dropped + tally.overrides_dropped} names dropped: the quote did not show them"
        )
    if tally.parts_not_passed:
        lines.append(
            f"{tally.parts_not_passed} parts not passed to the reviewer: not provable by code"
        )
    return tuple(lines)
