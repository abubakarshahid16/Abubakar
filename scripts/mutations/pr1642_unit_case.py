"""#1618 (PR #1642): a unit whose case is its meaning keeps it, so mPa is never MPa
(unit_case.py, claims.py, numparse.py; danger zone). Ids M1642-01.. (CLAUDE.md rule 12)."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_1618_unit_case.py"
_TAG = ("pr1642", "units", "honesty")
_CLAIMS = APP / "claims.py"
_NUMPARSE = APP / "numparse.py"
_CASE = APP / "unit_case.py"


def _entry(
    number: str, what: str, path, anchor: str, replacement: str, keyword: str
) -> Mutation:
    return Mutation(
        id=f"M1642-{number}",
        phase=1642,
        description=what,
        path=path,
        anchor=anchor,
        replacement=replacement,
        target=_T,
        keyword=keyword,
        tags=_TAG,
    )


MUTATIONS: tuple[Mutation, ...] = (
    _entry(
        "01",
        "claims folds every unit to lower case again, so mPa reads as MPa",
        _CLAIMS,
        "    u = fold_unit(unit_str)\n",
        "    u = unit_str.strip().lower()\n",
        "millipascal_is_never",
    ),
    _entry(
        "02",
        "a kept unit is no longer a rate's top, so a real mW/m2 is thrown away",
        _CLAIMS,
        "for a in _families(top.lower(), _RATE_NUMERATOR)",
        "for a in _families(top, _RATE_NUMERATOR)",
        "rate_keeps_its_case",
    ),
    _entry(
        "03",
        "the kept units are not in the recognised list",
        _CLAIMS,
        "    **UNCONVERTED,\n",
        "",
        "millipascal_is_never",
    ),
    _entry(
        "04",
        "mPag is not a pressure with a reference",
        _CLAIMS,
        "    **REFERENCE_SUFFIX,\n",
        "",
        "millipascal_with_a_reference",
    ),
    _entry(
        "05",
        "5 mPa.s in a sentence is cut at the pascal and read as a pressure",
        _CLAIMS,
        'unit = unit_at(sentence, m.group("unit"), m.end("unit"))',
        'unit = m.group("unit")',
        "viscosity_in_a_sentence",
    ),
    _entry(
        "06",
        "a quote printing 10 mPa proves a value of 10 MPa",
        _NUMPARSE,
        "        _strip_thousands(fold(mark_case_kept(text))),\n",
        "        _strip_thousands(fold(text)),\n",
        "quote_does_not_prove",
    ),
    _entry(
        "07",
        "the mark is not a letter, so MPa is a whole word beside it and mPa proves MPa",
        _NUMPARSE,
        '_CASE_KEPT_MARK = "\\u0283"\n',
        '_CASE_KEPT_MARK = "\\ue000"\n',
        "quote_does_not_prove",
    ),
    _entry(
        "08",
        "fold_unit folds a kept unit too",
        _CASE,
        "    return top + slash + rest.lower() if top in CASE_KEPT_UNITS else text.lower()\n",
        "    return text.lower()\n",
        "test_fold_unit",
    ),
    _entry(
        "09",
        "what follows a kept unit's slash no longer folds",
        _CASE,
        "    return top + slash + rest.lower() if top in CASE_KEPT_UNITS else text.lower()\n",
        "    return top + slash + rest if top in CASE_KEPT_UNITS else text.lower()\n",
        "denominator_of_a_kept_rate",
    ),
    _entry(
        "10",
        "a checklist calculation converts mPa with the MPa factor",
        _CASE,
        '    key = fold_unit(unit).replace(" ", "")',
        '    key = str(unit or "").lower().replace(" ", "")',
        "calculation_does_not_convert",
    ),
    _entry(
        "11",
        "5 Pa.s in a sentence is read as a pressure of 5 Pa",
        _CASE,
        '    if unit.lower() not in ("pa", "kpa", "mpa"):\n',
        '    if unit.lower() not in ("kpa", "mpa"):\n',
        "pascal_second_in_a_sentence",
    ),
)
