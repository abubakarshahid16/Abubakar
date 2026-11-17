"""Assemble ONE paper's list of points: the rule check's comments and the AI review's lines, their decisions, the counts and the
proposed review code (owner, 12 Nov 2026, the redesigned page). Reads only; the scope question is asked here once (rule 5)."""

from __future__ import annotations

import logging
from pathlib import Path

from . import agent_review_not_applicable as not_applicable
from . import (
    crs_comments,
    crs_completeness,
    evidence_boxes,
    review_code_proposal,
    standards_web_search,
)
from . import review as review_mod
from . import (
    review_point_decisions as decisions_mod,
)
from . import (
    review_points as rp,
)
from . import (
    review_points_notes as notes_mod,
)
from .config import settings
from .db import connect

DONE = ("complete", "completed")


def runs_of_paper(conn, paper_id: str) -> tuple[str | None, str | None]:
    """(the paper's latest finished rule-check run, its latest finished AI review run), None where there is none."""
    marks = ",".join("?" for _ in DONE)
    base = (
        "SELECT r.id FROM review_runs r WHERE r.submittal_document_id = ? AND r.status IN ("
        + marks
        + ") {extra}"
        " ORDER BY r.started_at DESC LIMIT 1"
    )
    ai = None
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name = 'agent_review_run'"
    ).fetchone():
        row = conn.execute(
            base.format(extra="AND r.id IN (SELECT run_id FROM agent_review_run)"),
            (paper_id, *DONE),
        ).fetchone()
        ai = row["id"] if row else None
        rc_row = conn.execute(
            base.format(extra="AND r.id NOT IN (SELECT run_id FROM agent_review_run)"),
            (paper_id, *DONE),
        ).fetchone()
    else:
        rc_row = conn.execute(base.format(extra=""), (paper_id, *DONE)).fetchone()
    return (rc_row["id"] if rc_row else None), ai


SHALL, SHOULD, UNKNOWN = "shall", "should", "unknown"
UNKNOWN_STRENGTH_WORDS = (
    "the rule's strength is not recorded, so it is treated as mandatory"
)


def _checklist_entry(rule_id: str) -> dict | None:
    """The approved checklist entry (`reference/datasheet_checks.json`) with this id, or None."""
    from . import datasheet_checks

    try:
        data = datasheet_checks.load_rules()  # the ONE reader of the approved checklist
    except (OSError, ValueError):
        return None

    def walk(node):
        if isinstance(node, dict):
            if node.get("id") == rule_id:
                return node
            for v in node.values():
                if (got := walk(v)) is not None:
                    return got
        elif isinstance(node, list):
            for v in node:
                if (got := walk(v)) is not None:
                    return got
        return None

    return walk(data)


def _strength(finding: dict | None) -> str:
    """ "shall", "should" or "unknown", read from EVERY home that knows the rule's strength: the stored requirement (its type is a
    recommendation or not), and for a datasheet-check finding the approved checklist entry (mandatory unless the entry says it is a
    recommendation). Nothing known: "unknown", and the proposal treats it as mandatory and says so (the stricter code, never a silent
    softer one)."""
    f = finding or {}
    rid = f.get("requirement_id")
    if rid:
        row = (
            connect()
            .execute(
                "SELECT requirement_type FROM standard_requirements WHERE id = ?",
                (rid,),
            )
            .fetchone()
        )
        if row:
            return SHOULD if row["requirement_type"] == "recommendation" else SHALL
    if f.get("origin") == "datasheet_check":
        import re

        m = re.search(
            r"\b([A-Z][A-Z0-9]*-[A-Z0-9]+):",
            str(f.get("requirement_source_text") or ""),
        )  # "<label> DS-C1: <text>"
        entry = _checklist_entry(m.group(1)) if m else None
        if entry is not None:
            soft = entry.get("recommendation") is True or str(
                entry.get("strength") or ""
            ).lower() in ("should", "recommendation")
            return SHOULD if soft else SHALL
        return SHALL  # an approved checklist check: mandatory unless its entry says otherwise
    return UNKNOWN


def _fold(text) -> str:
    return " ".join(str(text or "").lower().split())


