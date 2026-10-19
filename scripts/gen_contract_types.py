"""Write the frontend's TypeScript contract types from the backend's own models.

Order 119.1 (117a item 4): one source of truth. A registered pydantic model is
the definition; `contracts/generated/*.ts` is written from it and committed,
and CI fails when the committed file and the model differ, so the screen
cannot quietly drift from what the server sends.

    python scripts/gen_contract_types.py           # rewrite the generated files
    python scripts/gen_contract_types.py --check   # exit 1 and show the diff on drift

What is read from a model: its fields (JSON schema), which are required (no
default -> `name: T`, else `name?: T`; with `Module.sent_defaults` a default
that is a value, not None, is also `name: T`), its docstring and each field's `#:`
comment, above the field or trailing on its line (as the JSDoc). A `dict`
field the screen knows by a richer type names it with
`Field(json_schema_extra={"tsType": "PageCoverage"})`, or, for a model whose
file may not grow (`schemas.py`), in its `Module.ts_types`; that name is
imported from `contracts/types.ts`, so a richer type is always a named alias
there (the import takes a type's FIRST identifier). A model referenced but not
registered is an error, never a silent `unknown`.

Models move here block by block: add a `Module` (or a model to one) and
delete the hand-written copy from `contracts/types.ts` in the same PR.

Order 133: a `DataModule` is a generated file written from rule data rather
than a model (the review tiers, `scripts/gen_tier_rules.py`); it is written and
checked the same way.
"""

from __future__ import annotations

import argparse
import difflib
import importlib.util
import inspect
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GENERATED = REPO / "contracts" / "generated"
sys.path.insert(0, str(REPO / "backend"))

_COMMENT = re.compile(r"^\s*#:\s?(.*)$")
_FIELD = re.compile(r"^\s*([a-z_][a-z0-9_]*)\s*:")
_TRAILING = re.compile(r"\s#:\s?(.*)$")
_IDENT = re.compile(r"^[A-Za-z_]\w*")


@dataclass(frozen=True)
class Module:
    """One generated file: its models in order, as (model, TypeScript name),
    the Literal fields written as named unions, as
    ((model name, field), TypeScript name), and the fields written as a richer
    screen type than their JSON schema says (a `dict`), as
    ((model name, field), TypeScript type)."""

    filename: str
    source: str
    models: tuple[tuple[type, str], ...]
    unions: tuple[tuple[tuple[str, str], str], ...] = ()
    ts_types: tuple[tuple[tuple[str, str], str], ...] = ()
    #: a field whose default is a value (not None) is always sent in a
    #: response, so it is written required (`name: T`). Set where the screen
    #: reads such fields as always there (a count, a list it maps over);
    #: left off where it also reads an older server's reply without them.
    sent_defaults: bool = False


def modules() -> tuple[Module, ...]:
    from app.api import run_summary as rs

    return (
        *_schema_modules(),
        Module(
            filename="run_summary.ts",
            source="backend/app/api/run_summary.py",
            models=(
                (rs.TierCounts, "RunSummaryTierCounts"),
                (rs.TierRow, "RunSummaryTierRow"),
                (rs.StandardClauses, "RunSummaryStandardClauses"),
                (rs.HowReviewed, "RunSummaryHowReviewed"),
                (rs.RunSummary, "ReviewRunTierSummary"),
                (rs.RunCountsBatch, "ReviewRunCountsBatch"),
            ),
            unions=(
                (("TierRow", "tier"), "RunSummaryTier"),
                (("TierRow", "label"), "RunSummaryTierLabel"),
                (("TierRow", "reason"), "RunSummaryTierReason"),
                (("TierRow", "crs_priority_label"), "RunSummaryCrsPriorityLabel"),
            ),
        ),
    )


