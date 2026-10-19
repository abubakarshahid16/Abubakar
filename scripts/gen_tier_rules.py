"""Order 133 (117a item 4): the review tiers' rule data, written for the screen.

`backend/app/reference/review_tiers.json` is the one source of the tier rules'
data (statuses, labels, reason words and their order, phrases). The backend's
`review_tiers.py` reads it; this renders it as `contracts/generated/review_tiers.ts`
for the screen's `crs/tiers.ts`. `scripts/gen_contract_types.py` writes and
checks the file with the model-generated ones (`--check` fails on drift).
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RULES = REPO / "backend" / "app" / "reference" / "review_tiers.json"
SOURCE = "backend/app/reference/review_tiers.json"
FILENAME = "review_tiers.ts"


def render(path: Path = RULES) -> str:
    """The TypeScript text of the rule data at `path`, as one `as const` object."""
    rules = json.loads(path.read_text(encoding="utf-8"))
    body = json.dumps(rules, indent=2, ensure_ascii=False)
    return "\n".join(
        [
            f"// GENERATED from {SOURCE} by scripts/gen_contract_types.py.",
            "// Do not edit: change the rule data and run the script (order 133).",
            "",
            "/** The review tiers' rules as data. `backend/app/review_tiers.py` and the",
            " *  screen's `crs/tiers.ts` both read them, so neither holds a rule the",
            " *  other does not. Display only. */",
            f"export const TIER_RULES = {body} as const;",
            "",
        ]
    )
