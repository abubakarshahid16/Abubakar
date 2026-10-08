"""#616: each entry deletes one place where a leading-zero comma ("0,030") is
kept out of the thousands rule; backend/tests/test_w2_numparse_leading_zero.py
must notice."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_w2_numparse_leading_zero.py"
_TAG = ("w2_numparse", "honesty")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M2421", phase=2421,
             description="parse_value reads 0,030 as a thousands group (30) again",
             path=APP / "numparse.py",
             anchor='    if re.fullmatch(r"(?!0,)\\d{1,3}(?:,\\d{3})+(?:\\.\\d+)?", num):',
             replacement='    if re.fullmatch(r"\\d{1,3}(?:,\\d{3})+(?:\\.\\d+)?", num):',
             target=_T, keyword="decimal", tags=_TAG),
    Mutation(id="M2422", phase=2422,
             description="find_numbers reads 0,030 as a thousands group (30) again",
             path=APP / "numparse.py",
             anchor='_GROUPED = re.compile(r"(?!0,)[0-9]{1,3}(?:,[0-9]{3})+(?:\\.[0-9]+)?")',
             replacement='_GROUPED = re.compile(r"[0-9]{1,3}(?:,[0-9]{3})+(?:\\.[0-9]+)?")',
             target=_T, keyword="find_numbers or figure_check", tags=_TAG),
    Mutation(id="M2423", phase=2423,
             description="fold_numbers strips the comma of 0,030 again (the text becomes 0030)",
             path=APP / "numparse.py",
             anchor='_THOUSANDS = re.compile(r"(?<=\\d)(?<!(?<![\\d,.])0),(?=\\d{3}(?!\\d))")',
             replacement='_THOUSANDS = re.compile(r"(?<=\\d),(?=\\d{3}(?!\\d))")',
             target=_T, keyword="fold_numbers", tags=_TAG),
    Mutation(id="M2424", phase=2424,
             description="claims counts the decimals of 0,030 as a thousands group again",
             path=APP / "claims.py",
             anchor='    if re.fullmatch(r"[-+]?(?!0,)\\d{1,3}(?:,\\d{3})+(?:\\.\\d+)?", text):',
             replacement='    if re.fullmatch(r"[-+]?\\d{1,3}(?:,\\d{3})+(?:\\.\\d+)?", text):',
             target=_T, keyword="last_digit_precision", tags=_TAG),
)
