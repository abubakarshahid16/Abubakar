"""Order 119.1 (117a item 4): the screen's contract types are written from the
backend's own models, and a difference between the two fails.

`scripts/gen_contract_types.py` renders every `contracts/generated/*.ts` it
registers - the run summary, and since order 133 the CRS issue gate, the
review finding, the runs list and a run's standards list, plus the review
tiers' rule data; CI runs it with `--check`. These tests hold each committed
file to its source and prove the check fails on a mismatch either way: the
file edited by hand, or the model changed without regenerating. Order 133
also holds `contracts/types.ts` to having no hand-written copy of a type that
is generated.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import sys
from dataclasses import replace
from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel

REPO = Path(__file__).resolve().parents[2]
TYPES_TS = REPO / "contracts" / "types.ts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gen = _load("gen_contract_types")
MODULES = {module.filename: module for module in gen.modules()}
ALL = (*gen.modules(), *gen.data_modules())
RUN_SUMMARY = MODULES["run_summary.ts"]
CRS_ISSUE = MODULES["crs_issue.ts"]
REVIEW_RUNS = MODULES["review_runs.ts"]


def _ts_names(module) -> list[str]:
    """Every TypeScript name a model module exports: models and unions."""
    return [ts for _, ts in module.models] + [ts for _, ts in module.unions]


def test_every_generated_module_is_registered():
    on_disk = {path.name for path in gen.GENERATED.glob("*.ts")}
    assert on_disk == {module.filename for module in ALL}
    assert {
        "crs_issue.ts",
        "review_findings.ts",
        "review_runs.ts",
        "run_standards.ts",
    } <= set(MODULES)
    assert sum(len(module.models) for module in MODULES.values()) == 6 + 16


@pytest.mark.parametrize("module", ALL, ids=lambda module: module.filename)
def test_the_committed_file_is_what_its_source_renders(module):
    assert gen.drift(module) == []


def test_the_check_passes_on_the_committed_files():
    assert gen.main(["--check"]) == 0


@pytest.mark.parametrize("module", ALL, ids=lambda module: module.filename)
def test_a_hand_edit_to_a_generated_file_is_drift(module, tmp_path):
    committed = (gen.GENERATED / module.filename).read_text(encoding="utf-8")
    edited = committed.replace("export ", "export declare ", 1)
    assert edited != committed
    (tmp_path / module.filename).write_text(edited, encoding="utf-8")

    diff = "".join(gen.drift(module, tmp_path))

    assert "\n-export declare " in diff and "\n+export " in diff


def test_a_hand_edit_to_a_union_is_drift(tmp_path):
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


def test_a_field_added_to_the_issue_gate_without_regenerating_is_drift():
    from app import schemas

    class CrsIssueGate(schemas.CrsIssueGate):
        #: a field the screen has not been told about
        new_blocker_count: int

    models = tuple(
        (CrsIssueGate if model is schemas.CrsIssueGate else model, name)
        for model, name in CRS_ISSUE.models
    )

    diff = "".join(gen.drift(replace(CRS_ISSUE, models=models)))

    assert "+  /** a field the screen has not been told about */" in diff
    assert "+  new_blocker_count: number;" in diff


def test_a_rule_label_changed_without_regenerating_is_drift(tmp_path):
    tiers = _load("gen_tier_rules")
    rules = json.loads(Path(tiers.RULES).read_text(encoding="utf-8"))
    rules["labels"] = [
        "Comment!" if label == "Comment" else label for label in rules["labels"]
    ]
    edited = tmp_path / "review_tiers.json"
    edited.write_text(json.dumps(rules), encoding="utf-8")
    committed = (gen.GENERATED / tiers.FILENAME).read_text(encoding="utf-8")

    assert tiers.render(edited) != committed
    shutil.copy(tiers.RULES, tmp_path / "same.json")
    assert tiers.render(tmp_path / "same.json") == committed


def test_a_dict_field_keeps_its_screen_type_and_its_null():
    text = gen.render(RUN_SUMMARY)
    assert "  page_coverage?: PageCoverage | null;" in text
    assert (
        'import type { AiStepNumbers, PageCoverage, RequirementSplit, ReviewRunSummary } from "../types";'
        in text
    )


def test_a_schemas_dict_field_takes_its_screen_type_from_the_module():
    """`schemas.py` may not grow, so its `dict` fields are named in
    `Module.ts_types`; each name is a type `contracts/types.ts` exports."""
    text = gen.render(REVIEW_RUNS)
    assert "  by_status: StatusCounts;" in text
    assert "  completeness?: ReviewRunCompleteness | null;" in text
    assert "  table_values_not_compared: TableValuesNotCompared[];" in text
    types_ts = TYPES_TS.read_text(encoding="utf-8")
    for _, ts in REVIEW_RUNS.ts_types:
        name = re.match(r"\w+", ts).group(0)
        assert re.search(rf"^export (interface|type) {name}\b", types_ts, re.M), name


def test_a_sent_default_is_required_only_where_the_module_says_so():
    runs = gen.render(REVIEW_RUNS)
    assert "  equipment_tags: string[];" in runs
    assert "  findings_total: number;" in runs
    assert "  recommended_code?: string | null;" in runs
    gate = gen.render(CRS_ISSUE)
    assert "  checked_pages?: number[];" in gate


def test_a_trailing_field_comment_is_the_field_jsdoc():
    text = gen.render(CRS_ISSUE)
    assert "  /** order 127: the pages left to tick */\n  unread_pages:" in text


@pytest.mark.parametrize("module", gen.modules(), ids=lambda module: module.filename)
def test_no_hand_written_copy_of_a_generated_type_is_left(module):
    """Order 133: a generated type lives in its generated file only. A copy
    left in `contracts/types.ts` would drift from the model unseen."""
    types_ts = TYPES_TS.read_text(encoding="utf-8")
    generated = (gen.GENERATED / module.filename).read_text(encoding="utf-8")
    for name in _ts_names(module):
        declared = re.compile(rf"^export (interface|type) {name}\b", re.M)
        assert not declared.search(types_ts), f"{name} is hand-written in types.ts"
        assert len(declared.findall(generated)) == 1, name
    assert f'export * from "./generated/{module.filename[:-3]}";' in types_ts


def test_a_referenced_model_that_is_not_registered_fails_loudly():
    class Inner(BaseModel):
        x: int

    class Outer(BaseModel):
        inner: Inner

    with pytest.raises(SystemExit, match="Inner is referenced but not registered"):
        gen.render(gen.Module("t.ts", "t.py", ((Outer, "Outer"),)))
