"""The engineer's SIGN-OFF of a general review, and the contractor copy issued with it (order 14; lead's design, approved 18 Nov 2026).

SIGNER: the earlier engine's own rule: a signed-in user who may read the paper (`api_utils.require_named_user` in the route); the
signer is the server's user, never the body's. Append-only: a re-sign is a new row, the older ones stay.

BEFORE SIGNING (every refusal says what is wrong, in words and comment numbers): the run finished (not stopped early); its three counts
agree (page = database = file); EVERY comment and confirmation is decided (the undecided ones are listed; `accept_rest` accepts them, each
as its own decision row); the review code is the engineer's own choice of the four configured labels (nothing is proposed by the machine);
and the contractor copy can be built with no internal text (`aim_review_contractor`).

AFTER SIGNING: the contractor copy built from that moment is KEPT with its sha256 (`aim_issued_copies`) and is what a download returns,
byte for byte. A decision made after the sign-off changes the run's digest: the state reads "changed since sign-off" and the contractor
copy is refused until the run is signed again. Ids, counts and words in the audit; never document text. No model, no socket.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

from . import aim_review_decisions
from .aim_review_gate import NO_CONTRACTOR_COPY_WORDS
from .aim_review_store import DECISIONS, ISSUED, SIGNOFFS

AUDIT = "general_review_signed"
AUDIT_ACCEPT_REST = "general_comments_accepted_rest"
NOT_SIGNED, SIGNED, CHANGED = "not_signed", "signed", "changed"
SUPER_USER_WORDS = "Only a super user can sign this review for now."
NOT_SIGNED_WORDS = NO_CONTRACTOR_COPY_WORDS
CHANGED_WORDS = (
    "No contractor copy: a decision changed after the sign-off. Sign the review again."
)


class Refused(ValueError):
    """The sign-off cannot be recorded; `blockers` lists each comment (part, number, title or why) in words."""

    def __init__(self, message: str, blockers: list[dict] | None = None) -> None:
        super().__init__(message)
        self.blockers = blockers or []


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _has(conn) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name = ?", (SIGNOFFS,)
        ).fetchone()
        is not None
    )


def digest(conn, run_id: str) -> str:
    """A fingerprint of every comment's LATEST decision: it changes when any decision is made after it was taken."""
    latest: dict[tuple[str, str], str] = {}
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name = ?", (DECISIONS,)
    ).fetchone():
        for r in conn.execute(
            f"SELECT id, part, comment_key FROM {DECISIONS} WHERE run_id = ? ORDER BY decided_at, rowid",
            (run_id,),
        ):
            latest[(r["part"], r["comment_key"])] = r["id"]
    raw = "|".join(f"{p}:{k}:{i}" for (p, k), i in sorted(latest.items()))
    return hashlib.sha256(raw.encode()).hexdigest()


def undecided(view: dict) -> list[dict]:
    """The comments and confirmations with no decision, by number and title (a title is the card's one line, never the paper's text)."""
    out = []
    for part, group in (
        ("comment", view["comments"]),
        ("confirmation", view.get("confirmations") or []),
    ):
        out += [
            {"part": part, "n": c["n"], "title": c.get("title") or ""}
            for c in group
            if not c.get("decision")
        ]
    return out


def _name(conn, user_id: str) -> str:
    row = conn.execute(
        "SELECT display_name FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    return (
        str(row["display_name"])
        if row and row["display_name"]
        else "the reviewing engineer"
    )


def latest(conn, run_id: str):
    if not _has(conn):
        return None
    return conn.execute(
        f"SELECT * FROM {SIGNOFFS} WHERE run_id = ? ORDER BY signed_at DESC, rowid DESC LIMIT 1",
        (run_id,),
    ).fetchone()


def status(conn, run: dict, view: dict, may_sign: bool = False) -> dict:
    """What the page's sign bar says: not signed / signed / changed since sign-off, the undecided list, and the four code labels."""
    from . import comparison

    row = latest(conn, run["run_id"])
    state = NOT_SIGNED
    if row is not None:
        state = (
            SIGNED
            if row["decisions_digest"] == digest(conn, run["run_id"])
            else CHANGED
        )
    todo = undecided(view)
    out = {
        "state": state, "undecided": todo, "undecided_count": len(todo), "codes": list(comparison.review_codes()),
        "can_sign": run.get("status") == "done" and not todo, "signed": None, "may_sign": may_sign,
        "may_sign_words": None if may_sign else SUPER_USER_WORDS,
    }  # fmt: skip
    if row is not None:
        from . import aim_review_contractor

        counts = json.loads(row["counts_json"])
        out["signed"] = {
            "by": _name(conn, row["signed_by"]),
            "at": row["signed_at"],
            "code": row["review_code"],
            "statement": row["statement"],
            "counts": counts,
            "copy_statement": aim_review_contractor.statement(counts),
        }
    return out


