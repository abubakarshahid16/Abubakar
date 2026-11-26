"""The fake model of the general review (tests and the dry run): no network, fixed JSON per step built from the material in
the prompt; the send gate is asked, nothing is sent. Moved out of `engine` unchanged (engine stays under 800 lines); importable
as `engine.FakeModel`."""

from __future__ import annotations

import json
import re

from .engine import CallRecord, Meter, StepFailed
from .prompts import build_parts, check_body


def _long_lines(text: str):
    return [ln.strip() for ln in text.splitlines() if len(ln.strip()) >= 25]


#: The fake knowledge step's one item, carried by this paper (a real build writes one or more).
KNOWLEDGE_ITEM = {
    "topic": "fake knowledge item",
    "what_to_check": "fake",
    "applies_when": "always",
    "paper_fields": ["section"],
    "kind": "presence",
    "stands_in_for": "engineering practice",
    "carried_by": "HERE",
}


def _fixed_answer(step: str, prompt: str = "") -> dict | None:
    """The fixed answer of a step that reads no material (the knowledge step, the attack), else None; the local attack keeps
    every item its prompt shows."""
    if step == "aim_attack_items":
        shown = prompt.split("THE ITEMS:")[-1].split("Books:")[0]
        return {"verdicts": [{"id": i, "verdict": "keep", "why": "fake", "what_to_check": ""}
                             for i in re.findall(r'"id": "(C[0-9]+)"', shown)]}  # fmt: skip
    if step == "aim_checklist_knowledge":
        return {"items": [dict(KNOWLEDGE_ITEM)]}
    if step == "aim_attack":
        return {"remove": [], "fix": [], "add": []}
    return None


class FakeModel:
    """No network: fixed JSON per step built from the material in the prompt; the gate is asked, nothing is sent.

    `answers` may give a step's answer (a dict, or a function of (step, cached, prompt)); `fail` makes a step raise; `asked`
    keeps every call's step, model, carries and whether a paper block was cached (for tests)."""

    dry = True

    def __init__(
        self,
        *,
        kind: str = "datasheet",
        equipment_type: str | None = None,
        subject_key: str = "fake",
        answers: dict | None = None,
        fail: dict | None = None,
        meter: Meter | None = None,
    ) -> None:
        self.meter = meter or Meter(cap=0.0)
        self.kind, self.equipment_type, self.subject_key = (
            kind,
            equipment_type,
            subject_key,
        )
        self.answers = dict(answers or {})
        self.fail = dict(fail or {})
        self.asked: list[dict] = []

    def ask(
        self,
        *,
        step: str,
        model: str,
        system: str,
        cached: str | None,
        prompt: str,
        carries: set[str],
        max_tokens: int,
        effort: str | None = None,
    ):
        from app import claude_approved, claude_spend

        with claude_approved.carrying(sorted(carries)):
            refused = claude_approved.refusal()
        body = {
            "model": model,
            "max_tokens": int(claude_spend.output_cap(model, max_tokens)),
            **build_parts(system, cached, prompt, effort),
        }
        problems = check_body(body)
        chars = len(system) + len(cached or "") + len(prompt)
        rec = CallRecord(step=step, model=model, prompt_chars=chars, code="fake")
        self.asked.append(
            {
                "step": step,
                "model": model,
                "carries": frozenset(carries),
                "cached": bool(cached),
                "prompt": prompt,
                "cached_text": cached or "",
            }
        )
        if problems:
            rec.ok, rec.code = False, "bad_shape"
            self.meter.calls.append(rec)
            raise StepFailed(f"{step}: bad_shape ({'; '.join(problems)})")
        if refused is not None:
            rec.ok, rec.code = False, f"refused:{refused[0]}"
            self.meter.calls.append(rec)
            raise StepFailed(f"{step}: stop {refused[0]}")
        self.meter.calls.append(rec)
        if step in self.fail:
            rec.ok, rec.code = False, str(self.fail[step])
            raise StepFailed(f"{step}: {self.fail[step]}")
        given = self.answers.get(step)
        if callable(given):
            return given(step, cached or "", prompt)
        if given is not None:
            return given
        return self.fake_answer(step, cached or "", prompt)

    def fake_answer(self, step: str, cached: str, prompt: str):
        """Deterministic stand-in answers that exercise every code path (quotes found and not found, numbers, labels)."""
        pages = re.findall(r"=== PAGE (\d+) ===\n(.*?)(?=\n=== PAGE|\Z)", cached, re.S)
        if step == "aim_identify":
            n, txt = pages[0]
            q = (_long_lines(txt) or [txt.strip()[:40]])[0][:60]
            return {
                "kind": self.kind,
                "equipment_type": self.equipment_type,
                "subject": "fake subject",
                "subject_key": self.subject_key,
                "service": "",
                "evidence": [{"page": int(n), "quote": q}],
                "cited": [],
            }
        if step == "aim_select":
            ids = re.findall(r'"alias": "(B\d+)"', prompt)[:10]
            return {
                "books": [{"alias": a, "why": "fake", "subjects": "all"} for a in ids],
                "not_held_needed": [],
            }
        if step in ("aim_checklist", "aim_checklist_retry"):
            rules = re.findall(
                r'\{"rule": "(R\d+)", "book": "(B\d+)", "clause": "([^"]*)", "page": (\d+), "text": "((?:[^"\\]|\\.)*)"',
                prompt,
            )
            items = []
            for i, (_rid, b, cl, pg, tx) in enumerate(rules[:4]):
                items.append(
                    {
                        "topic": f"fake {i}",
                        "what_to_check": "fake check",
                        "book": b,
                        "clause": cl,
                        "page": int(pg),
                        "rule_quote": json.loads(f'"{tx}"')[:80],
                        "applies_when": "always",
                        "paper_fields": ["any"],
                        "kind": "presence",
                        "source": "held standard",
                    }
                )
            items.append(
                {
                    "topic": "fake knowledge",
                    "what_to_check": "y",
                    "book": "",
                    "clause": "",
                    "page": None,
                    "rule_quote": "",
                    "applies_when": "always",
                    "paper_fields": ["any"],
                    "kind": "presence",
                    "source": "not from a held standard",
                    "stands_in_for": "an unheld practice",
                }
            )
            return {"items": items}
        if (fixed := _fixed_answer(step, prompt)) is not None:
            return fixed
        if step in ("aim_judge", "aim_checklist_missed"):
            ids = re.findall(r'"id": "([CG]\d+)"', prompt)
            n, txt = pages[0]
            q = (_long_lines(txt) or [txt.strip()[:40]])[0][:50]
            labels = ["Not met", "Question", "Met", "AI opinion", "Does not apply"]
            return {
                "judgments": [
                    {
                        "id": cid,
                        "label": labels[i % len(labels)],
                        "page": int(n),
                        "quote": q,
                        "field": "fake field",
                        "comment": "fake comment",
                    }
                    for i, cid in enumerate(ids)
                ]
            }
        return {}
