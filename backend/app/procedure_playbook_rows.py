"""#1522 (b): a procedure's CRS rows from the review playbooks, as ENGINEER rows.

A review run of a document whose stored kind is `procedure` never called the review
playbooks (`playbooks.review`), so its CRS had no completeness rows ("does the
procedure contain its team and roles, its nodes, its follow-up"). With
`settings.procedure_playbook_rows_enabled` ON, `crs_rows` adds one row per element of
each matching playbook. No document is named in code: a playbook matches a procedure
when one of its title phrases (`title_cues`, else its title less the generic words) stands as a phrase in the
procedure's cover lines (the first lines of page 1) and none of its `title_excludes` does (order 14 lane P).

What a row may say, and no more:
  * present            -> "found, engineer to confirm" with the page and quote.
  * unclear / missing  -> says so (and which cues were not found).
  * could not be checked -> says so, with the reason.
  * standard_not_held  -> the playbook's own wording: the standard is not held, so
                          the element is never met. With the presence switches on
                          (`playbooks._section_without_standard`): "Section not found:
                          ...; engineer to confirm", or the page and heading where the
                          section was found, content not checked, engineer to confirm.
  * NEVER compliant. Every row is unconfirmed (`engineer_confirmed` False): it rides
    on the internal copy and is not on the contractor's copy until an engineer
    accepts it. No model is called (no proposer). The playbook's draft notice
    travels with each row. The review reads only the run's own allowed documents.
No playbook matched -> no rows and ONE review note saying so.
"""

from __future__ import annotations

import re

from . import crs_mapping, playbooks, procedure_text, word_pages
from .config import settings

KIND = "procedure"
ROW_KIND = "playbook_check"
BY = "Playbook check (draft)"
COVER_LINES = 12
#: Words of a playbook title that do not name its subject.
_GENERIC = frozenset(
    [
        "procedure",
        "procedures",
        "study",
        "review",
        "assessment",
        "the",
        "a",
        "an",
        "of",
        "for",
        "and",
    ]
)
_WORD = re.compile(r"[a-z0-9&]+")


def title_cue(playbook: playbooks.Playbook) -> tuple[str, ...]:
    """The words of the playbook's title that name its subject (its own cue)."""
    return tuple(w for w in _WORD.findall(playbook.title.lower()) if w not in _GENERIC)


def cover_text(pages: list[tuple[int, str]]) -> str:
    """The first lines of the first page: where a procedure names what it is."""
    if not pages:
        return ""
    lines = [ln.strip() for ln in (pages[0][1] or "").splitlines() if ln.strip()]
    return "\n".join(ln for ln in lines[:COVER_LINES] if _is_heading(ln))


#: Words a sentence has and a heading does not (verbs, pronouns, clause links).
_SENTENCE_WORDS = frozenset(
    [
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "shall",
        "will",
        "should",
        "must",
        "may",
        "has",
        "have",
        "this",
        "that",
        "these",
        "those",
        "which",
        "where",
        "when",
        "after",
        "before",
        "following",
        "issued",
        "by",
        "with",
        "from",
        "as",
        "it",
        "we",
    ]
)


def _is_heading(line: str) -> bool:
    """A title-shaped line (short, no colon, not a sentence), not a sentence that
    mentions a subject. Same length and colon rule as `document_kind`'s title cue."""
    from .document_kind import _TITLE_WORDS_MAX

    words = line.strip("| ").split()
    if not words or ":" in line or len(words) > _TITLE_WORDS_MAX:
        return False
    if line.rstrip().endswith((".", ";", ",")):
        return False
    return not any(w.lower() in _SENTENCE_WORDS for w in words)


def cues(playbook: playbooks.Playbook) -> tuple[str, ...]:
    """The phrases a cover names this kind of procedure by: the playbook's own list, else its title cue as one phrase."""
    if playbook.title_cues:
        return playbook.title_cues
    cue = title_cue(playbook)
    return (" ".join(cue),) if cue else ()