def _schema_modules() -> tuple[Module, ...]:
    """Order 133: the CRS issue gate, the review finding, the runs list and a
    run's standards list, from `schemas.py`."""
    from app import schemas as s
    from app.api import run_summary as rs

    return (
        Module(
            filename="crs_issue.ts",
            source="backend/app/schemas.py",
            models=(
                (s.CrsUnreadPage, "CrsUnreadPage"),
                (s.CrsOpenFinding, "CrsOpenFinding"),
                (s.CrsIssueGate, "CrsIssueGate"),
                (s.CrsIssueDecision, "CrsIssueDecision"),
                (s.CrsIssueDecisionList, "CrsIssueDecisionList"),
            ),
        ),
        Module(
            filename="review_findings.ts",
            source="backend/app/schemas.py",
            models=(
                (s.ReviewScopeDecision, "ReviewScopeDecision"),
                (s.ReviewFinding, "ReviewFinding"),
            ),
            unions=(
                (("ReviewFinding", "category"), "ReviewCategory"),
                (("ReviewFinding", "severity"), "ReviewSeverity"),
                (("ReviewFinding", "disposition"), "ReviewDisposition"),
                (("ReviewFinding", "status"), "ReviewStatus"),
                (("ReviewFinding", "approval_status"), "ApprovalStatus"),
                (("ReviewFinding", "compliance_status"), "ComplianceStatus"),
            ),
        ),
        Module(
            filename="review_runs.ts",
            sent_defaults=True,
            source="backend/app/schemas.py and backend/app/api/run_summary.py",
            models=(
                (s.ReviewJobState, "ReviewJobState"),
                (s.AiStepNumbers, "AiStepNumbers"),
                (s.AiNumbers, "AiNumbers"),
                (s.ReviewRunSummary, "ReviewRunSummary"),
                (rs.ReviewRunList, "ReviewRunList"),
            ),
            ts_types=tuple(
                (("ReviewRunSummary", field), ts)
                for field, ts in (
                    ("by_status", "StatusCounts"),
                    ("completeness", "ReviewRunCompleteness"),
                    ("standards_change", "StandardsChange"),
                    ("page_coverage", "PageCoverage"),
                    ("table_values_not_compared", "TableValuesNotCompared[]"),
                    ("requirements_not_applied", "RequirementsNotApplied[]"),
                    ("requirement_split", "RequirementSplit"),
                    ("clause_coverage", "RunClauseCoverageSummary"),
                    ("applicability", "RunApplicability"),
                    ("ai_check_status", "AiCheckStatus"),
                    ("web_check_status", "RunCheckStatus"),
                )
            ),
        ),
        Module(
            filename="run_standards.ts",
            source="backend/app/schemas.py",
            models=(
                (s.ReviewRunStandard, "ReviewRunStandard"),
                (s.ReviewRunMissingReference, "ReviewRunMissingReference"),
                (s.HeldForConfirmation, "ReviewRunHeldForConfirmation"),
                (s.ReviewRunStandardList, "ReviewRunStandardList"),
            ),
        ),
    )


@dataclass(frozen=True)
class DataModule:
    """One generated file written from rule data, not from a model (order
    133): `render` returns the file's whole text."""

    filename: str
    source: str
    render: Callable[[], str]


