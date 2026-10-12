"""Audit 2026-09-30 leftovers: items the fixing batch left "not done"
(M1600-M1619).

Each entry deletes one fix; the named tests must fail. Most live in
`backend/tests/test_audit_leftovers.py`; the chat cost item in
`test_audit_leftovers_chat.py`, the risk scope item in
`test_access_audit_security.py`.
"""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_audit_leftovers.py"
_CMP = APP / "comparison.py"
_MAIN = APP / "main.py"
_MP = APP / "market_phrase.py"
_P = 1600

MUTATIONS: tuple[Mutation, ...] = (
    # 1. a low-trust value produces no verdict at all
    Mutation(id="M1600", phase=_P, description="a COMPLIANT on an untrusted value is accepted",
             path=_CMP,
             anchor="_VERDICTS_HELD_ON_LOW_TRUST = frozenset({NON_COMPLIANT, COMPLIANT})\n",
             replacement="_VERDICTS_HELD_ON_LOW_TRUST = frozenset({NON_COMPLIANT})\n",
             target=_T, keyword="untrusted_value_is_held_too or held_compliance",
             tags=("honesty", "critical")),
    Mutation(id="M1601", phase=_P, description="the CRS question prints the LOW_TRUST_VALUE code",
             path=APP / "crs_mapping.py",
             anchor="    return re.sub(r\"^(?:[a-z_]+|[A-Z][A-Z_]+):\\s*\", \"\", text)\n",
             replacement="    return re.sub(r\"^[a-z_]+:\\s*\", \"\", text)\n",
             target=_T, keyword="held_compliance", tags=("honesty",)),
    # 2. no unit is said as no unit
    Mutation(id="M1602", phase=_P, description="two unitless values are blamed on units ''",
             path=_CMP, anchor="    if not got and not want:\n",
             replacement="    if False:\n",
             target=_T, keyword="no_unit_are_not_blamed", tags=("honesty",)),
    Mutation(id="M1603", phase=_P, description="one missing unit is printed as unit ''",
             path=_CMP, anchor="    if not got:\n",
             replacement="    if False:\n",
             target=_T, keyword="no_unit_are_not_blamed", tags=("honesty",)),
    Mutation(id="M1604", phase=_P, description="the recheck reads a missing-unit refusal as a judgement",
             path=APP / "claude_recheck.py",
             anchor="    if _NO_CONVERSION_PHRASE in rationale or comparison.UNIT_NOT_GUESSED_PHRASE in rationale:\n",
             replacement="    if _NO_CONVERSION_PHRASE in rationale:\n",
             target=_T, keyword="still_blocked_for_the_recheck", tags=("honesty",)),
    # 3. carried-forward bylines
    Mutation(id="M1605", phase=_P, description="a carried-forward byline prints the raw user id",
             path=_MAIN,
             anchor="                crs_mapping_mod.resolve_byline(record.get(\"comment_by\"), people),\n",
             replacement="                record.get(\"comment_by\"),\n",
             target=_T, keyword="carried_forward_byline", tags=("honesty",)),
    # 4. a re-raised rejection is marked
    Mutation(id="M1606", phase=_P, description="a re-raised rejected comment is shown blind",
             path=_MAIN,
             anchor="        if seen is None or row.get(\"engineer_confirmed\"):\n",
             replacement="        if True:\n",
             target=_T, keyword="rejected_on_an_earlier_run", tags=("honesty", "critical")),
    Mutation(id="M1607", phase=_P, description="a confirmed comment is marked 'previously rejected'",
             path=_MAIN,
             anchor="        if seen is None or row.get(\"engineer_confirmed\"):\n",
             replacement="        if seen is None:\n",
             target=_T, keyword="rejected_on_an_earlier_run", tags=("honesty",)),
    # 6. the market whitelist vouches for every word
    Mutation(id="M1608", phase=_P, description="market_phrase lets an unknown word through",
             path=_MP,
             anchor="        if _SUBJECT_WORD.match(low) and low not in _NOISE and vouched_for(low):\n",
             replacement="        if _SUBJECT_WORD.match(low) and low not in _NOISE:\n",
             target=_T, keyword="unknown_word_is_dropped", tags=("privacy", "critical")),
    Mutation(id="M1609", phase=_P, description="a British spelling is not vouched for",
             path=_MP, anchor="    for british, american in _BRITISH:\n",
             replacement="    for british, american in ():\n",
             target=_T, keyword="unknown_word_is_dropped", tags=("privacy",)),
    Mutation(id="M1613", phase=_P, description="the engineering-abbreviation supplement is not read",
             path=_MP, anchor="    return frozenset(words) | frozenset(extra)\n",
             replacement="    return frozenset(words)\n",
             target=_T, keyword="unknown_word_is_dropped", tags=("privacy",)),
    # 7. the streamed label is the final label
    Mutation(id="M1610", phase=_P, description="an image-only point streams as a bare [S1]",
             path=APP / "chat_stream.py",
             anchor="            clean, _labels = _relabel_image_only_citations(clean, self.passages or [])\n",
             replacement="",
             target=_T, keyword="streams_with_its_read_from_image_label", tags=("honesty",)),
    # 8. a charged fallback call is in the answer's cost
    Mutation(id="M1611", phase=_P, description="a charged first call is left out of the answer's cost",
             path=APP / "chat.py", anchor="    if fallback_spent:\n",
             replacement="    if False:\n",
             target="tests/test_audit_leftovers_chat.py", tags=("budget", "honesty")),
    Mutation(id="M1614", phase=_P, description="Claude-first does not report a charged fallback call",
             path=APP / "chat_claude_first.py",
             anchor="the Claude call failed\")\n        if on_fallback_cost is not None and turn_cost > 0:\n"
                    "            on_fallback_cost(round(turn_cost, 6))\n",
             replacement="the Claude call failed\")\n        if on_fallback_cost is not None and turn_cost > 0:\n"
                         "            pass\n",
             target="tests/test_audit_leftovers_chat.py", tags=("budget", "honesty")),
    # 5. a risk's source finding is in the caller's scope
    Mutation(id="M1612", phase=_P, description="POST /api/risks accepts a hidden source finding",
             path=_MAIN,
             anchor="        if source is None or not scope.may_read(source[\"document_id\"]):\n",
             replacement="        if False:\n",
             target="tests/test_access_audit_security.py",
             keyword="risk_citing_a_hidden_finding", tags=("security", "critical")),
    Mutation(id='M1615', phase=1615,
             description='the API response model drops the requirement types the extractor also stores (500 on the requirements list)',
             path=APP / 'schemas.py',
             anchor='RequirementType = Literal["numeric_limit", "statement", "table_value",\n                          "applicability_trigger", "relative_limit", "table_row",\n                          "definition"]',
             replacement='RequirementType = Literal["numeric_limit", "statement", "table_value"]',
             target='tests/test_requirement_types_contract.py', tags=('reliability',)),
)