def matches(playbook: playbooks.Playbook, cover: str) -> bool:
    """One of the playbook's phrases stands in the cover lines as a PHRASE (its words adjacent, any case, spaces or hyphens:
    `playbooks._hits`), and no phrase that puts the cover outside its book's scope does (order 14 lane P: "Pressure Safety
    Valve Bench Test Procedure" is not a pressure test procedure; a pipeline welding procedure is not on-plot piping). A
    playbook with `title_requires` also needs one of those scope phrases on the cover ("piping" for an on-plot piping book)."""
    if any(playbooks._hits((x,), cover) for x in playbook.title_excludes):
        return False
    if playbook.title_requires and not playbooks._hits(playbook.title_requires, cover):
        return False
    return bool(playbooks._hits(cues(playbook), cover))


def chosen(submittal_id: str) -> list[playbooks.Playbook]:
    """The procedure playbooks whose phrases the paper's cover lines hold, by id: the procedure TYPE of the paper. The one
    home of that choice: the CRS rows below and gate G2's books for the type (`scripts/crs_gates.py`) both take it."""
    found, _broken = playbooks.available()
    cover = cover_text(procedure_text.load_pages(submittal_id))
    return sorted(
        (
            pb
            for pb in found.values()
            if pb.document_kind == KIND and matches(pb, cover)
        ),
        key=lambda p: p.id,
    )


def element_lead(playbook_title: str, element_title: str) -> str:
    """How a row names its playbook element: "<playbook title>, <element title>". The row's comment goes on " (<standard> <clause>):
    ..."; the answer-key scorer (`tools/answer_key_score.py`) reads a row's element from this lead, so the two never differ."""
    return f"{playbook_title}, {element_title}"


def _comment(playbook: playbooks.Playbook, report: dict, entry: dict) -> str:
    head = f"{element_lead(playbook.title, entry['title'])} ({entry['source']['standard']} {entry['source']['clause']})"
    state = entry["state"]
    if state == playbooks.PRESENT:
        ev = (entry["evidence"] or [{}])[0]
        where = ev.get("locator") or "the document"
        quote = f': "{ev["quote"]}"' if ev.get("quote") else ""
        body = f"found at {where}{quote}; engineer to confirm that it meets what is expected"
    elif state == playbooks.UNCLEAR:
        body = f"unclear: {entry['reason']}; engineer to check"
    elif state == playbooks.MISSING:
        body = f"{entry['reason']}; engineer to check whether the document states it in other words"
    elif state == playbooks.STANDARD_NOT_HELD:
        body = entry["reason"]
    else:
        body = f"{entry['reason']}; engineer to check"
    # W-H6 (order 14): the playbook's draft notice is said ONCE per sheet (`notice_line`), never repeated in every row
    return f"{head}: {body}."


def notice_line(notices) -> str | None:
    """W-H6: the ONE line a sheet carries for its playbook rows while a playbook is a draft (each distinct notice once), else None."""
    said = list(dict.fromkeys(n for n in notices if n))
    return f"{BY}: {' '.join(said)}" if said else None


def same_element_found(entries: list[tuple[playbooks.Playbook, dict]]) -> None:
    """W-H6 (order 14): two playbooks chosen for one paper can name the SAME element (one title). When one finds it and the other
    does not, the sheet said "Section not found" in one row while another row cited the section. The row that found nothing says
    where the other playbook found it (its page, as that row cites it), still unconfirmed and still not checked against a book not
    held; every other row is left as it is."""
    found = {}
    for pb, e in entries:
        if e.get("evidence") and e.get("section_state") in (playbooks.PRESENT, playbooks.UNCLEAR):
            found.setdefault(_title_key(e["title"]), (pb, e))
    for pb, e in entries:
        hit = found.get(_title_key(e["title"]))
        if e.get("section_state") != playbooks.MISSING or hit is None or hit[0].id == pb.id:
            continue
        other_pb, other = hit
        page = other.get("cited_page")
        where = f"page {page}" if page else (other["evidence"][0].get("locator") or "the document")
        e.update(
            section_state=playbooks.UNCLEAR, evidence=other["evidence"][:1], cited_page=page,
            reason=(f"unclear: this checklist's own words were not found, but the same element is found by the {other_pb.title} "
                    f"checklist at {where}; {e['source']['standard']} is not held, so its text is not quoted; engineer to confirm"),
        )  # fmt: skip


