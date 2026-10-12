"""#845 (Stage B, #805 rule 7 "AI numbers first"): a finished run's AI
numbers, read from what the run stored. No model is called here.

THE STEPS, EACH WITH ITS OWN DENOMINATOR AND WHERE IT RAN. The reader (how
many pages the AI read, and what became of its readings), the matcher (how
many requirements it was asked about, and what became of its proposals), the
AI engineering check, the AI wording and (#645) the AI clause checks - how
many undecided clause sentences got a proposed check. Each says "local model" or "cloud
model" when the stored record names the engine, and nothing when it does not.

NULL RENDERS AS NOTHING, NEVER 0 (CLAUDE.md rule 4). A step the run holds no
record of is None - a run made before the record existed, or a step that
never ran - and the screen shows nothing for it. A count is only printed
next to what it is out of.
"""
from __future__ import annotations

LOCAL = "local model"
CLOUD = "cloud model"


def where(engine: str | None) -> str | None:
    """'local model' / 'cloud model' from a stored engine or model name
    ('claude', 'claude:<tag>', 'ollama:<tag>'), or None when it names
    neither (an injected test engine, or nothing recorded)."""
    name = str(engine or "").strip().lower()
    if name.startswith(("claude", "anthropic")):
        return CLOUD
    if name.startswith("ollama"):
        return LOCAL
    return None


def _n(value) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _step(label: str, state: str, lines: list[str], *, engine: str | None = None,
          model: str | None = None, local_instead: str | None = None,
          counts: dict | None = None) -> dict:
    # #791: `counts` are the same numbers the lines print, for the pipeline
    # panel's lights; a count the record does not hold is left out, never 0.
    return {"step": label, "state": state, "where": where(engine or model),
            "model": model, "local_instead": local_instead, "lines": lines,
            "counts": counts or {}}


def _reasons(counts: dict[str, int]) -> str:
    return ", ".join(f"{n} {why}" for why, n in sorted(counts.items()) if n)


def reader(summary: dict | None) -> dict | None:
    """The AI reader, from the reader summary the run kept
    (`requirement_split.reader`, written by `datasheets.reader_summary`)."""
    if not summary:
        return None
    pages = _n(summary.get("pages"))
    if summary.get("engine") == "off":
        return _step("AI reader", "off",
                     [f"Off: the code readers read all {pages} page(s)."])
    read = _n(summary.get("pages_read"))
    left: dict[str, int] = {}
    for why in (summary.get("code_only") or {}).values():
        left[str(why)] = left.get(str(why), 0) + 1
    timed_out = len(summary.get("timed_out") or [])
    lines = [f"{read} of {pages} page(s) read by the AI"
             + (f"; {timed_out} timed out" if timed_out else "")
             + (f"; {sum(left.values())} left to the code readers ({_reasons(left)})" if left else "")
             + "."]
    agreed, conflicts, ai_only = (_n(summary.get(k)) for k in ("agreed", "conflicts", "ai_only"))
    merged = agreed + conflicts + ai_only
    lines.append(f"Of {merged} value(s) the AI read: {agreed} agreed with the code readers, "
                 f"{conflicts} in conflict, {ai_only} read by the AI only.")
    if isinstance(summary.get("refused_by_gate"), int):
        refused = summary["refused_by_gate"]
        lines.append(f"{refused} of {refused + merged} AI reading(s) refused by the code gate.")
    state = "incomplete" if summary.get("stopped") or summary.get("unavailable") else "ran"
    counts = {"pages": pages, "pages_read": read, "timed_out": timed_out,
              "left_to_code": sum(left.values()), "agreed": agreed, "conflicts": conflicts,
              "ai_only": ai_only}
    if isinstance(summary.get("refused_by_gate"), int):
        counts["refused_by_gate"] = summary["refused_by_gate"]
    return _step("AI reader", state, lines, engine=summary.get("engine"),
                 model=summary.get("model"), counts=counts)


