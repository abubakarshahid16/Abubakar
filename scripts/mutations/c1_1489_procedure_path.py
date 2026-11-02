"""#1476 / PR 1489 procedure path: each entry deletes one decision line;
backend/tests/test_procedure_path.py must notice."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_procedure_path.py"
_TAG = ("c1_1489", "procedure_path")
_C = APP / "comparison.py"
_P = APP / "procedure_text.py"
_M = APP / "crs_mapping.py"
_OWN = '    own = evidence in OWN_TEXT_EVIDENCE and not _OTHER_EVIDENCE.search(text or "")\n'
_STATEMENT = (
    '        and requirement.get("requirement_type") == requirements_3b.STATEMENT\n'
)


def _m(n, desc, path, anchor, repl, kw=None):
    return Mutation(
        id=f"M1489-{n:02d}",
        phase=1489,
        description=desc,
        path=path,
        anchor=anchor,
        replacement=repl,
        target=_T,
        keyword=kw,
        tags=_TAG,
    )


MUTATIONS: tuple[Mutation, ...] = (
    _m(
        1,
        "a procedure-evidence demand is sent to another document again",
        _P,
        _OWN,
        "    own = False\n",
        "procedure_evidence_demand",
    ),
    _m(
        2,
        "an unmatched statement of a procedure is sent away again",
        _P,
        _STATEMENT,
        "        and False\n",
        "found_requirement or nothing_found",
    ),
    _m(
        3,
        "a certificate or drawing demand is checked against the procedure text",
        _P,
        _OWN,
        "    own = bool(evidence)\n",
        "certificate_or_drawing",
    ),
    _m(
        4,
        "a search that finds nothing asks the contractor to provide it again",
        _P,
        '            **engineer,\n            "rationale": (\n                f"{NOT_FOUND}',
        '            **base,\n            "status": "MISSING_INFORMATION",\n            "rationale": (\n                f"{NOT_FOUND}',
        "nothing_found",
    ),
    _m(
        5,
        "a found passage becomes COMPLIANT",
        _P,
        '    return {\n        **engineer,\n        "rationale": (\n            f\'{FOUND}',
        '    return {\n        **base,\n        "status": "COMPLIANT",\n        "rationale": (\n            f\'{FOUND}',
        "never_compliant or found_requirement",
    ),
    _m(
        6,
        "the switch is ignored",
        _P,
        "    if not settings.procedure_path_enabled or not document_id:\n",
        "    if not document_id:\n",
        "router_kind_decides",
    ),
    _m(
        7,
        "every submittal counts as a procedure once the switch is on",
        _P,
        "    return document_kind(document_id) in PROCEDURE_KINDS\n",
        "    return True\n",
        "router_kind_decides",
    ),
    _m(
        8,
        "the comparison never asks the procedure path, so nothing is routed",
        _C,
        "    if routed := procedure_text.route(requirement, fact):\n",
        "    if False:\n",
        "found_requirement",
    ),
    _m(
        9,
        "a statement that only asks to be stated is looked up in the text",
        _P,
        "        and not field_links.asks_only_to_be_stated(text)\n",
        "",
        "stated_on_the_datasheet",
    ),
    _m(
        10,
        "a statement naming a certificate is looked up in the text",
        _P,
        "        and evidence in (None, requirements_3b.DATA_SHEET_EVIDENCE)\n",
        "",
        "certificate_or_drawing",
    ),
    _m(
        11,
        "the run never reads the procedure pages",
        _C,
        "        procedure_text.reading(review_run_id),  # #1476\n",
        "        procedure_text.using(None),  # #1476\n",
        "reads_the_procedure_pages",
    ),
    _m(
        12,
        "the pages stay set after the run, for the next caller",
        _P,
        "        _PAGES.reset(token)\n",
        "        pass\n",
        "reads_the_procedure_pages",
    ),
    _m(
        13,
        "a kind the router left to an engineer takes the procedure path",
        _P,
        '    if row is None or row["state"] == "needs_engineer":\n',
        "    if row is None:\n",
        "router_kind_decides",
    ),
    _m(
        15,
        "a requirement with too few words is searched anyway",
        _P,
        "    if len(key_words(text)) < MIN_HITS:\n",
        "    if False:\n",
        "too_few_words",
    ),
    _m(
        16,
        "one shared word is enough for a passage",
        _P,
        "    need = max(1, min(MIN_HITS, len(wanted)))\n",
        "    need = 1\n",
        "two_of_three_words",
    ),
    _m(
        17,
        "a procedure row is left off the CRS as a note",
        _M,
        "        and not procedure_text.is_row(finding)\n",
        "",
        "without_a_page",
    ),
    _m(
        18,
        "a procedure row prints the datasheet wording on the CRS",
        _M,
        "    if words := procedure_text.crs_words(f, lead):  # #1476\n",
        "    if False:\n",
        "one_counted_note",
    ),
    _m(
        19,
        "the procedure reason codes are not registered",
        _C,
        "    *procedure_text.REASON_CODES,  # #1476\n",
        "",
        "one_counted_note",
    ),
    _m(
        20,
        "a record about a procedure is checked against the procedure text",
        _P,
        '    own = evidence in OWN_TEXT_EVIDENCE and not _OTHER_EVIDENCE.search(text or "")\n',
        "    own = evidence in OWN_TEXT_EVIDENCE\n",
        "procedure_records",
    ),
    _m(
        21,
        "a quote that is not in the stored page is shown",
        _P,
        '    if not found or _fold(quote) not in _fold(dict(pages).get(found["page"], "")):\n',
        "    if not found:\n",
        "never_shown",
    ),
    _m(
        22,
        "a not-found procedure row is its own CRS line again",
        _M,
        "            and not procedure_text.is_unfound(f)\n",
        "",
        "one_counted_note",
    ),
    _m(
        23,
        "the procedure note counts one too many",
        _P,
        '            "count": len(rows),\n',
        '            "count": len(rows) + 1,\n',
        "one_counted_note",
    ),
    _m(
        24,
        "a found row loses its contractor page",
        _P,
        "    if match:\n        return int(match.group(1))\n",
        "    if False:\n        return int(match.group(1))\n",
        "one_counted_note",
    ),
    _m(
        25,
        "a found row takes its fact's page, not the page of its quote",
        _P,
        "    if match:\n        return int(match.group(1))\n",
        "    if match and not fact:\n        return int(match.group(1))\n",
        "page_of_its_quote",
    ),
)
