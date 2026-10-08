"""Mutations of the ONE standard-identifier matcher (#452; audit A02, A03):
backend/app/standard_ids.py and every caller moved onto it (applicability,
chat_tools, understanding, chat_comparison, claude_selection, answerability).
Each puts one old defect back; its target test must fail.
Targets: backend/tests/test_standard_matcher.py, test_b8_answerability.py.

Ids M2601 to M2616. They were M2501 onwards until 2026-10-08, when #614 took
M2501 to M2518 (and #619 has M2421 to M2424); renumbered to avoid the clash.
The harness refuses a duplicate at import either way.
"""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_standard_matcher.py"
_IDS = APP / "standard_ids.py"
_APP = APP / "applicability.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M2601", phase=2601, description="the prefix rule is back: API 65 finds API 650",
             path=_APP,
             anchor="        if any(standard_ids.same_standard(identifier, name) for name in _library_names(entry)):\n",
             replacement="        if any(key.startswith(normalise_identifier(n)) or normalise_identifier(n).startswith(key)"
                         " for n in _library_names(entry)):\n",
             target=_T, keyword="different_number_never_matches", tags=("w3",)),
    Mutation(id="M2602", phase=2602, description="a part or division no longer has to agree",
             path=_IDS,
             anchor="    return a.identity == b.identity and (a.part is None or b.part is None or a.part == b.part)\n",
             replacement="    return a.identity == b.identity\n",
             target=_T, keyword="part_one_never_matches_part_two", tags=("w3",)),
    Mutation(id="M2603", phase=2603, description="SAES-B-14 is no longer SAES-B-014 (no zero padding)",
             path=_IDS,
             anchor="    return StandardId(\"SAES\", f\"{m.group('letter')}-{int(m.group('num')):03d}\")\n",
             replacement="    return StandardId(\"SAES\", f\"{m.group('letter')}-{m.group('num')}\")\n",
             target=_T, keyword="SAES", tags=("w3",)),
    Mutation(id="M2604", phase=2604, description="the vocabulary file's equivalences are ignored (NACE MR0175 is not ISO 15156)",
             path=_IDS,
             anchor="        return _equivalences().get((self.family, self.number), (self.family, self.number))\n",
             replacement="        return (self.family, self.number)\n",
             target=_T, keyword="NACE or vocabulary_file_changes", tags=("w3",)),
    Mutation(id="M2605", phase=2605, description="the API part is not read, so Pt-1 meets Part II",
             path=_IDS,
             anchor="    return StandardId(\"API\", m.group(\"num\"), _part(m))\n",
             replacement="    return StandardId(\"API\", m.group(\"num\"))\n",
             target=_T, keyword="part_one_never_matches_part_two", tags=("w3",)),
    Mutation(id="M2606", phase=2606, description="two spellings of one missing standard are listed twice",
             path=_APP,
             anchor="        key = standard_ids.key(name)\n        if not key or key in seen:\n",
             replacement="        key = normalise_identifier(name)\n        if not key or key in seen:\n",
             target=_T, keyword="listed_once", tags=("w3",)),
    Mutation(id="M2607", phase=2607, description="select rebuilds its own missing list again",
             path=_APP,
             anchor="        for identifier in missing_references(library, referenced)\n",
             replacement="        for identifier in referenced\n",
             target=_T, keyword="uses_the_held_api_520", tags=("w3",)),
    Mutation(id="M2608", phase=2608, description="the chat tool looks an identifier up in a dict keyed by document id",
             path=APP / "chat_tools.py",
             anchor="        entry = applicability.find_standard(library, identifier)\n",
             replacement="        entry = applicability._match_referenced(library, cited).get("
                         "applicability.normalise_identifier(identifier))\n",
             target=_T, keyword="chat_tool_reports", tags=("w3",)),
    Mutation(id="M2609", phase=2609, description="a question naming API 520 Part I no longer finds API-520-I",
             path=APP / "understanding.py",
             anchor="        if parsed is not None and parsed.family in standard_ids.SPECIFIC_FAMILIES \\\n",
             replacement="        if False and parsed is not None and parsed.family in standard_ids.SPECIFIC_FAMILIES \\\n",
             target=_T, keyword="scoped_to_that_file", tags=("w3",)),
    Mutation(id="M2610", phase=2610, description="the compare check is a substring test again",
             path=APP / "chat_comparison.py",
             anchor="        if key in have or any(standard_ids.same_standard(token, n) for n in matched_names):\n",
             replacement="        if key in have or any(key in h or h in key for h in have):\n",
             target=_T, keyword="compare_naming_api_65", tags=("w3",)),
    Mutation(id="M2611", phase=2611, description="the contractual gate compares exact keys again",
             path=APP / "claude_selection.py",
             anchor="    return any(standard_ids.same_standard(code, r)\n",
             replacement="    return any(applicability.normalise_identifier(code) == applicability.normalise_identifier(r)\n",
             target=_T, keyword="contractual_gate", tags=("w3",)),
    Mutation(id="M2612", phase=2612, description="a deferral is compared with held standards by exact key again",
             path=APP / "answerability.py",
             anchor="                   if not any(standard_ids.same_standard(ref, d) for d in held)\n",
             replacement="                   if not any(standard_ids.flat_key(ref) == standard_ids.flat_key(d) for d in held)\n",
             target="tests/test_b8_answerability.py", keyword="written_another_way", tags=("w3",)),
    Mutation(id="M2613", phase=2613, description="a national adoption is not the adopted standard (BS EN 13445-3 is not EN 13445)",
             path=_IDS,
             anchor='            family = vocabulary()["body_aliases"].get(family, family)\n',
             replacement="",
             target=_T, keyword="unseen and EN", tags=("w3",)),
    Mutation(id="M2614", phase=2614, description="a joint body (ANSI/ISA) is not read by the general shape",
             path=_IDS,
             anchor=r'    r"^\s*(?P<fam>[A-Z]{2,6}(?:/[A-Z]{2,6})?)',
             replacement=r'    r"^\s*(?P<fam>[A-Z]{2,6})',
             target=_T, keyword="unseen and ISA", tags=("w3",)),
    Mutation(id="M2615", phase=2615, description="the general shape is switched off: only the special-cased families are read",
             path=_IDS,
             anchor="        m = _GENERIC.match(clean)\n",
             replacement="        m = None\n",
             target=_T, keyword="unseen", tags=("w3",)),
    Mutation(id="M2616", phase=2616, description="the API document words are hard-coded instead of read from the vocabulary file",
             path=_IDS,
             anchor='    api_words = "|".join(re.escape(w) for w in vocabulary()["api_document_words"]) or "(?!)"\n',
             replacement='    api_words = "RP|STD|STANDARD|SPEC|PUBL|MPMS|BULL|TR"\n',
             target=_T, keyword="api_document_words_come_from", tags=("w3",)),
)
