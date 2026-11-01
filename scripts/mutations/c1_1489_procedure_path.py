"""#1476 / PR 1489 procedure path: each entry deletes one decision line;
backend/tests/test_procedure_path.py must notice."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_procedure_path.py"
_TAG = ("c1_1489", "procedure_path")
_C = APP / "comparison.py"
_P = APP / "procedure_text.py"
_OWN = "    own = evidence in OWN_TEXT_EVIDENCE\n"
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
        "nothing found no longer says contractor to show where",
        _P,
        '"status": "MISSING_INFORMATION"',
        '"status": "NEEDS_ENGINEER_REVIEW"',
        "nothing_found",
    ),
    _m(
        5,
        "a found passage becomes COMPLIANT",
        _P,
        '\n        "status": "NEEDS_ENGINEER_REVIEW",\n        "rationale": (\n',
        '\n        "status": "COMPLIANT",\n        "rationale": (\n',
        "never_compliant or found_requirement",
    ),
    _m(
        6,
        "the switch is ignored",
        _P,
        "    if not settings.procedure_path_enabled or not document_id:\n",
        "    if not document_id:\n",
        "switch_is_off",
    ),
    _m(
        7,
        "every submittal counts as a procedure once the switch is on",
        _P,
        "    return document_kind(document_id) in PROCEDURE_KINDS\n",
        "    return True\n",
        "switch_is_off",
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
        14,
        "a procedure row is rewritten by the unread-pages qualifier again",
        _P,
        '        and not (verdict.get("rationale") or "").startswith(NOT_FOUND)\n',
        "",
        "keeps_its_own_words",
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
)
