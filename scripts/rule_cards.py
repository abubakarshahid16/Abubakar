"""Rule cards report and release gate (order 296). The logic lives in `backend/app/rule_cards.py`.

    python scripts/rule_cards.py            # per checklist: cards tested / draft and why
    python scripts/rule_cards.py --check    # exit 0 only when no card is a draft nobody explained
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app import rule_cards  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(rule_cards.main())
