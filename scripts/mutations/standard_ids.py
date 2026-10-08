"""Mutations of the ONE standard-identifier matcher (#452; audit A02, A03):
backend/app/standard_ids.py and every caller moved onto it (applicability,
chat_tools, understanding, chat_comparison, claude_selection, answerability).
Each puts one old defect back; its target test must fail.
Targets: backend/tests/test_standard_matcher.py, test_b8_answerability.py.

Ids start at M2501 (not max+1) to leave room for the other sessions working in
parallel on 2026-10-08; the harness refuses a duplicate at import either way.
"""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_standard_matcher.py"
_IDS = APP / "standard_ids.py"
_APP = APP / "applicability.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M2501", phase=2501, description="the prefix rule is back: API 65 finds API 650",
             path=_APP,
             anchor="        if any(standard_ids.same_standard(identifier, name) for name in _library_names(entry)):\n",
             replacement="        if any(key.startswith(normalise_identifier(n)) or normalise_identifier(n).startswith(key)"
                         " for n in _library_names(entry)):\n",
             target=_T, keyword="different_number_never_matches", tags=("w3",)),
    Mutation(id="M2502", phase=2502, description="a part or division no longer has to agree",
             path=_IDS,
             anchor="    return a.identity == b.identity and (a.part is None or b.part is None or a.part == b.part)\n",
             replacement="    return a.identity == b.identity\n",
             target=_T, keyword="part_one_never_matches_part_two", tags=("w3",)),
    Mutation(id="M2503", phase=2503, description="SAES-B-14 is no longer SAES-B-014 (no zero padding)",
             path=_IDS,
             anchor="    return StandardId(\"SAES\", f\"{m.group('letter')}-{int(m.group('num')):03d}\")\n",
             replacement="    return StandardId(\"SAES\", f\"{m.group('letter')}-{m.group('num')}\")\n",
             target=_T, keyword="SAES", tags=("w3",)),
    Mutation(id="M2504", phase=2504, description="NACE MR0175 is no longer ISO 15156",
             path=_IDS,
             anchor="_EQUIVALENT = {(\"NACE\", \"MR0175\"): (\"ISO\", \"15156\")}\n",
             replacement="_EQUIVALENT: dict = {}\n",
             target=_T, keyword="NACE", tags=("w3",)),
    Mutation(id="M2505", phase=2505, description="the API part is not read, so Pt-1 meets Part II",
             path=_IDS,
             anchor="    return StandardId(\"API\", m.group(\"num\"), _part(m))\n",
             replacement="    return StandardId(\"API\", m.group(\"num\"))\n",
             target=_T, keyword="part_one_never_matches_part_two", tags=("w3",)),
    Mutation(id="M2506", phase=2506, description="two spellings of one missing standard are listed twice",
             path=_APP,
             anchor="        key = standard_ids.key(name)\n        if not key or key in seen:\n",
             replacement="        key = normalise_identifier(name)\n        if not key or key in seen:\n",
             target=_T, keyword="listed_once", tags=("w3",)),
    Mutation(id="M2507", phase=2507, description="select rebuilds its own missing list again",
             path=_APP,
             anchor="        for identifier in missing_references(library, referenced)\n",
             replacement="        for identifier in referenced\n",
             target=_T, keyword="uses_the_held_api_520", tags=("w3",)),
    Mutation(id="M2508", phase=2508, description="the chat tool looks an identifier up in a dict keyed by document id",
             path=APP / "chat_tools.py",
             anchor="        entry = applicability.find_standard(library, identifier)\n",
             replacement="        entry = applicability._match_referenced(library, cited).get("
                         "applicability.normalise_identifier(identifier))\n",
             target=_T, keyword="chat_tool_reports", tags=("w3",)),
    Mutation(id="M2509", phase=2509, description="a question naming API 520 Part I no longer finds API-520-I",
             path=APP / "understanding.py",
             anchor="        if parsed is not None and parsed.family in standard_ids.SPECIFIC_FAMILIES \\\n",
             replacement="        if False and parsed is not None and parsed.family in standard_ids.SPECIFIC_FAMILIES \\\n",
             target=_T, keyword="scoped_to_that_file", tags=("w3",)),
    Mutation(id="M2510", phase=2510, description="the compare check is a substring test again",
             path=APP / "chat_comparison.py",
             anchor="        if key in have or any(standard_ids.same_standard(token, n) for n in matched_names):\n",
             replacement="        if key in have or any(key in h or h in key for h in have):\n",
             target=_T, keyword="compare_naming_api_65", tags=("w3",)),
    Mutation(id="M2511", phase=2511, description="the contractual gate compares exact keys again",
             path=APP / "claude_selection.py",
             anchor="    return any(standard_ids.same_standard(code, r)\n",
             replacement="    return any(applicability.normalise_identifier(code) == applicability.normalise_identifier(r)\n",
             target=_T, keyword="contractual_gate", tags=("w3",)),
    Mutation(id="M2512", phase=2512, description="a deferral is compared with held standards by exact key again",
             path=APP / "answerability.py",
             anchor="                   if not any(standard_ids.same_standard(ref, d) for d in held)\n",
             replacement="                   if not any(standard_ids.flat_key(ref) == standard_ids.flat_key(d) for d in held)\n",
             target="tests/test_b8_answerability.py", keyword="written_another_way", tags=("w3",)),
)
