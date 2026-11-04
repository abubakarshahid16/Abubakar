"""The agent loop for the proof test (#1690, part of #805). Behind `AGENT_REVIEW_ENABLED` (off by default).

think -> ask for one tool -> code runs it -> look at the result -> repeat, at most `max_steps` times per item.
The ONLY model dependency is the `Provider` protocol: `complete(messages, tool_specs)` returns one dict,
either {"tool", "args", "reason"} or {"final": {...finding...}}, plus "usd" (what that call cost). A Claude provider
owns its metering (`claude_spend.metered` through `reader_transport`); this module never opens a socket.

The loop only ever ends in a finding. Honesty invariants (CLAUDE.md rule 4) are enforced in `check_final`:
colour GREEN/YELLOW/RED only; GREEN needs a document quote and a page; "not mentioned" is never GREEN; confidence is
never "high"; a wrong shape is YELLOW. A finding the toolbox refuses is not recorded: the loop retries inside the step
limit, then falls to a YELLOW ask-the-engineer finding.
"""

from __future__ import annotations

import re
import time
from typing import Any, Protocol

from app import agent_trace
from app.agent_trace import words

COLOURS = ("GREEN", "YELLOW", "RED")
MAX_STEPS = 15
TOOL_NAMES = (
    "open_page",
    "search",
    "get_clause",
    "compare_number",
    "record_finding",
    "ask_engineer",
)
_NOT_MENTIONED = re.compile(
    r"\bnot\s+(mentioned|stated|found|specified|addressed|given)\b", re.I
)


class Provider(Protocol):
    def complete(self, messages: list[dict], tool_specs: list[dict]) -> dict: ...


class FakeProvider:
    """Test provider: replays a script (dicts or callables of messages). Costs `usd` per call."""

    def __init__(self, script: list, usd: float = 0.0) -> None:
        self.script = list(script)
        self.usd = usd
        self.calls: list[list[dict]] = []

    def complete(self, messages: list[dict], tool_specs: list[dict]) -> dict:
        self.calls.append([dict(m) for m in messages])
        if not self.script:
            raise RuntimeError("fake provider script exhausted")
        nxt = self.script.pop(0)
        out = dict(nxt(messages) if callable(nxt) else nxt)
        out.setdefault("usd", self.usd)
        return out


def yellow(reason: str, item: dict | None = None) -> dict:
    """The ask-the-engineer finding."""
    return {
        "color": "YELLOW",
        "action": "ask the engineer",
        "reason": words(reason),
        "item": (item or {}).get("id"),
    }


def _page_ok(page: Any) -> bool:
    if isinstance(page, bool):
        return False
    if isinstance(page, int):
        return page >= 1
    return isinstance(page, str) and page.strip().isdigit() and int(page) >= 1


def check_final(finding: Any) -> dict:
    """Apply the honesty invariants. Returns a new dict; never raises."""
    if not isinstance(finding, dict):
        return yellow("wrong shape")
    out = dict(finding)
    colour = out.get("color")
    colour = colour.strip().upper() if isinstance(colour, str) else None
    if colour not in COLOURS:
        return {**yellow("wrong shape"), "item": out.get("item")}
    out["color"] = colour
    if str(out.get("confidence", "")).strip().lower() == "high":
        out.pop("confidence")
    if colour == "GREEN":
        quote = out.get("doc_quote")
        if not (isinstance(quote, str) and quote.strip() and _page_ok(out.get("page"))):
            return _down(out, "no document quote and page")
        text = " ".join(str(v) for v in out.values() if isinstance(v, str))
        if _NOT_MENTIONED.search(text):
            return _down(out, "not mentioned is not compliant")
    return out


def _down(finding: dict, reason: str) -> dict:
    out = dict(finding)
    out.update(
        {
            "color": "YELLOW",
            "downgraded_from": "GREEN",
            "reason": words(reason),
            "action": out.get("action") or "ask the engineer",
        }
    )
    return out


def _tool_spec_names(toolbox: Any) -> list[str]:
    return [s.get("name") for s in getattr(toolbox, "TOOL_SPECS", [])]


def _run_tool(toolbox: Any, name: str, args: Any) -> dict:
    if name not in _tool_spec_names(toolbox) or not isinstance(args, dict):
        return {
            "ok": False,
            "result": {"error": "unknown tool or bad arguments"},
            "cites": [],
        }
    try:
        res = toolbox.run(name, args)
    except Exception as exc:  # a tool failure is a result the model sees, not a crash
        return {"ok": False, "result": {"error": type(exc).__name__}, "cites": []}
    return res if isinstance(res, dict) else {"ok": False, "result": {}, "cites": []}