def _title_key(title: str) -> str:
    return " ".join(_WORD.findall((title or "").lower()))


def _row(playbook, report, entry, submittal_name: str, submittal_id: str = "") -> dict:
    shown = entry["state"] == playbooks.PRESENT or entry.get("section_state") in (
        playbooks.PRESENT,
        playbooks.UNCLEAR,
    )
    ev = (entry["evidence"] or [{}])[0] if shown else {}
    # an unclear row's page column is the page its comment cites (the verified one)
    cited = entry.get("cited_page")
    group = [
        {"document_id": submittal_id, "contractor_evidence_text": ev.get("quote") or ""}
    ]
    return {
        "finding_id": "",
        "document_name": submittal_name,
        "page_section": word_pages.page_cell(f"page {cited}", [cited], group)
        if cited
        else ev.get("locator") or "",
        "comment": _comment(playbook, report, entry),
        "comment_by": BY,
        "standard_reference": f"{entry['source']['standard']} {entry['source']['clause']}",
        "row_kind": ROW_KIND,
        "severity": "",
        "engineer_confirmed": False,
        "comment_key": crs_mapping.comment_key(
            "playbook element", playbook.id, entry["id"]
        ),
        "priority": crs_mapping.PRIORITY_ENGINEER_TO_CHECK,
        "playbook_state": entry["state"],
        # Never printed: the quote the page cell is proved from (`procedure_crs`).
        **({"quote": ev.get("quote")} if settings.procedure_crs_fields_enabled else {}),
    }


def crs_rows(
    submittal_id: str, submittal_name: str, allowed: frozenset[str]
) -> tuple[list[dict], list[dict]]:
    """(rows, review notes) for the run's submittal; ([], []) with the switch off or
    for any kind but a procedure."""
    if (
        not settings.procedure_playbook_rows_enabled
        or procedure_text.document_kind(submittal_id) != KIND
    ):
        return [], []
    picked = chosen(submittal_id)
    if not picked:
        return [], [
            {
                "note": "Playbook check - no playbook matched this procedure",
                "standard": "",
                "count": None,
                "detail": (
                    "No review playbook's title appears in the first lines of this procedure, so its "
                    "completeness was not checked against a playbook; engineer to check it."
                ),
            }
        ]
    reports = [(pb, playbooks.review(submittal_id, pb, allowed_document_ids=allowed)) for pb in picked]
    same_element_found([(pb, e) for pb, report in reports for e in report["elements"]])
    rows = []
    for pb, report in reports:
        rows.extend(
            {**_row(pb, report, e, submittal_name, submittal_id), "playbook_notice": report["playbook"]["notice"]}
            for e in report["elements"]
        )
    said = notice_line(r["playbook_notice"] for r in rows)
    return rows, ([{"note": "Playbook check - draft", "standard": "", "count": len(rows), "detail": said}] if said else [])


def merge(
    rows: list[dict],
    submittal_id: str,
    submittal_name: str,
    allowed: frozenset[str],
    findings: list[dict] = (),
) -> tuple[list[dict], list[dict]]:
    """The CRS rows with the playbook rows added in rank order (the same list, untouched,
    when there are none), and the review notes this adds. Order 4c, switch on: each
    quoted row's page cell, and the note that says what the Item No label is."""
    from . import procedure_crs

    mine, notes = crs_rows(submittal_id, submittal_name, allowed)
    merged = (
        sorted([*rows, *mine], key=lambda r: r.get("priority") or 0) if mine else rows
    )
    procedure_crs.fill_pages(merged, list(findings), submittal_id)
    return merged, notes + procedure_crs.number_notes(submittal_id)
