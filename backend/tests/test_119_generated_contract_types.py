"""Order 119.1 (117a item 4): the screen's contract types are written from the
backend's own models, and a difference between the two fails.

`scripts/gen_contract_types.py` renders every `contracts/generated/*.ts` it
registers - the run summary, and since order 133 the CRS issue gate, the
review finding, the runs list and a run's standards list, plus the review
tiers' rule data; CI runs it with `--check`. These tests hold each committed
file to its source and prove the check fails on a mismatch either way: the
file edited by hand, or the model changed without regenerating. Order 133
also holds `contracts/types.ts` to having no hand-written copy of a type that
is generated, and holds every hand-written mirror there (an interface named
after a backend model) to declaring only fields that model sends.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import sys
import textwrap
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


# --- Order 133 G5: the hand-written mirrors in contracts/types.ts -----------
#
# Most screen types are still written by hand. Each `export interface X` whose
# name is a pydantic model in `app.schemas` or an `app.api.*` module mirrors
# that model, so every field it declares must be a field (or alias, or
# computed field) the model sends. A field the screen reads that the backend
# never sends is how a screen shows nothing - or a made-up value - unseen.

#: Fields a mirror declares that its model does not send today. This list may
#: only SHRINK: a fix removes its entry (the second test fails until it does),
#: and nothing new may be added to make the first test pass.
MIRROR_EXTRA_FIELDS_ALLOWED: dict[str, frozenset[str]] = {
    "ComparisonSide": frozenset({"reason"}),
    "Comparison": frozenset({"could_not_be_checked", "incomplete"}),
    "AnswerResult": frozenset({"web_available", "web_phrase", "web_searched"}),
}

#: Interfaces the parser below cannot read, each with its reason. Empty today:
#: every `export interface` in types.ts parses to at least one field.
UNREADABLE_INTERFACES: dict[str, str] = {}

_INTERFACE_HEAD = re.compile(
    r"^export interface (\w+)\s*(?:<[^>{]*>)?\s*(?:extends\s+[^{]+)?\{", re.M
)
_FIELD = re.compile(r"(?:readonly\s+)?(\w+|\"[^\"]+\"|'[^']+')\s*\??\s*:")
_QUOTES = "\"'`"


def _skip_string(text: str, i: int) -> int:
    """The index just past the string literal that opens at `i`."""
    quote, i = text[i], i + 1
    while text[i] != quote:
        i += 2 if text[i] == "\\" else 1
    return i + 1


def _strip_comments(text: str) -> str:
    out, i = [], 0
    while i < len(text):
        if text.startswith("//", i):
            end = text.find("\n", i)
            i = len(text) if end < 0 else end
        elif text.startswith("/*", i):
            i = text.index("*/", i + 2) + 2
            out.append(" ")
        elif text[i] in _QUOTES:
            end = _skip_string(text, i)
            out.append(text[i:end])
            i = end
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def _body_end(text: str, i: int) -> int:
    """The index of the `}` closing the body that starts at `i`."""
    depth = 1
    while True:
        if text[i] in _QUOTES:
            i = _skip_string(text, i)
            continue
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        if depth == 0:
            return i
        i += 1


def _top_level_fields(body: str) -> list[str]:
    """The member names of one interface body; nested object types,
    generics, unions spread over lines and arrow types are not members."""
    names, depth, at_member_start, i = [], 0, True, 0
    while i < len(body):
        c = body[i]
        if depth == 0 and at_member_start and not c.isspace():
            at_member_start = False
            match = _FIELD.match(body, i)
            if match:
                names.append(match.group(1).strip("\"'"))
                i = match.end()
                continue
        if c in _QUOTES:
            i = _skip_string(body, i)
            continue
        if c in "{([<":
            depth += 1
        elif c in "})]" or (c == ">" and body[i - 1] != "="):
            depth -= 1
        elif depth == 0 and c in ";,\n":
            at_member_start = True
        i += 1
    return names


def _interfaces(text: str) -> dict[str, list[str]]:
    """Each exported interface's own fields (an `extends` parent's fields
    belong to the parent's own entry)."""
    text = _strip_comments(text)
    found: dict[str, list[str]] = {}
    for head in _INTERFACE_HEAD.finditer(text):
        assert head.group(1) not in found, f"{head.group(1)} declared twice"
        found[head.group(1)] = _top_level_fields(
            text[head.end() : _body_end(text, head.end())]
        )
    return found


