"""Order 120 item 3: every reason code a finding's text can open with has a
plain sentence on the screen.

The comparison and the rule evaluator write rationales as "<code>: words".
The screen shows the code's sentence from one table,
`frontend/src/components/review/reasonWords.tsx`, and keeps the code in a
tooltip. This reads the codes from the writers' own source, so a new
`f"{SOME_CODE}: ..."` rationale fails here until the table names it.
"""

import re
from pathlib import Path

from app import comparison, rule_eval

ROOT = Path(__file__).resolve().parents[2]
TABLE = ROOT / "frontend" / "src" / "components" / "review" / "reasonWords.tsx"
# The constant a rationale f-string opens with: f"{NO_FIELD_MATCHED}: ..."
LEAD = re.compile(r'f"\{([A-Z][A-Z_]+)\}: ')


def _codes() -> dict[str, str]:
    codes = {}
    for module in (comparison, rule_eval):
        source = Path(module.__file__).read_text(encoding="utf-8")
        for name in set(LEAD.findall(source)):
            codes[name] = getattr(module, name)
    return codes


def test_the_writers_have_codes_to_check():
    codes = _codes()
    # Not vacuous: the known families are found by the scan.
    assert codes["NO_FIELD_MATCHED"] == "no_field_matched"
    assert codes["RULE_REASON"] == "RULE_EVALUATED"
    assert len(codes) >= 15


def test_every_code_has_a_plain_sentence_on_the_screen():
    table = TABLE.read_text(encoding="utf-8")
    named = set(re.findall(r'^\s+([A-Za-z_]+): "', table, flags=re.MULTILINE))
    missing = sorted(code for code in _codes().values() if code not in named)
    assert not missing, (
        f"reason codes with no plain sentence in {TABLE.name}: {missing}"
    )
