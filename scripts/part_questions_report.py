"""Order 264.8, step 0: why do the Part questions of a review wait? COUNTS ONLY, read-only, on a COPY.

A review of a vessel sheet holds thousands of requirements on "Part questions": a standard's Part or
appendix whose own scope limits it to one construction (a material family, a way of joining, a
temperature range) and the sheet does not settle whether this equipment is of it. This reads ONE
review run's stored scope record and the sheet's stored facts, and says, per class of construction
phrase, how many questions and requirements wait and whether the sheet carries a fact that could
settle that class (a material, a joint efficiency / welded wording, a minimum design metal
temperature). It also counts the lines the second model task is given (`stated_construction`): none
at all means "unsure" at once (`ai_applicability._division_decision`).

No part name, scope sentence, quote, value, filename or page is printed (CLAUDE.md rule 1): classes,
counts and yes/no only. A live-shaped path is refused. No model is called.

    python scripts/part_questions_report.py --db <review-copy.sqlite> --review-run <id> [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "scripts"))

#: Closed word lists that class a construction phrase. No standard, Part or layout is named.
CLASSES = {
    "material": (
        "steel",
        "alloy",
        "iron",
        "aluminium",
        "aluminum",
        "copper",
        "nickel",
        "titanium",
        "nonferrous",
        "non-ferrous",
        "stainless",
        "carbon",
        "duplex",
        "zirconium",
        "metal",
    ),
    "joining": (
        "weld",
        "braz",
        "forg",
        "cast",
        "rolled",
        "bolted",
        "fabricat",
        "solder",
    ),
    "temperature": (
        "temperature",
        "cold",
        "cryogenic",
        "impact",
        "heat treat",
        "tempered",
    ),
}
#: The sheet roles whose stored facts could settle a class (the vessel form of the checklists).
SETTLING_ROLES = {
    "material": ("shell_material", "head_material", "tube_material"),
    "joining": ("joint_efficiency", "radiography", "pwht", "design_code"),
    "temperature": ("mdmt", "design_temperature"),
}


def classify(construction: str) -> str:
    """The class of a construction phrase: material / joining / temperature / other."""
    low = (construction or "").lower()
    for name, words in CLASSES.items():
        if any(w in low for w in words):
            return name
    return "other"


def run(db_path: Path, review_run: str) -> dict:
    from rehearse_requirement_reextraction import refuse_live

    from app import classification as classification_mod
    from app import datasheet_checks, datasheets, scope_type_words
    from app.config import settings

    settings.db_path = refuse_live(db_path)
    conn = sqlite3.connect(f"file:{settings.db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT submittal_document_id, outcome_json FROM review_runs WHERE id = ?",
        (review_run,),
    ).fetchone()
    conn.close()
    if row is None:
        raise SystemExit(f"no review run {review_run}")
    outcome = json.loads(row["outcome_json"] or "{}")
    questions = (
        (outcome.get("requirement_split") or {}).get("division_scope") or {}
    ).get("questions") or []
    doc = row["submittal_document_id"]
    allowed = frozenset({doc})
    facts = datasheets.list_facts(doc, allowed_document_ids=allowed)
    rules = datasheet_checks.load_rules()
    roles_present = {
        role
        for f in facts
        if (
            role := datasheet_checks.role_of(
                datasheets.normalise_field_name(
                    f.get("field_label") or f.get("field_name") or ""
                ),
                rules,
            )
        )
        and str(f.get("field_value") or "").strip()
    }
    stated = scope_type_words.stated_construction(
        classification_mod.of_document(doc) or {}, facts
    )
    out = {
        "questions": len(questions),
        "requirements_waiting": sum(int(q.get("requirements") or 0) for q in questions),
        "stated_lines": len(stated),
        "by_class": {},
    }
    for q in questions:
        name = classify(q.get("construction") or "")
        bucket = out["by_class"].setdefault(
            name, {"questions": 0, "requirements": 0, "sheet_has_a_settling_fact": None}
        )
        bucket["questions"] += 1
        bucket["requirements"] += int(q.get("requirements") or 0)
        roles = SETTLING_ROLES.get(name)
        bucket["sheet_has_a_settling_fact"] = (
            bool(roles) and any(r in roles_present for r in roles) if roles else None
        )
    out["settling_roles_present"] = {
        name: sorted(r for r in roles if r in roles_present)
        for name, roles in SETTLING_ROLES.items()
    }
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", required=True, type=Path)
    ap.add_argument("--review-run", required=True)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)
    result = run(args.db, args.review_run)
    text = json.dumps(result, indent=1)
    if args.json:
        args.json.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
