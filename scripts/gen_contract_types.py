"""Write the frontend's TypeScript contract types from the backend's own models.

Order 119.1 (117a item 4): one source of truth. A registered pydantic model is
the definition; `contracts/generated/*.ts` is written from it and committed,
and CI fails when the committed file and the model differ, so the screen
cannot quietly drift from what the server sends.

    python scripts/gen_contract_types.py           # rewrite the generated files
    python scripts/gen_contract_types.py --check   # exit 1 and show the diff on drift

What is read from a model: its fields (JSON schema), which are required (no
default -> `name: T`, else `name?: T`), its docstring and each field's `#:`
comment (as the JSDoc). A `dict` field the screen knows by a richer type names
it with `Field(json_schema_extra={"tsType": "PageCoverage"})`; that name is
imported from `contracts/types.ts`. A model referenced but not registered is
an error, never a silent `unknown`.

Models move here block by block: add a `Module` (or a model to one) and
delete the hand-written copy from `contracts/types.ts` in the same PR.
"""

from __future__ import annotations

import argparse
import difflib
import inspect
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GENERATED = REPO / "contracts" / "generated"
sys.path.insert(0, str(REPO / "backend"))

_COMMENT = re.compile(r"^\s*#:\s?(.*)$")
_FIELD = re.compile(r"^\s*([a-z_][a-z0-9_]*)\s*:")
_IDENT = re.compile(r"^[A-Za-z_]\w*")


@dataclass(frozen=True)
class Module:
    """One generated file: its models in order, as (model, TypeScript name),
    and the Literal fields written as named unions, as
    ((model name, field), TypeScript name)."""

    filename: str
    source: str
    models: tuple[tuple[type, str], ...]
    unions: tuple[tuple[tuple[str, str], str], ...] = ()


def modules() -> tuple[Module, ...]:
    from app.api import run_summary as rs

    return (
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
            ),
        ),
    )


def field_comments(model: type) -> dict[str, str]:
    """Each field's `#:` comment lines, joined, from the model's source."""
    comments: dict[str, str] = {}
    pending: list[str] = []
    for line in inspect.getsource(model).splitlines()[1:]:
        if match := _COMMENT.match(line):
            pending.append(match.group(1).strip())
        elif match := _FIELD.match(line):
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
        comments = field_comments(model)
        lines = _jsdoc(model.__doc__, "")
        lines.append(f"export interface {ts_name} {{")
        for name, node in schema["properties"].items():
            lines += _jsdoc(comments.get(name), "  ")
            mark = "" if name in required else "?"
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


def render(module: Module) -> str:
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


def drift(module: Module, directory: Path = GENERATED) -> list[str]:
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
    for module in modules():
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
