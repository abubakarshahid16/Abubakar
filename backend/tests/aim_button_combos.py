"""Order 14, piece B: a fixed sample of `review_engine.Facts` combinations, and one plain answer per combination, so the old
engine's resolver can be compared with the answers recorded from `origin/main` (c71aaae7) before the general review existed."""

from __future__ import annotations

import itertools
import json
import random

KINDS = (None, "datasheet", "procedure", "contract", "specification", "drawing")
PROVIDERS = ("ollama", "claude", "per_task", "other")
FLAGS = (
    "kind_guess", "agent_enabled", "agent_engine_claude", "step_engine_claude", "lane_open", "blocked", "paper_approved",
    "is_contract", "contract_yes", "scored_allowed", "kind_scored", "caps_ok", "books_ok", "local_ai", "rules_for_kind",
)  # fmt: skip
CHOICES = ("automatic", "claude", "local")
SAMPLE = 6000
SEED = 1418


def combos():
    """Every kind x provider x choice with all flags on, all off, each flag alone flipped; then a fixed random sample."""
    out = []
    for kind, provider, choice in itertools.product(KINDS, PROVIDERS, CHOICES):
        for base in (True, False):
            out.append(
                (
                    choice,
                    {"kind": kind, "provider": provider, **dict.fromkeys(FLAGS, base)},
                )
            )
            for flag in FLAGS:
                kw = {"kind": kind, "provider": provider, **dict.fromkeys(FLAGS, base)}
                kw[flag] = not base
                out.append((choice, kw))
    rnd = random.Random(SEED)
    for _ in range(SAMPLE):
        kw = {"kind": rnd.choice(KINDS), "provider": rnd.choice(PROVIDERS)}
        kw.update({f: rnd.random() < 0.5 for f in FLAGS})
        out.append((rnd.choice(CHOICES), kw))
    return out


def answer(module, choice: str, kw: dict) -> str:
    """The resolver's whole answer for one combination, as one line of sorted JSON."""
    plan = module.decide(choice, module.Facts(**kw))
    return json.dumps(plan.as_dict(), sort_keys=True) + "\n"