def _accepted(res: dict) -> bool:
    inner = res.get("result") if isinstance(res.get("result"), dict) else {}
    verdict = str(inner.get("verdict") or inner.get("status") or "").lower()
    return bool(res.get("ok")) and (
        verdict == "accepted" or inner.get("accepted") is True
    )


def _ask_engineer(toolbox: Any, item: dict, reason: str) -> None:
    try:
        toolbox.run("ask_engineer", {"item": item.get("id"), "reason": words(reason)})
    except Exception:
        pass


def _initial(item: dict, skill_item: Any) -> list[dict]:
    return [
        {
            "role": "user",
            "content": {
                "item": item,
                "skill_item": skill_item,
                "instruction": "Review this item with the tools. Finish with a final "
                "finding (GREEN, YELLOW or RED) that quotes the document.",
            },
        }
    ]


def run_item(
    item: dict,
    skill_item: Any,
    toolbox: Any,
    provider: Provider,
    *,
    max_steps: int = MAX_STEPS,
    usd_cap: float,
    trace: agent_trace.TraceWriter | None = None,
) -> dict:
    """Run one item. Returns {"finding", "steps", "usd", "why"}; resumes from the trace's saved calls."""
    item_id, doc = item.get("id"), item.get("doc")
    messages = _initial(item, skill_item)
    calls: list[dict] = trace.load_checkpoint(item_id) if trace else []
    usd, step = 0.0, 0
    finding: dict | None = None
    why = ""

    def save(call: dict) -> None:
        calls.append(call)
        if trace:
            trace.save_checkpoint(item_id, calls)

    def step_done(name, args, res, reason, secs, verified="", replayed=False):
        if trace:
            trace.step(
                doc=doc,
                item_id=item_id,
                step=step,
                tool=name,
                args=args,
                result=res,
                verified=verified,
                seconds=secs,
                reason=reason,
                replayed=replayed,
            )

    for call in calls:  # replay saved steps: no model call, no cost repeated
        step += 1
        usd += float(call.get("usd") or 0.0)
        name, args = call["tool"], call.get("args") or {}
        res = (
            call["result"]
            if name in agent_trace.SIDE_EFFECT_TOOLS
            else _run_tool(toolbox, name, args)
        )
        messages.append(
            {
                "role": "assistant",
                "content": {"tool": name, "args": args, "reason": call.get("reason")},
            }
        )
        messages.append({"role": "tool", "name": name, "content": res})
        step_done(name, args, res, call.get("reason"), 0.0, replayed=True)

    while finding is None:
        if usd >= usd_cap:
            finding, why = yellow("usd cap", item), "usd cap"
            break
        if step >= max_steps:
            finding, why = yellow("step limit", item), "step limit"
            break
        step += 1
        t0 = time.time()
        try:
            reply = provider.complete(
                messages, list(getattr(toolbox, "TOOL_SPECS", []))
            )
        except Exception as exc:
            finding, why = (
                yellow("provider error " + type(exc).__name__, item),
                "provider error",
            )
            break
        secs = time.time() - t0
        cost = float(reply.get("usd") or 0.0) if isinstance(reply, dict) else 0.0
        usd += cost
        if trace:
            trace.add_spend(cost)
        if not isinstance(reply, dict) or not ("final" in reply or "tool" in reply):
            messages.append(
                {
                    "role": "tool",
                    "name": "loop",
                    "content": {"ok": False, "error": "wrong reply shape"},
                }
            )
            step_done("loop", {}, {"ok": False}, "wrong reply shape", secs)
            save(
                {
                    "tool": "loop",
                    "args": {},
                    "result": {"ok": False},
                    "reason": "wrong reply shape",
                    "usd": cost,
                }
            )
            continue
        if "final" in reply:
            name, args = "record_finding", {"finding": check_final(reply["final"])}
            reason = "final"
        else:
            name, args, reason = (
                reply["tool"],
                reply.get("args") or {},
                words(reply.get("reason")),
            )
            if name == "record_finding" and isinstance(args, dict):
                args = {**args, "finding": check_final(args.get("finding"))}
        t1 = time.time()
        res = _run_tool(toolbox, name, args)
        secs += time.time() - t1
        messages.append(
            {
                "role": "assistant",
                "content": {"tool": name, "args": args, "reason": reason},
            }
        )
        messages.append({"role": "tool", "name": name, "content": res})
        keep = res if name in agent_trace.SIDE_EFFECT_TOOLS else None
        verified = (
            "finding accepted by code"
            if name == "record_finding" and _accepted(res)
            else ""
        )
        step_done(name, args, res, reason, secs, verified)
        save(
            {"tool": name, "args": args, "result": keep, "reason": reason, "usd": cost}
        )
        if name == "record_finding" and _accepted(res):
            finding, why = args["finding"], "recorded"
        elif name == "ask_engineer" and res.get("ok"):
            finding, why = (
                yellow(str(args.get("reason") or "asked the engineer"), item),
                "asked the engineer",
            )
    if why in ("step limit", "usd cap"):
        _ask_engineer(toolbox, item, why)
    if trace:
        trace.finish_item(
            doc=doc, item_id=item_id, finding=finding, why=why, usd=usd, steps=step
        )
    return {"finding": finding, "steps": step, "usd": usd, "why": why}