def _on_page(document_id: str | None, page, text, scope) -> bool:
    """Code check: the passage stands in the stored text of that page of a document the caller may read. This is what lets a
    rule-check point show a passage ("this passage is on the page"): located by code, never invented."""
    quote = _fold(text)
    if not (
        document_id
        and isinstance(page, int)
        and page >= 1
        and quote
        and scope.may_read(document_id)
    ):
        return False
    row = (
        connect()
        .execute(
            "SELECT text FROM pages WHERE document_id = ? AND page_no = ?",
            (document_id, page),
        )
        .fetchone()
    )
    return bool(row) and quote in _fold(row["text"])


def _sides(finding: dict, scope) -> dict:
    """{"submittal": {"document", "page", "verified"}, "standard": {...}} for a finding: `verified` only when the cited passage is found
    in the stored text of the cited page (`_on_page`)."""
    out = {}
    for side, (doc_f, page_f, text_f) in evidence_boxes.SIDES.items():
        doc, page = finding.get(doc_f), finding.get(page_f)
        readable = bool(doc) and scope.may_read(doc)
        out[side] = {
            "document": doc if readable else None,
            "page": page if readable else None,
            "verified": _on_page(doc, page, finding.get(text_f), scope),
        }
    return out


def _checklist_entry_of(finding: dict | None) -> tuple[str, dict] | None:
    """(entry id, the entry) of the approved checklist the finding's text comes from: its stored origin is the datasheet check AND the entry
    it names is in `reference/datasheet_checks.json` with a text of its own. None when that cannot be proven."""
    f = finding or {}
    if f.get("origin") != "datasheet_check":
        return None
    import re

    m = re.search(r"\b([A-Z][A-Z0-9]*-[A-Z0-9]+):", str(f.get("requirement_source_text") or ""))
    entry = _checklist_entry(m.group(1)) if m else None
    return (m.group(1), entry) if entry and str(entry.get("text") or "").strip() else None


def _checklist_origin(finding: dict | None) -> bool:
    """The finding's text is the app's OWN approved checklist: its stored origin is the datasheet check AND the checklist entry it names is
    in `reference/datasheet_checks.json`. Proven from stored data; when the entry cannot be found it is not proven (hidden)."""
    return _checklist_entry_of(finding) is not None


def _ref_state(reference: str, library: list[dict], readable: frozenset[str]) -> str:
    """How a stored standard reference resolves to the held library: "readable" (it resolves, and EVERY book it resolves to is readable),
    "unreadable" (it resolves to a book the viewer may not read), "unresolved" (a cited standard that no held book matches) or "none"."""
    from . import applicability, standard_ids

    text = " ".join(str(reference or "").split())
    if not text:
        return "none"
    state = "readable"
    for cited in standard_ids.cited_standards(text) or [text]:
        hits = [
            e["id"]
            for e in library
            if any(standard_ids.same_standard(cited, n) for n in applicability._library_names(e))
        ]
        if not hits:
            return "unresolved"
        if any(h not in readable for h in hits):
            state = "unreadable"
    return state


def readability_proof(row: dict, finding: dict | None, docs: list[str], readable: frozenset[str], library: list[dict], everything: bool) -> tuple[bool, bool]:
    """(content, reference): may this viewer see the requirement-derived CONTENT of a rule-check point, and the stored REFERENCE (a book
    name)? Fail closed: shown only when readability is PROVEN. A viewer who may read the whole library is not restricted. Linked books: all
    must be readable. No link: a checklist origin proves the content (the reference still needs its books readable or not held at all); a
    reference that resolves to readable held books only proves both. Everything else is hidden."""
    if everything:
        return True, True
    if docs:
        ok = all(d in readable for d in docs)
        return ok, ok
    state = _ref_state((row or {}).get("standard_reference"), library, readable)
    if _checklist_origin(finding):
        return True, state != "unreadable"
    return state == "readable", state == "readable"