def _script(name: str):
    """A sibling script, loaded by path (this file is also loaded by path)."""
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).with_name(f"{name}.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def data_modules() -> tuple[DataModule, ...]:
    tiers = _script("gen_tier_rules")
    return (
        DataModule(filename=tiers.FILENAME, source=tiers.SOURCE, render=tiers.render),
    )


def field_comments(model: type) -> dict[str, str]:
    """Each field's `#:` comment lines, joined, from the model's source."""
    comments: dict[str, str] = {}
    pending: list[str] = []
    for line in inspect.getsource(model).splitlines()[1:]:
        if match := _COMMENT.match(line):
            pending.append(match.group(1).strip())
        elif match := _FIELD.match(line):
            if trailing := _TRAILING.search(line):
                pending.append(trailing.group(1).strip())
            if pending:
                comments[match.group(1)] = " ".join(pending)
            pending = []
        elif line.strip():
            pending = []
    return comments


def _jsdoc(text: str | None, indent: str) -> list[str]:
    if not text:
        return []
    words = " ".join(inspect.cleandoc(text).split())
    return [f"{indent}/** {words} */"]


def _literal(values: list) -> str:
    return " | ".join(f'"{v}"' for v in values)


class _Renderer:
    def __init__(self, module: Module, defs: dict):
        self.names = {model.__name__: ts for model, ts in module.models}
        self.unions = dict(module.unions)
        self.ts_types = dict(module.ts_types)
        self.sent_defaults = module.sent_defaults
        self.defs = defs
        self.imports: set[str] = set()

    def type_of(self, node: dict, where: tuple[str, str] | None = None) -> str:
        if "tsType" in node:
            self.imports.add(_IDENT.match(node["tsType"]).group(0))
            nullable = any(part.get("type") == "null" for part in node.get("anyOf", []))
            return node["tsType"] + (" | null" if nullable else "")
        if "anyOf" in node:
            parts = [self.type_of(part, where) for part in node["anyOf"]]
            return " | ".join(dict.fromkeys(parts))
        if "$ref" in node:
            name = node["$ref"].rsplit("/", 1)[-1]
            if name not in self.names:
                raise SystemExit(f"{name} is referenced but not registered")
            return self.names[name]
        if "enum" in node or "const" in node:
            if where in self.unions:
                return self.unions[where]
            return _literal(node.get("enum", [node.get("const")]))
        kind = node.get("type")
        if kind == "null":
            return "null"
        if kind == "string":
            return "string"
        if kind in ("integer", "number"):
            return "number"
        if kind == "boolean":
            return "boolean"
        if kind == "array":
            item = self.type_of(node.get("items", {}))
            return f"({item})[]" if " | " in item else f"{item}[]"
        if kind == "object":
            values = node.get("additionalProperties")
            if isinstance(values, dict) and values:
                return f"Record<string, {self.type_of(values)}>"
            return "Record<string, unknown>"
        raise SystemExit(f"no TypeScript type for {node} at {where}")

    def interface(self, model: type, ts_name: str) -> list[str]:
        schema = self.defs.get(model.__name__) or model.model_json_schema()
        required = set(schema.get("required", []))
        if self.sent_defaults:
            required |= {
                name
                for name, field in model.model_fields.items()
                if not field.is_required() and field.get_default() is not None
            }
        comments = field_comments(model)
        lines = _jsdoc(model.__doc__, "")
        lines.append(f"export interface {ts_name} {{")
        for name, node in schema["properties"].items():
            lines += _jsdoc(comments.get(name), "  ")
            mark = "" if name in required else "?"
            if (model.__name__, name) in self.ts_types:
                node = {**node, "tsType": self.ts_types[model.__name__, name]}
            lines.append(
                f"  {name}{mark}: {self.type_of(node, (model.__name__, name))};"
            )
        lines.append("}")
        return lines

    def union(self, model: type, field: str, ts_name: str) -> list[str]:
        node = model.model_json_schema()["properties"][field]
        values = [
            part for part in node.get("anyOf", [node]) if part.get("type") != "null"
        ]
        if len(values) != 1 or ("enum" not in values[0] and "const" not in values[0]):
            raise SystemExit(f"{model.__name__}.{field} is not a Literal")
        only = values[0]
        return [
            f"export type {ts_name} = {_literal(only.get('enum', [only.get('const')]))};"
        ]


def render(module: Module | DataModule) -> str:
    if isinstance(module, DataModule):
        return module.render()
    defs: dict = {}
    for model, _ in module.models:
        defs.update(model.model_json_schema().get("$defs", {}))
    renderer = _Renderer(module, defs)
    by_name = {model.__name__: model for model, _ in module.models}
    body: list[str] = []
    for (model_name, field), ts_name in module.unions:
        body += renderer.union(by_name[model_name], field, ts_name)
    for model, ts_name in module.models:
        body += ["", *renderer.interface(model, ts_name)]
    head = [
        f"// GENERATED from {module.source} by scripts/gen_contract_types.py.",
        "// Do not edit: change the backend model and run the script (order 119.1).",
    ]
    if renderer.imports:
        names = ", ".join(sorted(renderer.imports))
        head += ["", f'import type {{ {names} }} from "../types";']
    return "\n".join([*head, "", *body]).replace("\n\n\n", "\n\n") + "\n"


def drift(module: Module | DataModule, directory: Path = GENERATED) -> list[str]:
    """The unified diff from the committed file to the model's rendering;
    empty when they agree. A missing file is all drift."""
    path = directory / module.filename
    committed = path.read_text(encoding="utf-8") if path.exists() else ""
    return list(
        difflib.unified_diff(
            committed.splitlines(keepends=True),
            render(module).splitlines(keepends=True),
            fromfile=f"committed {module.filename}",
            tofile=f"from {module.source}",
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check", action="store_true", help="fail on drift, write nothing"
    )
    args = parser.parse_args(argv)
    failed = False
    for module in (*modules(), *data_modules()):
        if args.check:
            diff = drift(module)
            if diff:
                failed = True
                sys.stdout.writelines(diff)
                print(
                    f"\n{module.filename} differs from {module.source}: run scripts/gen_contract_types.py"
                )
        else:
            GENERATED.mkdir(parents=True, exist_ok=True)
            (GENERATED / module.filename).write_text(
                render(module), encoding="utf-8", newline="\n"
            )
    if args.check and not failed:
        print("generated contract types match the backend models")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
