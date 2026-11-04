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

import contextlib
import hashlib
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

    def complete(self, messages: list[dict], tool_specs: list[dict]) -> dict:  # noqa: ARG002
        self.calls.append([dict(m) for m in messages])
        if not self.script:
            raise RuntimeError("fake provider script exhausted")
        nxt = self.script.pop(0)
        out = dict(nxt(messages) if callable(nxt) else nxt)
        out.setdefault("usd", self.usd)
        return out


CANON_KEYS = (
    "item",
    "doc",
    "color",
    "page",
    "doc_quote",
    "clause_quote",
    "standard",
    "clause",
    "action",
    "priority",
    "figures",
    "reason",
)
PRIORITIES = ("must", "should", "nice")


def yellow(reason: str, item: dict | None = None) -> dict:
    """The ask-the-engineer finding."""
    return {
        "item": (item or {}).get("id"),
        "doc": (item or {}).get("doc"),
        "color": "YELLOW",
        "action": "ask the engineer",
        "priority": "should",
        "reason": words(reason),
    }


def _page_ok(page: Any) -> bool:
    if isinstance(page, bool):
        return False
    if isinstance(page, int):
        return page >= 1
    return isinstance(page, str) and page.strip().isdigit() and int(page) >= 1


def check_final(finding: Any) -> dict:
    """Honesty invariants. New dict with canonical keys only; never raises.

    Confidence is never sent at all (it is dropped, whatever its value).
    """
    if not isinstance(finding, dict):
        return yellow("wrong shape")
    out = {k: finding[k] for k in CANON_KEYS if k in finding}
    colour = out.get("color")
    colour = colour.strip().upper() if isinstance(colour, str) else None
    if colour not in COLOURS:
        return {**yellow("wrong shape"), "item": out.get("item"), "doc": out.get("doc")}
    out["color"] = colour
    verdict = finding.get("verdict")
    if verdict is not None and str(verdict).strip().upper() != colour:
        out.update(
            color="YELLOW",
            reason=words("color and verdict differ"),
            action=out.get("action") or "ask the engineer",
        )
        return out
    if out.get("priority") not in PRIORITIES:
        out.pop("priority", None)
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
            "reason": words("downgraded from GREEN: " + reason),
            "action": out.get("action") or "ask the engineer",
        }
    )
    return out


def _specs(toolbox: Any) -> list[dict]:
    """The toolbox's own TOOL_SPECS; the agent_tools module's only if it has none."""
    specs = getattr(toolbox, "TOOL_SPECS", None)
    if not specs:
        try:
            from app import agent_tools

            specs = getattr(agent_tools, "TOOL_SPECS", None)
        except ImportError:
            specs = None
    return list(specs or [])


def _run_tool(toolbox: Any, name: str, args: Any) -> dict:
    if not isinstance(args, dict):
        return {"ok": False, "result": {"error": "bad arguments"}, "cites": []}
    try:
        res = toolbox.run(name, args)
    except Exception as exc:  # noqa: BLE001 - a tool failure is a result the model sees
        # recorded: the failure is counted in the finding, never raised
        return {"ok": False, "result": {"error": type(exc).__name__}, "cites": []}
    return res if isinstance(res, dict) else {"ok": False, "result": {}, "cites": []}


def _inner(res: dict) -> dict:
    inner = res.get("result") if isinstance(res, dict) else None
    return inner if isinstance(inner, dict) else {}


def _accepted(res: dict) -> bool:
    inner = _inner(res)
    verdict = str(inner.get("verdict") or inner.get("status") or "").lower()
    return bool(res.get("ok")) and (
        verdict == "accepted" or inner.get("accepted") is True
    )


def _ask_engineer(toolbox: Any, item: dict, reason: str) -> None:
    try:
        toolbox.run("ask_engineer", {"item": item.get("id"), "reason": words(reason)})
    except Exception:  # noqa: BLE001 - best effort; the finding is already YELLOW
        # recorded: the failure is counted in the finding, never raised
        return


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