def _backend_models() -> dict[str, type[BaseModel]]:
    import importlib
    import pkgutil

    import app.api

    names = ["app.schemas"] + [
        f"app.api.{info.name}" for info in pkgutil.iter_modules(app.api.__path__)
    ]
    models: dict[str, type[BaseModel]] = {}
    for module_name in names:
        module = importlib.import_module(module_name)
        for name, value in vars(module).items():
            if (
                isinstance(value, type)
                and issubclass(value, BaseModel)
                and value.__module__ == module_name
            ):
                assert name not in models, f"{name} is defined in two modules"
                models[name] = value
    return models


def _sent_keys(model: type[BaseModel]) -> set[str]:
    keys = set(model.model_computed_fields)
    for name, field in model.model_fields.items():
        keys.add(name)
        for alias in (field.alias, field.serialization_alias, field.validation_alias):
            if isinstance(alias, str):
                keys.add(alias)
    return keys


def _mirror_extras(text: str) -> tuple[int, dict[str, set[str]]]:
    """(mirrors checked, interface -> fields its model does not send)."""
    models = _backend_models()
    interfaces = _interfaces(text)
    unread = [name for name, fields in interfaces.items() if not fields]
    assert sorted(unread) == sorted(UNREADABLE_INTERFACES), unread
    mirrors = {name: interfaces[name] for name in interfaces.keys() & models.keys()}
    extras = {
        name: extra
        for name, fields in mirrors.items()
        if (extra := set(fields) - _sent_keys(models[name]))
    }
    return len(mirrors), extras


def test_the_parser_reads_every_interface_style_types_ts_uses():
    text = textwrap.dedent(
        """
    /** a { brace } in a comment, and a: field */
    export interface A extends B<C>, D {
      // gone: string;
      one: string; two?: number | null,
      readonly three: { inner: string; deeper: { x: 1 } }[];
      four: Record<string, { y: number }>;
      five:
        | "a;b"
        | "{";
      six: (z: number) => void;
      "seven-eight"?: boolean
    }
    export interface E { nine: string; ten: number }
    """
    )
    assert _interfaces(text) == {
        "A": ["one", "two", "three", "four", "five", "six", "seven-eight"],
        "E": ["nine", "ten"],
    }


def test_every_hand_written_mirror_declares_only_fields_its_model_sends():
    count, extras = _mirror_extras(TYPES_TS.read_text(encoding="utf-8"))
    # 148 on order 133; a drop means the net silently caught fewer mirrors.
    assert count >= 148, count
    unexpected = {
        name: sorted(extra - MIRROR_EXTRA_FIELDS_ALLOWED.get(name, frozenset()))
        for name, extra in extras.items()
    }
    unexpected = {name: extra for name, extra in unexpected.items() if extra}
    assert unexpected == {}, (
        f"contracts/types.ts declares fields its backend model does not send: "
        f"{unexpected}"
    )


def test_every_allow_listed_extra_field_is_still_extra():
    """A fixed exception must leave the allow-list, so it only shrinks."""
    _, extras = _mirror_extras(TYPES_TS.read_text(encoding="utf-8"))
    stale = {
        name: sorted(allowed - extras.get(name, set()))
        for name, allowed in MIRROR_EXTRA_FIELDS_ALLOWED.items()
    }
    stale = {name: fields for name, fields in stale.items() if fields}
    assert stale == {}, f"no longer extra - remove from the allow-list: {stale}"
