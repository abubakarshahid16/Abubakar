#!/usr/bin/env python3
"""No second number reader outside `numparse`: the same check CI runs, run BEFORE the push.

`backend/tests/test_w2_number_parser.py::test_no_module_outside_the_known_list_defines_a_second_number_reader`
fails a module under `backend/app/` that defines a private number reader (`_NUMBER_TOKEN =`, `_ANY_NUMBER =`,
`_fold_numbers`, `_normalise_number_text`) or folds text with `unicodedata.normalize("NFKC", ...)`. Three PRs of one
batch (a figure comparer, an agent toolbox, a local second opinion) were sent back by CI for exactly that, a text fold
or a digit-run pattern that never reads a value. This script loads the pattern and the exemption list FROM THAT TEST
(one source: they cannot drift) and applies them to the app folder, so the push is refused locally.

    python scripts/check_second_number_reader.py            # exit 1 and the fix, or 0
    python scripts/check_second_number_reader.py --app DIR  # scan another folder (used by the tests)
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TEST = REPO / "backend" / "tests" / "test_w2_number_parser.py"

FIX = """  - it only COUNTS or REFUSES digits (never yields a value)? Rename the pattern (for example `_DIGIT_RUN`).
  - it folds look-alike characters? Call `app.word_fold.fold_compat` instead of `unicodedata.normalize("NFKC", ...)`.
  - it really reads a number? Use `app.numparse` (do not write a second reader).
  Adding the module to `_NOT_YET_MOVED` in the test is a decision, not a habit: it needs a reason that says when it stops being true."""


def load_rules(test: Path = TEST) -> tuple[object, set[str]]:
    """(the private-reader pattern, the exempt file names): taken from the CI test itself."""
    sys.path.insert(0, str(test.parents[2] / "backend"))
    spec = importlib.util.spec_from_file_location("_w2_number_parser_rules", test)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module._PRIVATE_PARSER, set(module._NOT_YET_MOVED)


def offenders(app: Path, pattern, exempt: set[str]) -> list[str]:
    return [
        p.name
        for p in sorted(app.glob("*.py"))
        if p.name != "numparse.py"
        and p.name not in exempt
        and pattern.search(p.read_text(encoding="utf-8"))
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--app", type=Path, default=REPO / "backend" / "app")
    ap.add_argument("--test", type=Path, default=TEST)
    args = ap.parse_args(argv)
    pattern, exempt = load_rules(args.test)
    found = offenders(args.app, pattern, exempt)
    if not found:
        print("OK: no module outside numparse defines a second number reader")
        return 0
    print(
        f"a second number reader appeared in {found}. CI test_w2_number_parser refuses it. Fix:"
    )
    print(FIX)
    return 1


if __name__ == "__main__":
    sys.exit(main())