def _rule_points(run_id: str, paper_id: str, scope) -> list[dict]:
    from . import main as main_mod

    rows = main_mod._crs_content(
        run_id, scope, "internal", apply_point_decisions=False
    )[0]
    ctx = {
        "run_id": run_id,
        "paper_document_id": paper_id,
        "readable": frozenset(scope.allowed_document_ids),
        # the tags THIS review knows for the paper (its findings' equipment tags): a bracket group is a tag list only when its entries ARE these
        "known_tags": frozenset(
            "".join(str(r[0]).upper().split())
            for r in connect().execute(
                "SELECT DISTINCT equipment_tag FROM review_findings WHERE review_run_id = ? AND equipment_tag IS NOT NULL AND equipment_tag != ''",
                (run_id,),
            )
        ),
    }
    from .agent_review_rules import library_of

    conn = connect()
    library = library_of(conn)
    everything = {r[0] for r in conn.execute("SELECT id FROM documents")} <= ctx["readable"]
    out = []
    for row in rows:
        fid = row.get("finding_id")
        finding = review_mod.get(fid) if fid else None
        if finding is not None and finding.get("fact_id"):  # the value the datasheet check read: its text and its page
            fact = connect().execute("SELECT field_name, field_value, unit, page FROM submittal_facts WHERE id = ?", (finding["fact_id"],)).fetchone()
            finding = {**finding, "_fact": dict(fact) if fact else None}
        if finding is not None and not scope.may_read(finding["document_id"]):
            finding = None
        sides = _sides(finding, scope) if finding else {}
        docs = _book_docs_of_row(row, finding, {})
        proof = readability_proof(row, finding, docs, ctx["readable"], library, everything)
        app_text = False
        if not everything and not docs and proof[0] and (hit := _checklist_entry_of(finding)):
            app_text = True
            # the checklist is app content every user may see, but ONLY the text in the approved file itself: read from the JSON entry, never
            # from the stored row (a stored row can carry words of a book)
            text = f"Datasheet check {hit[0]}: {' '.join(str(hit[1]['text']).split())}"
            finding = {**finding, "requirement_source_text": text, "requirement": text}
        p = rp.rule_point(row, ctx, finding, sides, strength=_strength(finding), proof=proof, app_text_only=app_text)
        p["_book_docs"] = docs
        p["_confirmed"], p["_rejected"] = (
            bool(row.get("engineer_confirmed")),
            bool(row.get("engineer_rejected")),
        )
        out.append(p)
    shown = {p["id"] for p in out}
    for pid, d in decisions_mod.latest(
        paper_id
    ).items():  # a REMOVED point stays in the record (and the list), though its row left the sheet
        key = pid.removeprefix("rc:")
        if (
            pid.startswith("rc:")
            and d["state"] == decisions_mod.REMOVE
            and pid not in shown
        ):
            finding = review_mod.get(key)
            if (
                finding
                and finding.get("review_run_id") == run_id
                and scope.may_read(finding["document_id"])
            ):
                out.append(rp.removed_stub(finding, ctx, strength=_strength(finding)))
    return out


def _book_docs_of_row(row: dict, finding: dict | None, point: dict) -> list[str]:
    """Every rule book (document id) the row's findings cite, in order, without repeats: a row that cites several clauses, or several
    books, is one point that counts once for each book."""
    docs: list[str] = []
    if finding and finding.get("standard_document_id"):
        docs.append(finding["standard_document_id"])
    for fid in row.get("finding_ids") or []:
        other = review_mod.get(fid) if fid != (finding or {}).get("id") else None
        if other and other.get("standard_document_id"):
            docs.append(other["standard_document_id"])
    return list(dict.fromkeys(docs))


def _stem(filename: str | None) -> str | None:
    """A rule book's name from its file name: the stem (the same rule the AI reviewer uses for its rule book labels)."""
    return Path(filename).stem.strip() or None if filename else None


