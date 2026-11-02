"""The words of the clause review's outcome (#1477): counts with their denominators, split
from `clause_review.py` so that file does not grow. Pure: it fills a status dict, stores nothing."""

from __future__ import annotations


def _results(status: dict, reviewed: int) -> dict:
    """Every outcome out of the applicable requirements; `adds_up` is checked, not assumed."""
    out = {
        "applicable": status["requirements"],
        "reviewed": reviewed,
        "verified_quote": status["verified"],
        "no_passage_found": status["no_evidence"],
        "unverifiable": status["unverified"],
        "unreadable": status["unreadable"],
        "failed": len(status["failed"]),
        "not_reviewed": len(status["not_reviewed"]),
    }
    told = reviewed + out["unreadable"] + out["failed"] + out["not_reviewed"]
    return {**out, "adds_up": told == out["applicable"]}


def _not_ai_reviewed(status: dict) -> str:
    """How many applicable requirements the AI did not review, and each reason. "" when none."""
    over = int(status.get("over_limit") or 0)
    limit = status.get("limit")
    parts = []
    if over:
        parts.append(
            f"{over} over the local engine's limit of {limit} per run (the first {limit} in "
            "standard, page and clause order were taken, not chosen by importance)"
        )
    rest = len(status["not_reviewed"]) - over
    why = status.get("not_reviewed_why")
    if why:
        parts += [f"{count} because {reason}" for reason, count in why.items()]
    elif rest > 0:
        parts.append(f"{rest} because {status['stopped'] or 'they were not reached'}")
    if status["failed"]:
        parts.append(f"{len(status['failed'])} failed (no answer)")
    if status["unreadable"]:
        parts.append(f"{status['unreadable']} with an unreadable answer")
    told = len(status["not_reviewed"]) + len(status["failed"]) + status["unreadable"]
    if not told:
        return ""
    return (
        f"{told} of {status['requirements']} applicable requirement(s) not AI-reviewed: "
        + ", ".join(parts)
    )


def _engine_sentence(status: dict) -> str:
    """The Claude lane's money, or why it was not used. Counts and USD only."""
    if status.get("engine_note"):
        return str(status["engine_note"])
    usd = status.get("usd")
    if not usd:
        return ""
    return (
        f"Claude batch, this run only: USD {usd['charged']:.4f} charged, USD {usd['held']:.4f} held "
        f"at worst case until settled; {status['calls']} ask(s) sent, {status['cache_hits']} "
        f"answered from stored answers at no cost; worst case had all {status['requirements']} been "
        f"sent: USD {usd['worst_case_all']:.2f}"
    )


def fill(status: dict, elapsed: float) -> None:
    """Add the counts and the plain sentence to the run's status (never document text).
    Whole-document mode adds a note: "N of M requirements reviewed; K not reviewed (time
    budget of T s reached); first not reviewed: ..." - not reviewed is never a pass."""
    status["elapsed_seconds"] = round(elapsed, 1)
    status["minutes_per_page"] = round(elapsed / 60 / max(1, status["pages"]), 3)
    status["not_reviewed_count"] = len(status["not_reviewed"])
    read = sum(
        status[k] for k in ("verified", "no_evidence", "unverified", "unreadable")
    )
    # Reviewed: the AI gave an answer that could be read. Unreadable is asked, not reviewed.
    reviewed = read - status["unreadable"]
    status["results"] = _results(status, reviewed)
    status["not_ai_reviewed_count"] = status["requirements"] - reviewed
    left = len(status["not_reviewed"]) + len(status["failed"])
    why = f" ({status['stopped']})" if status["stopped"] else ""
    named = [*status["not_reviewed"], *status["failed"]]
    listed = (
        f": {', '.join(named[:10])}{' ...' if len(named) > 10 else ''}" if named else ""
    )
    kind = f"document kind '{status['kind']}'" + (
        ""
        if status["kind_state"] == "confirmed"
        else f" ({status['kind_state']}, not confirmed)"
    )
    status["not_read_count"] = left
    if status.get("whole_document"):
        # Rule 4: every count with its denominator; not reviewed is never a pass.
        stop = (
            f" ({status['stopped']})"
            if status["stopped"] and status["not_reviewed"]
            else ""
        )
        first = (
            f"; first not reviewed: {', '.join(status['not_reviewed'][:10])}"
            if status["not_reviewed"]
            else ""
        )
        fail = (
            f"; {len(status['failed'])} failed (no answer): {', '.join(status['failed'][:10])}"
            if status["failed"]
            else ""
        )
        status["whole_document_note"] = (
            f"{reviewed} of {status['requirements']} requirements reviewed; "
            f"{len(status['not_reviewed'])} not reviewed{stop}{first}{fail}"
        )
    status["plain"] = (
        f"AI clause review (suggestions only, engineer to confirm): {read} of {status['requirements']} "
        f"requirement(s) read - {status['verified']} with a verified quote, {status['no_evidence']} "
        f"with no passage found, {status['unverified']} with a quote that could not be verified, "
        f"{status['unreadable']} unreadable; {left} not reviewed{why}{listed}; {kind}."
    )
    for sentence in (_not_ai_reviewed(status), _engine_sentence(status)):
        if sentence:
            status["plain"] += f" {sentence}."
    if not status["results"]["adds_up"]:
        status["plain"] += " THE COUNTS DO NOT ADD UP - report this run."
    if status.get("whole_document_note"):
        status["plain"] += f" {status['whole_document_note']}."
