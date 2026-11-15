"""Role 2 of the nine-role reviewer: the project context (B3).

Code finds the project's papers and decides which may be read (the shown list, the starter's access, the engine choice, the
register, a contract). A model reads each allowed paper in windows and may only NAME a standard or a project override with a page
quote. Code finds the quote on that page of that paper; a name or override whose quote is not found is dropped and counted.
The note always says what was not available, filled by code, never by the model.

No model is called here: `ask` is an adapter supplied by the job over B1's seam (`nine_call`). A failed call leaves what code
found. Pure: no database, no network, no document names in this file.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from . import agent_general_review, applicability
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


def nine_on() -> bool:
    """`AGENT_REVIEW_NINE_ROLES_ENABLED` (off = today's requests and bytes). Read here once for the two B3 hooks; the flag itself
    is declared with the job (B5)."""
    from .config import settings

    return bool(getattr(settings, "agent_review_nine_roles_enabled", False))


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


Ask = Callable[[str, Sequence[tuple[int, str]]], Mapping | None]
"""`ask(document_id, [(page, text), ...]) -> {"standards": [{name, page, quote}], "overrides": [{subject, general_ref, page,
quote, precedence}]}` or None. Supplied by the job over `nine_call`; the model sees one window of one allowed paper."""


@dataclass
class Tally:
    read: list[str] = field(default_factory=list)
    windows: int = 0
    failed_windows: int = 0
    standards_dropped: int = 0
    overrides_dropped: int = 0
    unheld_standards: int = 0


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
            chunk = [(n, p.pages[n]) for n in win]
            try:
                got = ask(p.document_id, chunk)
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


def _keep_standard(raw, p, library, out, tally) -> None:
    name = str((raw or {}).get("name") or "").strip()
    src = _quote(raw or {}, p) if name else None
    if src is None:
        tally.standards_dropped += 1
        return
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
    if src is None:
        tally.overrides_dropped += 1
        return
    ref = (raw.get("general_ref") or None) and str(raw.get("general_ref")).strip()
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