def resolve_books(points: list[dict], readable: frozenset[str]) -> None:
    """Give each point its rule books by IDENTITY: `books` = [{id, name}] of the books it cites that the caller may read (the name is
    the book's own file name, not a string made of its clause and page), `rule_book` = the first one's name. A book the caller may not
    read is counted by the listing, never named (rule 5). Points that cite no book have an empty `books`."""
    ids = {d for p in points for d in p.get("_book_docs") or [] if d in readable}
    names: dict[str, str] = {}
    if ids:
        marks = ",".join("?" for _ in ids)
        for r in connect().execute(
            f"SELECT id, filename FROM documents WHERE id IN ({marks})", sorted(ids)
        ):
            if _stem(r["filename"]):
                names[r["id"]] = _stem(r["filename"])
    for p in points:
        books = [
            {"id": d, "name": names[d]}
            for d in p.get("_book_docs") or []
            if d
            in names  # `names` holds readable books only (the ONE guard: `ids` above)
        ]
        p["books"] = books
        # a point that cites a book the caller may not read is counted apart for it, even when another of its books is readable
        p["_other_books"] = any(
            d not in names or d not in readable for d in p.get("_book_docs") or []
        )
        p["no_book"] = not (
            p.get("_book_docs") or p.get("_book_doc")
        )  # cites no rule book at all
        if books:
            p["rule_book"] = books[0]["name"]
        elif p.get("_book_docs") or p.get("_book_doc"):
            p["rule_book"], p["clause"] = (
                None,
                None,
            )  # held but not readable (or not found): not named
        else:
            p["rule_book"] = (
                None  # no identity, no chip: a display string is never parsed into a book
            )


def _names(ids) -> dict[str, str]:
    ids = sorted(i for i in ids if i)
    if not ids:
        return {}
    marks = ",".join("?" for _ in ids)
    return {
        r["id"]: r["display_name"]
        for r in connect().execute(
            f"SELECT id, display_name FROM users WHERE id IN ({marks})", ids
        )
        if r["display_name"]
    }


def _assemble(paper_id: str, scope) -> tuple[dict, list[dict], dict]:
    """(the listing, the RAW points with their private keys, the facts the one-CRS export needs). `assemble` is the listing alone."""
    conn = connect()
    rc_run, ai_run = runs_of_paper(conn, paper_id)
    readable = frozenset(scope.allowed_document_ids)
    ai_pts, not_held = (
        rp.ai_points_of_run(conn, ai_run, paper_id, readable) if ai_run else ([], [])
    )
    library = rp.library_of(conn)
    not_held = rp.books_not_held(not_held, [], library)  # the run's record, re-tested against today's library
    rc_pts = _rule_points(rc_run, paper_id, scope) if rc_run else []
    # the AI review is the only reviewer: its notes are points of the one list (a rule check lists its own); the notes are the calculator's: behind its setting
    if ai_run and not rc_run and settings.ai_review_calculator_enabled:
        ai_pts += notes_mod.notes_of_run(ai_run, paper_id, scope, not_held)
    names = _names(decisions_mod.people(paper_id))
    add_pts = [
        decisions_mod.added_point(r, names.get(r["added_by"]) or r["added_by"])
        for r in decisions_mod.added(paper_id)
    ]
    points = rp.build(ai_pts, rc_pts, add_pts)
    resolve_books(points, readable)
    sentence_quotes(points, _paper_kind(conn, ai_run, paper_id))
    decided_by_me = decisions_mod.latest(paper_id)
    for p in points:
        d = decisions_mod.decision_of_point(p["id"], decided_by_me)
        if d["state"] is None and p.get("_rejected"):
            d = {
                "state": decisions_mod.REMOVE,
                "words": "Removed",
                "by": None,
                "reason": "removed earlier by an engineer",
            }
        elif d["state"] is None and p.get("_confirmed"):
            d = {"state": decisions_mod.KEEP, "words": "Kept", "by": None}
        if d.get("by"):
            d["by"] = names.get(d["by"]) or d["by"]
        if p.get("tile") == not_applicable.TILE:  # owner on PR #1872: a tick confirms the AI's "does not apply"
            d = {**d, "words": not_applicable.CONFIRMED if d.get("state") == decisions_mod.KEEP else d.get("words") or not_applicable.OPEN}
        p["decision"] = d
    decided = len(points) - len(review_code_proposal.still_open(points))  # FTU-16: the one open count, as the proposal reads it
    not_held = rp.books_not_held(not_held, points, library)  # with every row's "Book missing": one list for page and sheet
    counts = rp.counts(
        points, two_reader_possible=bool(ai_run), not_held=not_held, decided=decided
    )
    # the online search for books not held: off, {} and nothing added; never a point
    online = standards_web_search.into(counts, conn, ai_run, not_held)
    proposal = review_code_proposal.propose(
        points,
        unread_pages=_unread_pages(rc_run or ai_run, scope),
        resubmit_at=int(settings.review_code_resubmit_at_kept_mandatory_not_met or 0),
        reviews_ran=bool(rc_run or ai_run),
    )
    final = (
        conn.execute(
            "SELECT engineer_final_code, override_reason FROM review_runs WHERE id = ?",
            (rc_run or ai_run,),
        ).fetchone()
        if (rc_run or ai_run)
        else None
    )
    listing = {
        "paper_document_id": paper_id,
        "runs": {"rule_check": rc_run, "ai_review": ai_run},
        "points": [rp.public(p) for p in points],
        "counts": counts,
        "proposed_code": proposal,
        "final_code": (final["engineer_final_code"] if final else None) or None,
        # the recorded code as the page and each file print it (an approving code recorded with points open says so)
        "final_code_words": review_code_proposal.recorded_words(
            conn,
            rc_run or ai_run,
            (final["engineer_final_code"] if final else None) or None,
            final["override_reason"] if final else None,
            undecided=len(points) - decided,
            of=len(points),
        ),
        "code_run_id": rc_run or ai_run,
        "decided": decided,
        "of": len(points),
        "removed": [
            rp.public(p)
            for p in points
            if p["decision"]["state"] == decisions_mod.REMOVE
        ],
        "contractor_copy": _contractor_copy(conn, ai_run),
        "found_during_review": _found_during_review(conn, rc_run, ai_run),
    }
    grouped = crs_comments.group(points)  # P2: the SAME function the CRS file uses, so the page and the file show the same comments
    listing["comments"] = [crs_comments.public(c) for c in grouped]
    listing["comment_count"] = len(grouped)
    listing["completeness"] = crs_completeness.stored_latest(rc_run, ai_run)  # the three counts of the last review: the page says when they differ
    listing["kind_used"] = kind_used(conn, ai_run)  # LPS S3: the kind the review USED, from its run record
    listing["found"] = found_of(listing)  # LPS S2: THE one home of the "Found by the review" number of the review list
    facts = {"names": names, "not_held": not_held, "ai_run": ai_run, "rc_run": rc_run}
    return listing, points, {**facts, **online}