def _quote_hash(finding: dict) -> str:
    text = str(finding.get("doc_quote")) + "|" + str(finding.get("clause_quote"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def finding_ref(finding: Any) -> dict:
    """What a checkpoint may keep of a finding: numbers, colour, a hash of the quotes. No quote text."""
    if not isinstance(finding, dict):
        return {}
    ref = {k: v for k, v in agent_trace.safe_args(finding).items() if k != "other_keys"}
    if finding.get("color") in COLOURS:
        ref["color"] = finding["color"]
    if finding.get("priority") in PRIORITIES:
        ref["priority"] = finding["priority"]
    ref["item"] = str(finding.get("item"))
    ref["quote_hash"] = _quote_hash(finding)
    return ref


def _saved(name: str, args: Any, res: dict, guard: Any = words) -> dict:
    """The checkpoint entry of a side-effect call: verdict and reason words, never quote text."""
    inner = _inner(res)
    out = {
        "ok": bool(res.get("ok")),
        "accepted": _accepted(res),
        "verdict": str(inner.get("verdict") or "")[:12],
        "reason": guard(inner.get("reason")),
    }
    if name == "record_finding" and isinstance(args, dict):
        out["finding"] = finding_ref(args.get("finding"))
    return out


def _kept_args(name: str, args: Any) -> tuple[dict, bool]:
    """Arguments a checkpoint may keep: only reference numbers/ids; else the step is not re-run."""
    if name in agent_trace.SIDE_EFFECT_TOOLS or not isinstance(args, dict):
        return {}, False
    safe = agent_trace.safe_args(args)
    return (safe, False) if "other_keys" in safe else (safe, True)


class _ItemRun:
    """State of one item's loop; methods are the loop's small steps."""

    def __init__(
        self, item, skill_item, toolbox, provider, max_steps, usd_cap, trace, sink=None
    ):
        self.item, self.toolbox, self.provider = item, toolbox, provider
        self.max_steps, self.usd_cap, self.trace = max_steps, usd_cap, trace
        self.id, self.doc = item.get("id"), item.get("doc")
        self.sink = sink if sink is not None else (trace.sink if trace else None)
        self.specs = _specs(toolbox)
        self.names = {sp.get("name") for sp in self.specs}
        self.messages = _initial(item, skill_item)
        self.calls = trace.load_checkpoint(self.id) if trace else []
        self.usd, self.step = 0.0, 0
        self.finding: dict | None = None
        self.why = ""

    def _log(self, name, args, res, reason, secs, verified="", replayed=False):
        if self.trace:
            self.trace.step(
                doc=self.doc,
                item_id=self.id,
                step=self.step,
                tool=name,
                args=args,
                result=res,
                verified=verified,
                seconds=secs,
                reason=reason,
                replayed=replayed,
            )

    def _add(self, name, args, reason, res):
        self.messages.append(
            {
                "role": "assistant",
                "content": {"tool": name, "args": args, "reason": reason},
            }
        )
        self.messages.append({"role": "tool", "name": name, "content": res})

    def _replay_side_effect(self, name, call):
        """A saved record_finding / ask_engineer is not run again; accepted ends the item."""
        saved = call.get("saved") or {}
        res = {
            "ok": bool(saved.get("ok")),
            "result": {k: saved.get(k) for k in ("verdict", "accepted", "reason")},
            "cites": [],
        }
        if name == "record_finding" and saved.get("accepted"):
            stored = self.sink.get(self.id) if self.sink else None
            if stored is not None:
                self.finding = stored
            else:
                self.finding = {**(saved.get("finding") or {}), "doc": self.doc}
                self.finding["reason"] = words(saved.get("reason"))
            self.why = "recorded"
        elif name == "ask_engineer" and saved.get("ok"):
            self.finding = yellow(
                saved.get("reason") or "asked the engineer", self.item
            )
            self.why = "asked the engineer"
        return res

    def replay(self):
        """Saved steps: no model call, no cost repeated, side-effect tools never run again."""
        for call in self.calls:
            self.step += 1
            self.usd += float(call.get("usd") or 0.0)
            name, args = call["tool"], call.get("args") or {}
            if name in agent_trace.SIDE_EFFECT_TOOLS:
                res = self._replay_side_effect(name, call)
            elif call.get("rerun"):
                res = _run_tool(self.toolbox, name, args)
            else:
                res = {
                    "ok": False,
                    "result": {
                        "note": "result not kept after a restart; ask again if needed"
                    },
                    "cites": [],
                }
            self._add(name, args, call.get("reason"), res)
            self._log(name, args, res, call.get("reason"), 0.0, replayed=True)
            if self.finding is not None:
                return

    def limit(self) -> str:
        if self.usd >= self.usd_cap:
            return "usd cap"
        return "step limit" if self.step >= self.max_steps else ""

    def ask_model(self):
        self.step += 1
        t0 = time.time()
        try:
            reply = self.provider.complete(self.messages, self.specs)
        except Exception as exc:  # noqa: BLE001 - any provider failure ends in YELLOW
            # recorded: the failure is counted in the finding, never raised
            self.finding = yellow("provider error " + type(exc).__name__, self.item)
            self.why = "provider error"
            return None, 0.0, 0.0
        cost = float(reply.get("usd") or 0.0) if isinstance(reply, dict) else 0.0
        self.usd += cost
        if self.trace:
            self.trace.add_spend(cost)
        return reply, cost, time.time() - t0

    def _safe(self, reason):
        """A reason fit for a file: the trace's guard (raw quote marks, 13-word copies), else the word cap."""
        if self.trace:
            return self.trace.clean_reason(self.id, reason)
        return words(reason)

    def save(self, name, args, res, reason, cost):
        kept, rerun = _kept_args(name, args)
        call = {
            "tool": name,
            "args": kept,
            "rerun": rerun,
            "reason": self._safe(reason),
            "usd": cost,
        }
        if name in agent_trace.SIDE_EFFECT_TOOLS:
            call["saved"] = _saved(name, args, res, self._safe)
        self.calls.append(call)
        if self.trace:
            self.trace.save_checkpoint(self.id, self.calls)

    def unknown_tool(self, name, secs):
        """A tool the toolbox does not list ends the item YELLOW, with a PROBLEM line."""
        self.finding = yellow("unknown tool", self.item)
        self.why = "unknown tool"
        if self.trace:
            self.trace.problem(
                f"unknown tool {words(name, 2)}", doc=self.doc, item_id=self.id
            )
        self._log("unknown", {}, {"ok": False}, "unknown tool", secs)

    def _action(self, reply):
        """(tool name, args, reason) of a reply; a final goes through record_finding."""
        if "final" in reply:
            args = {"finding": self._own(check_final(reply["final"]))}
            return "record_finding", args, "final"
        name, args = reply["tool"], reply.get("args") or {}
        if name == "record_finding" and isinstance(args, dict):
            args = {**args, "finding": self._own(check_final(args.get("finding")))}
        return name, args, str(reply.get("reason") or "")

    def _own(self, finding):
        finding.setdefault("item", self.id)
        finding.setdefault("doc", self.doc)
        return finding

    def one_step(self):
        reply, cost, secs = self.ask_model()
        if self.finding is not None:
            return
        if not isinstance(reply, dict) or not ("final" in reply or "tool" in reply):
            bad = {"ok": False, "error": "wrong reply shape"}
            self.messages.append({"role": "tool", "name": "loop", "content": bad})
            self._log("loop", {}, {"ok": False}, "wrong reply shape", secs)
            self.save("loop", {}, bad, "wrong reply shape", cost)
            return
        name, args, reason = self._action(reply)
        if name not in self.names:
            self.unknown_tool(name, secs)
            return
        t1 = time.time()
        res = _run_tool(self.toolbox, name, args)
        self._add(name, args, reason, res)
        accepted = name == "record_finding" and _accepted(res)
        self._log(
            name,
            args,
            res,
            reason,
            secs + time.time() - t1,
            "finding accepted by code" if accepted else "",
        )
        self.save(name, args, res, reason, cost)
        if accepted:
            self.finding, self.why = args["finding"], "recorded"
            if self.sink is not None and not self.sink.has(self.id):
                self.sink.add(self.id, self.finding)
        elif name == "ask_engineer" and res.get("ok"):
            asked = str(args.get("reason") or "asked the engineer")
            self.finding, self.why = yellow(asked, self.item), "asked the engineer"
        return

    def run(self) -> dict:
        self.replay()
        while self.finding is None:
            if reason := self.limit():
                self.finding, self.why = yellow(reason, self.item), reason
                _ask_engineer(self.toolbox, self.item, reason)
                break
            self.one_step()
        if self.trace:
            self.trace.finish_item(
                doc=self.doc,
                item_id=self.id,
                finding=self.finding,
                why=self.why,
                usd=self.usd,
                steps=self.step,
            )
        return {
            "finding": self.finding,
            "steps": self.step,
            "usd": self.usd,
            "why": self.why,
        }


def run_item(
    item: dict,
    skill_item: Any,
    toolbox: Any,
    provider: Provider,
    *,
    max_steps: int = MAX_STEPS,
    usd_cap: float,
    trace: agent_trace.TraceWriter | None = None,
    sink: agent_trace.FindingSink | None = None,
) -> dict:
    """Run one item: {"finding", "steps", "usd", "why"}; resumes from saved calls.

    Accepted findings are persisted in the run's FindingSink (the trace's own when none is given)."""
    run = _ItemRun(item, skill_item, toolbox, provider, max_steps, usd_cap, trace, sink)
    return run.run()


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
    # The tools helper's ToolBox(ctx) reads ctx.findings: one persistent sink per run.
    target = getattr(toolbox, "ctx", None) or toolbox
    with contextlib.suppress(AttributeError):
        target.findings = trace.sink
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
    if usd_cap <= 0:
        return {str(i.get("id")): yellow("usd cap", i) for i in mine}
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
            reply = provider.complete(msgs, _specs(toolbox))
        except Exception:  # noqa: BLE001 - a failed look leaves the items YELLOW
            # recorded: the failure is counted in the finding, never raised
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
