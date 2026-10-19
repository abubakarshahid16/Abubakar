"""Order 119.1 (117a item 4): the screen's run-summary types are written from
the backend's own models, and a difference between the two fails.

`scripts/gen_contract_types.py` renders `contracts/generated/run_summary.ts`
from `app/api/run_summary.py`; CI runs it with `--check`. These tests hold the
committed file to the model and prove the check fails on a mismatch either
way: the file edited by hand, or the model changed without regenerating.
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import replace
from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel

REPO = Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location(
        "gen_contract_types", REPO / "scripts" / "gen_contract_types.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gen = _load()
(RUN_SUMMARY,) = gen.modules()


def test_the_committed_file_is_what_the_backend_models_render():
    assert gen.drift(RUN_SUMMARY) == []
    assert gen.main(["--check"]) == 0


def test_a_hand_edit_to_the_generated_file_is_drift(tmp_path):
    committed = (gen.GENERATED / RUN_SUMMARY.filename).read_text(encoding="utf-8")
    edited = committed.replace('"unit unknown"', '"unit unclear"')
    assert edited != committed
    (tmp_path / RUN_SUMMARY.filename).write_text(edited, encoding="utf-8")

    diff = "".join(gen.drift(RUN_SUMMARY, tmp_path))

    assert "-export type RunSummaryTierReason = " in diff and "unit unclear" in diff
    assert "+export type RunSummaryTierReason = " in diff and "unit unknown" in diff


def test_a_reason_added_on_the_backend_without_regenerating_is_drift():
    from app.api import run_summary as rs

    class TierRow(rs.TierRow):
        reason: Literal["page not read", "a new reason"] | None = None

    models = tuple(
        (TierRow if model is rs.TierRow else model, name)
        for model, name in RUN_SUMMARY.models
    )

    diff = "".join(gen.drift(replace(RUN_SUMMARY, models=models)))

    assert (
        '+export type RunSummaryTierReason = "page not read" | "a new reason";' in diff
    )


def test_a_dict_field_keeps_its_screen_type_and_its_null():
    text = gen.render(RUN_SUMMARY)
    assert "  page_coverage?: PageCoverage | null;" in text
    assert (
        'import type { AiStepNumbers, PageCoverage, RequirementSplit, ReviewRunSummary } from "../types";'
        in text
    )


def test_a_referenced_model_that_is_not_registered_fails_loudly():
    class Inner(BaseModel):
        x: int

    class Outer(BaseModel):
        inner: Inner

    with pytest.raises(SystemExit, match="Inner is referenced but not registered"):
        gen.render(gen.Module("t.ts", "t.py", ((Outer, "Outer"),)))