def found_of(listing: dict) -> dict:
    """THE one home of what a review list says the paper's review found (order 14 LPS, S2): the SAME tile totals the paper's page
    shows (`counts.tiles`), the lines the AI thinks do not apply (still to confirm), every point of the page and how many are not
    decided yet, and the runs the page is built from. The review list says these numbers, never a run's own finding count (an AI
    review's run holds no findings of the rule check, so that count said 0 while the page held 72 questions)."""
    tiles = listing["counts"]["tiles"]
    return {
        "not_met": tiles["not_met"]["total"],
        "questions": tiles["questions"]["total"],
        "met": tiles["met"]["total"],
        "does_not_apply": tiles["does_not_apply"]["total"],
        "to_confirm": sum(1 for p in listing["points"] if p.get("tile") == not_applicable.TILE),
        "points": listing["of"],
        "undecided": listing["of"] - listing["decided"],
        "runs": dict(listing["runs"]),
    }


def kind_used(conn, ai_run: str | None) -> dict | None:
    """The kind the paper's AI review USED, from its run record (`agent_review_run.paper_kind`, `kind_source`), order 14 LPS S3:
    `guess` only when that run used a guess. None without an AI review run or its record: the page then shows the stored kind."""
    import sqlite3

    from . import agent_review_kind as kind_mod

    if not ai_run:
        return None
    try:
        row = conn.execute(
            "SELECT paper_kind, kind_source FROM agent_review_run WHERE run_id = ?", (ai_run,)
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    if row is None:
        return None
    source = str(row["kind_source"] or "")
    known = bool(row["paper_kind"]) and row["paper_kind"] != kind_mod.UNKNOWN and source != kind_mod.SOURCE_NONE
    return {
        "run_id": ai_run,
        "kind": row["paper_kind"] if known else None,
        "known": known,
        "guess": known and source == kind_mod.SOURCE_GUESS,
        "confirmed": known and source == kind_mod.SOURCE_CONFIRMED,
        "source": source,
    }


def found_of_runs(run_ids: list[str], scope) -> dict[str, dict]:
    """{run id: `found_of` its paper's page} for each run that IS one of its paper's page runs (the latest finished rule check or AI
    review), on a paper the caller may read (rule 5: narrows only). An older run, a run not finished, or a paper the caller may not
    read is absent: the list then says nothing for it, never 0. Each paper is assembled once."""
    conn = connect()
    readable = frozenset(scope.allowed_document_ids)
    by_paper: dict[str, dict | None] = {}
    out: dict[str, dict] = {}
    for run_id in dict.fromkeys(run_ids):
        row = conn.execute("SELECT submittal_document_id FROM review_runs WHERE id = ?", (run_id,)).fetchone()
        paper = row["submittal_document_id"] if row else None
        if not paper or paper not in readable:
            continue
        if paper not in by_paper:
            rc_run, ai_run = runs_of_paper(conn, paper)
            by_paper[paper] = assemble(paper, scope)["found"] if (rc_run or ai_run) else None
        found = by_paper[paper]
        if found is not None and run_id in found["runs"].values():
            out[run_id] = found
    return out


def assemble(paper_id: str, scope) -> dict:
    return _assemble(paper_id, scope)[0]


def export_listing(paper_id: str, scope) -> tuple[dict, list[dict], dict]:
    """The listing, the raw points (private keys kept) and the facts for the ONE CRS file (`crs_one`): the same list the page reads."""
    return _assemble(paper_id, scope)


def _found_during_review(conn, *run_ids) -> int:
    """How many rule books the paper's review found only while it ran and so did not send (they were not on the list shown before
    the start): the UNION over the paper's runs (the rule check and the AI review), each book once. 0 when none: the screen then
    says nothing."""
    import sqlite3

    from . import agent_review_rules, review_shown

    books: set[str] = set()
    for run_id in filter(None, run_ids):
        try:
            dropped = [
                str(r[0])
                for r in conn.execute(
                    "SELECT DISTINCT standard_document_id FROM agent_review_rule WHERE run_id = ? AND asked = 0"
                    " AND left_out_reason = ? AND standard_document_id IS NOT NULL",
                    (run_id, agent_review_rules.REASON_WORDS[agent_review_rules.NOT_ON_LIST]),
                )
            ]
        except sqlite3.OperationalError:
            dropped = []
        books |= set(review_shown.held_rule_books(conn, run_id, extra=dropped))
    return len(books)


def _unread_pages(run_id: str | None, scope) -> int | None:
    """How many pages of the paper were not read, from the run's page record; None when it holds none (said, never 0)."""
    if not run_id:
        return None
    from . import comparison, page_ledger

    try:
        outcome = (
            comparison.run_outcome(
                run_id, allowed_document_ids=scope.allowed_document_ids
            )
            or {}
        )
        cov = outcome.get("page_coverage")
        if not cov or cov.get("pages_total") is None:
            return None
        return len(page_ledger.run_unread_pages(cov, page_ledger.run_reader(outcome)))
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "review points: the page record is unreadable (%s)", type(exc).__name__
        )
        return None