def run_items(
    items: list[dict],
    toolbox: Any,
    provider: Provider,
    trace: agent_trace.TraceWriter,
    *,
    skill_for: Any = None,
    max_steps: int = MAX_STEPS,
    usd_cap_item: float,
    usd_cap_run: float,
) -> dict:
    """Run items in order; completed items (state.json) are skipped; the run cap stops the run, resumable."""
    results: dict[str, dict] = {}
    stopped = ""
    for item in items:
        iid = str(item.get("id"))
        if trace.is_done(iid):
            continue
        if trace.spend >= usd_cap_run:
            stopped = "usd cap for the run"
            trace.problem(stopped)
            break
        trace.set_live(running=iid)
        skill = skill_for(item) if callable(skill_for) else skill_for
        out = run_item(
            item,
            skill,
            toolbox,
            provider,
            max_steps=max_steps,
            usd_cap=min(usd_cap_item, max(0.0, usd_cap_run - trace.spend)),
            trace=trace,
        )
        results[iid] = out
        trace.mark_done(iid, out["finding"].get("color", "not sure"))
    trace.piece_done("run paused" if stopped else "run finished")
    return {"results": results, "stopped": stopped}


# ---- document map and one look per page ---------------------------------------------------------------------------


def build_document_map(pages: Any) -> list[dict]:
    """Page-keyed outline: page number and up to 3 short heading lines. No other text is kept."""
    pairs = (
        sorted(pages.items())
        if isinstance(pages, dict)
        else [(p.get("page"), p.get("text")) for p in pages]
    )
    out = []
    for page, text in pairs:
        heads = []
        for line in str(text or "").splitlines():
            s = line.strip()
            if (
                3 <= len(s) <= 60
                and not s.endswith((".", ",", ";"))
                and len(s.split()) <= 8
                and (s.isupper() or s[0].isdigit() or s.istitle())
            ):
                heads.append(s)
            if len(heads) == 3:
                break
        out.append({"page": page, "headings": heads})
    return out


def items_on_page(items: list[dict], page: int) -> list[dict]:
    return [i for i in items if page == i.get("page") or page in (i.get("pages") or [])]


def answer_open_page(
    items: list[dict],
    page: int,
    toolbox: Any,
    provider: Provider,
    *,
    doc: Any = None,
    usd_cap: float,
    trace: agent_trace.TraceWriter | None = None,
) -> dict[str, dict]:
    """Open `page` ONCE and answer every item that sits on it in one model call. Unanswered items are YELLOW."""
    mine = items_on_page(items, page)
    if not mine:
        return {}
    opened = _run_tool(toolbox, "open_page", {"doc": doc, "page": page})
    answers: dict[str, dict] = {}
    reply: dict = {}
    if opened.get("ok"):
        msgs = [
            {
                "role": "user",
                "content": {
                    "items": mine,
                    "page": page,
                    "page_text": opened.get("result"),
                    "instruction": "Answer every item; final={'findings': [...]}",
                },
            },
        ]
        try:
            reply = provider.complete(msgs, list(getattr(toolbox, "TOOL_SPECS", [])))
        except Exception:
            reply = {}
        if trace:
            trace.add_spend(
                float(reply.get("usd") or 0.0) if isinstance(reply, dict) else 0.0
            )
            trace.step(
                doc=doc,
                item_id=f"page-{page}",
                step=1,
                tool="open_page",
                args={"doc": doc, "page": page},
                result=opened,
                reason=f"one look, {len(mine)} items",
            )
    given = (
        (reply.get("final") or {}).get("findings")
        if isinstance(reply, dict) and isinstance(reply.get("final"), dict)
        else None
    )
    by_id = {str(f.get("item")): f for f in given or [] if isinstance(f, dict)}
    for it in mine:
        raw = by_id.get(str(it.get("id")))
        f = (
            check_final(raw)
            if raw is not None
            else yellow("not answered on the page", it)
        )
        if raw is not None:
            f.setdefault("item", it.get("id"))
            if not _accepted(_run_tool(toolbox, "record_finding", {"finding": f})):
                f = yellow("finding refused", it)
        answers[str(it.get("id"))] = f
    return answers