def accept_rest(conn, run: dict, view: dict, actor: str) -> int:
    """Accept every undecided comment and confirmation, each as its own decision row (the history shows it). Returns how many."""
    by_n = {
        "comment": {c["n"]: c for c in view["comments"]},
        "confirmation": {c["n"]: c for c in view.get("confirmations") or []},
    }
    todo = undecided(view)
    with conn:
        for t in todo:
            aim_review_decisions.record(
                conn, run["run_id"], run["paper_document_id"], by_n[t["part"]][t["n"]], t["part"], aim_review_decisions.ACCEPT,
                actor=actor, text=None, reason=None,
            )  # fmt: skip
        if todo:
            aim_review_decisions.audit(
                conn,
                actor,
                AUDIT_ACCEPT_REST,
                run["paper_document_id"],
                {"run": run["run_id"], "count": len(todo)},
            )
    return len(todo)


def sign(
    conn, run: dict, view: dict, actor: str, code: str, statement: str | None = None
) -> dict:
    """Record the sign-off and keep the contractor copy. Raises `Refused` (the reason in words, the comments named) and writes nothing."""
    from . import aim_review_completeness, aim_review_contractor, comparison

    if run.get("status") != "done":
        raise Refused("a review that stopped early cannot be signed off")
    _data, rep = aim_review_completeness.checked(conn, run, view)
    if not rep["ok"]:
        raise Refused(
            rep.get("sentence") or "the file is not complete: it cannot be signed off"
        )
    todo = undecided(view)
    if todo:
        raise Refused(
            f"{len(todo)} comment(s) are not decided yet: decide each, or accept the rest",
            todo,
        )
    if code not in comparison.review_codes():
        raise Refused(
            "the review code is one of: " + ", ".join(comparison.review_codes())
        )
    statement = " ".join((statement or "").split())[:300] or None
    at = _now()
    name = _name(conn, actor)
    try:
        sheet, counts = aim_review_contractor.build(
            view, signed_by=name, signed_at=at, code=code
        )
    except aim_review_contractor.NotIssuable as exc:
        raise Refused(
            "the contractor copy cannot be issued yet: " + str(exc), exc.blockers
        ) from exc
    signoff_id = str(uuid.uuid4())
    with conn:
        conn.execute(
            f"INSERT INTO {SIGNOFFS} (id, run_id, paper_document_id, signed_by, signed_at, review_code, statement, counts_json, decisions_digest, team_sha256)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (signoff_id, run["run_id"], run["paper_document_id"], actor, at, code, statement, json.dumps(counts, sort_keys=True),
             digest(conn, run["run_id"]), hashlib.sha256(_data).hexdigest()),
        )  # fmt: skip
        conn.execute(
            f"INSERT INTO {ISSUED} (id, run_id, signoff_id, filename, sha256, content, issued_by, issued_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                str(uuid.uuid4()),
                run["run_id"],
                signoff_id,
                "contractor-copy.xlsx",
                hashlib.sha256(sheet).hexdigest(),
                sheet,
                actor,
                at,
            ),
        )
        aim_review_decisions.audit(
            conn,
            actor,
            AUDIT,
            run["paper_document_id"],
            {"run": run["run_id"], "code": code, **counts},
            at=at,
        )
    return status(conn, run, view)


def issued_copy(conn, run: dict, view: dict) -> bytes:
    """The contractor copy kept at the latest sign-off, byte for byte. Raises `Refused` when the run is not signed or changed since."""
    st = status(conn, run, view)
    if st["state"] == NOT_SIGNED:
        raise Refused(NOT_SIGNED_WORDS)
    if st["state"] == CHANGED:
        raise Refused(CHANGED_WORDS)
    row = latest(conn, run["run_id"])
    copy = conn.execute(
        f"SELECT content FROM {ISSUED} WHERE signoff_id = ? ORDER BY issued_at DESC, rowid DESC LIMIT 1",
        (row["id"],),
    ).fetchone()
    if copy is None:
        raise Refused(NOT_SIGNED_WORDS)
    return bytes(copy["content"])