def undecided(paper_id: str, scope) -> tuple[int, int]:
    """(points not decided, points in all) for the sign gate."""
    got = assemble(paper_id, scope)
    return got["of"] - got["decided"], got["of"]  # FTU-16: the listing's one open count (`review_code_proposal.still_open`)


def missing_books(conn, run_id: str) -> list[dict]:
    """The run's rule books not held, from its own record (`agent_review_missing_book`), as `crs_ai_words.mark_not_held` reads them."""
    return [{"rule_book": r["name"], "why": r["why"] or ""}
            for r in conn.execute("SELECT name, why FROM agent_review_missing_book WHERE run_id = ? ORDER BY rowid", (run_id,))]  # fmt: skip


def stored_lines(conn, run_id: str) -> list[dict]:
    """A run's stored lines as every CRS reads them (`crs_ai_words.read_now` with the run's books not held): the decided copy, the
    completeness count of the stored files (`crs_completeness._older_expected`) and the gates."""
    import json

    from . import crs_ai_words

    rows = conn.execute(
        "SELECT item_id, line_json FROM agent_review_line WHERE run_id = ? ORDER BY rowid",
        (run_id,),
    )
    return crs_ai_words.read_now(
        [{**json.loads(r["line_json"] or "{}"), "item_id": r["item_id"]} for r in rows],
        missing_books(conn, run_id),
    )


