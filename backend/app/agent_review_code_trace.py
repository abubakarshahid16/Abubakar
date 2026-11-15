"""The trace of a CODE line (the calculator's), read from the proof the line stores (owner, 12 Nov 2026; `ONE-REVIEWER.md`).

A model line's trace is its gate steps; a code line has no model and no gate, so its trace IS its proof, in plain fields: the paper quote and the page
it was found on, the clause quote, the two numbers the code compared with their units, the comparison and its answer, and which tests held. Nothing is
invented here: a field the line does not hold says so. Pure: reads the stored line only. No document text is logged.
"""

from __future__ import annotations

from collections.abc import Mapping


def _yes(flag: object) -> str:
    return "yes" if flag is True else "no"


def _number(side: object) -> str:
    if not isinstance(side, Mapping):
        return "not stored"
    value, unit = (
        str(side.get("raw_value") or "").strip(),
        str(side.get("raw_unit") or "").strip(),
    )
    return f"{value} {unit}".strip() or "not stored"


def steps(line: Mapping) -> list[tuple[str, str, str]]:
    """(step, outcome, reason) rows, in the order the proof is asked."""
    checked = (
        line.get("quotes_checked")
        if isinstance(line.get("quotes_checked"), Mapping)
        else {}
    )
    cmp = line.get("compare") if isinstance(line.get("compare"), Mapping) else {}
    req = (
        line.get("proof_requirement")
        if isinstance(line.get("proof_requirement"), Mapping)
        else {}
    )
    out = [("made by", "code, no model", str(line.get("code_kind") or ""))]
    if line.get("code_kind") == "numeric":
        out += [
            ("paper quote found on its page", _yes(checked.get("paper_found")), f"page {line.get('paper_page')}"),
            ("the value and its unit stated inside the paper quote", _yes(checked.get("paper_value")), _number(line.get("proof_fact"))),
            ("the quote sits with the field's label", _yes(checked.get("field")), str(line.get("field") or "")),
            ("clause quote found in its clause", _yes(checked.get("clause_found")), str(line.get("clause") or "")),
            ("the limit and its unit stated inside the clause quote", _yes(checked.get("clause_limit")), f"{req.get('operator') or ''} {_number(req)}".strip()),
        ]  # fmt: skip
    else:
        out += [
            (
                "paper value found next to its label on the page",
                _yes(checked.get("paper")),
                f"page {line.get('paper_page')}",
            ),
            (
                "the approved checklist's own wording",
                _yes(checked.get("clause")),
                str(line.get("rule_id") or ""),
            ),
        ]
    out.append(
        (
            "compared by code",
            str(
                cmp.get("verdict")
                or ("not decided" if cmp.get("decided") is False else "not stored")
            ),
            str(cmp.get("reason") or ""),
        )
    )
    out.append(
        (
            "decision",
            str(line.get("verdict_label") or line.get("verdict") or ""),
            str(line.get("not_proven_reason") or line.get("why") or ""),
        )
    )
    return out