def matcher(counts: dict | None) -> dict | None:
    """The AI matcher, from the run outcome's `ai_matcher`
    (`comparison.matcher_summary`)."""
    if not counts:
        return None
    if not counts.get("enabled"):
        return _step("AI matcher", "off", ["Off: requirements were paired by the match rules only."])
    sent, asked, proposed = (_n(counts.get(k)) for k in ("sent", "asked", "proposed"))
    not_asked = []
    if counts.get("no_candidates"):
        not_asked.append(f"{counts['no_candidates']} had no candidate field")
    if counts.get("not_asked_budget"):
        not_asked.append(f"{counts['not_asked_budget']} not asked: the call budget was spent")
    lines = [f"Asked about {asked} of {sent} requirement(s) the match rules could not pair"
             + (f" ({'; '.join(not_asked)})" if not_asked else "") + "."]
    used, held, refused = (_n(counts.get(k)) for k in ("used", "held", "refused_by_rule"))
    lines.append(f"Of {proposed} pairing(s) proposed: {used} used ({held} held for the engineer), "
                 f"{refused} refused by a match rule.")
    other = {k: v for k, v in (counts.get("other") or {}).items() if v}
    lines.append(f"Of {asked} asked: {proposed} proposed, {_n(counts.get('declined'))} declined, "
                 f"{_n(counts.get('unavailable'))} unavailable (time-out or model down)"
                 + (f", {_reasons(other)}" if other else "") + ".")
    state = "incomplete" if counts.get("unavailable") or counts.get("not_asked_budget") else "ran"
    return _step("AI matcher", state, lines, engine=counts.get("engine"), model=counts.get("model"),
                 counts={k: _n(counts.get(k)) for k in (
                     "sent", "asked", "proposed", "used", "held", "refused_by_rule",
                     "declined", "unavailable", "not_asked_budget")})


def engineering_check(status: dict | None) -> dict | None:
    """The AI engineering check, from `review_runs.ai_check_status`."""
    if not status:
        return None
    if not status.get("ran"):
        return _step("AI engineering check", "not run",
                     [f"Did not run: {status.get('reason') or 'no reason recorded'}."])
    plain = status.get("plain") or (
        f"{_n(status.get('kept_items'))} of {_n(status.get('proposed_items'))} proposed item(s) kept.")
    return _step("AI engineering check", "ran" if status.get("complete") else "incomplete",
                 [plain], model=status.get("model"), local_instead=status.get("local_instead"),
                 counts={"proposed": _n(status.get("proposed_items")),
                         "kept": _n(status.get("kept_items"))})


def wording(summary: dict | None) -> dict | None:
    """The AI wording of the CRS rows, from `crs_ai_wording_runs`."""
    if not summary:
        return None
    if not summary.get("enabled"):
        return _step("AI wording", "off", ["Off: the CRS rows keep their template wording."])
    tried, accepted = _n(summary.get("tried")), _n(summary.get("accepted"))
    refused = summary.get("refused") or {}
    lines = [f"Of {tried} row(s) worded: {accepted} kept, {sum(_n(v) for v in refused.values())} "
             "refused by the lock" + (f" ({_reasons(refused)})" if refused else "") + "."]
    if summary.get("not_tried"):
        lines.append(f"{summary['not_tried']} more row(s) not tried (the per-run row cap).")
    if summary.get("stopped"):
        lines.append(f"Stopped: {summary['stopped']}.")
    return _step("AI wording", "incomplete" if summary.get("stopped") else "ran", lines,
                 model=summary.get("model"), local_instead=summary.get("local_instead"),
                 counts={"tried": tried, "accepted": accepted,
                         "refused": sum(_n(v) for v in refused.values()),
                         "not_tried": _n(summary.get("not_tried"))})


def clause_checks(counts: dict | None) -> dict | None:
    """#645 AI clause checks, from the run outcome's
    `requirement_split.clause_checks` (`ai_requirements.propose_checks`).
    Always the local runner's model: standards text stays on this machine."""
    if not counts:
        return None
    from . import ai_requirements

    incomplete = counts.get("could_not_read") or counts.get("not_asked_budget")
    return _step("AI clause checks", "incomplete" if incomplete else "ran",
                 [ai_requirements.report_line(counts)],
                 engine="ollama", model=counts.get("model"),
                 counts={"sentences": _n(counts.get("sentences")), "asked": _n(counts.get("asked")),
                         "proposed": _n(counts.get("proposed")),
                         "refused": sum(_n(v) for v in (counts.get("refused") or {}).values()),
                         "could_not_read": _n(counts.get("could_not_read")),
                         "not_asked_budget": _n(counts.get("not_asked_budget"))})


def for_run(outcome: dict | None, ai_check_status: dict | None,
            wording_summary: dict | None) -> dict | None:
    """The four steps for one run, or None when the run holds no record of
    any of them (the panel is then not shown at all)."""
    outcome = outcome or {}
    steps = {
        "reader": reader((outcome.get("requirement_split") or {}).get("reader")),
        "matcher": matcher(outcome.get("ai_matcher")),
        "engineering_check": engineering_check(ai_check_status),
        "wording": wording(wording_summary),
        "clause_checks": clause_checks((outcome.get("requirement_split") or {}).get("clause_checks")),
    }
    return steps if any(steps.values()) else None