def run_meta(conn, run_id: str, paper_id: str, folder) -> dict:
    """THE meta an AI run's CRS is drawn again with (the engineer's decided copy, the gates): the file kept beside the run's sheets
    (`crs-meta.json`; unreadable or missing: a minimal meta, the paper and the run id), and the rule books NOT HELD always from the run's
    own record in the database (`agent_review_missing_book`, written with the meta), so a sheet drawn without that file (a restored
    database, a copy) still lists every book missing (order 14, G7). The file's list stands only when the database holds none."""
    import json
    from pathlib import Path

    path = Path(folder) / "crs-meta.json"
    try:
        meta = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, ValueError):
        meta = {}
    meta = meta if isinstance(meta, dict) else {}
    meta.setdefault("paper", paper_id)
    meta.setdefault("run_id", run_id)
    held = missing_books(conn, run_id)
    if held:
        labels = (
            meta.get("rule_labels") if isinstance(meta.get("rule_labels"), dict) else {}
        )
        meta["rule_labels"] = {**labels, "missing_rule_books": held}
    return meta


def decided_ai_sheet(run_id: str, paper_id: str, copy: str, folder) -> Path | None:
    """The AI review's CRS copy drawn again with the engineer's decisions (removed lines out, edited text in, added points in), or None
    when nothing was decided or added for this paper (the stored file stands). The run's own meta: `run_meta`."""
    from pathlib import Path

    from . import agent_review_crs, crs_ai_workbook

    if not decisions_mod.latest(paper_id) and not decisions_mod.added(paper_id):
        return None
    conn = connect()
    lines = stored_lines(conn, run_id)
    folder = Path(folder)
    meta = run_meta(conn, run_id, paper_id, folder)
    kept = decisions_mod.apply_to_lines(
        paper_id, run_id, lines, _names(decisions_mod.people(paper_id))
    )
    agent_review_crs._refuse_unproven(kept)  # the exit's own refusal still stands
    return crs_ai_workbook.write(kept, folder / f"crs-{copy}-decided.xlsx", meta, copy)


def _paper_kind(conn, ai_run: str | None, paper_id: str) -> str | None:
    """The kind the paper was reviewed as: its AI run's kind, else the decided kind."""
    from . import kind_words

    return _contractor_copy(conn, ai_run)["kind"] or kind_words.decided_kind(paper_id)


def sentence_quotes(points: list[dict], kind: str | None) -> None:
    """LPC (C4): on a paper under GENERAL review (a contract, a procedure), a quote is shown as evidence only when it is a full
    sentence (`quote_sentence`, the one test); otherwise the point says it holds no quote. A datasheet's points are not touched (a
    cell value is not a sentence). In place."""
    from . import agent_review_gate, quote_sentence

    if not agent_review_gate.general_kind_enabled(kind):
        return
    for p in points:
        refused = False
        for key in ("paper_quote", "paper_value"):
            if p.get(key) and not quote_sentence.is_full_sentence(p[key]):
                p[key], refused = None, True
        if refused and not p.get("paper_quote"):
            p["paper_quote_note"], p["paper_quote_refused"] = (
                quote_sentence.NO_SENTENCE,
                True,
            )


def _contractor_copy(conn, ai_run: str | None) -> dict:
    """{kind, words}: what the AI review's contractor copy holds for this paper's kind (the kind of its AI run)."""
    kind = None
    if ai_run:
        row = conn.execute(
            "SELECT paper_kind FROM agent_review_run WHERE run_id = ?", (ai_run,)
        ).fetchone()
        kind = row["paper_kind"] if row else None
    from . import kind_review_table

    return {"kind": kind, "words": kind_review_table.contractor_copy_words(kind)}
