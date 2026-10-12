"""Mutations for family-of-standards search (issue #373, 2026-10-01, M1860-M1869).
Files: backend/app/family_search.py, backend/app/chat.py.
Target: backend/tests/test_family_search.py.
"""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_family_search.py"
_F = APP / "family_search.py"
_TAG = ("family_search",)

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1860", phase=1860,
             description="the resolved standards are searched as ONE shared pool again, not each on its own",
             path=_F,
             anchor="    sides = resolved[\"candidates\"]\n",
             replacement=("    sides = resolved[\"candidates\"]\n"
                          "    if sides:\n"
                          "        sides = [(\"all\", frozenset().union(*(i for _, i in sides))),"
                          " (\"none\", frozenset())]\n"),
             target=_T, keyword="shared_search_hides", tags=_TAG),
    Mutation(id="M1861", phase=1861,
             description="the answer no longer says membership is a guess",
             path=_F,
             anchor='" Which standards belong to this family is a guess made by this app "',
             replacement='" Which standards belong to this family are listed here by this app "',
             target=_T, keyword="calls_membership_a_guess", tags=_TAG),
    Mutation(id="M1862", phase=1862,
             description="the family step runs after a comparison already answered and overwrites it",
             path=APP / "chat.py",
             anchor="    if (comparison_result is None and inventory_result is None and explain_of is None\n"
                    "            and document_id is None",
             replacement="    if (inventory_result is None and explain_of is None\n"
                         "            and document_id is None",
             target=_T, keyword="existing_compare_path", tags=_TAG),
    Mutation(id="M1863", phase=1863,
             description="a question that types a standard designation can still be read as a family question",
             path=_F,
             anchor="    if not text or _TYPED.search(text):\n",
             replacement="    if not text:\n",
             target=_T, keyword="not_intercepted", tags=_TAG),
    Mutation(id="M1864", phase=1864,
             description="a descriptor that describes nothing (\"applicable standards\") names a family",
             path=_F,
             anchor="    descriptor = [w for w in descriptor if w not in _GENERIC and len(w) >= 3]\n",
             replacement="    descriptor = [w for w in descriptor if len(w) >= 3]\n",
             target=_T, keyword="not_intercepted", tags=_TAG),
    Mutation(id="M1865", phase=1865,
             description="\"welding standards for pumps\" is read as a topic lookup",
             path=_F,
             anchor='    if after.group("prep").lower() == "for" and not after.group("mid").strip():\n',
             replacement="    if False:\n",
             target=_T, keyword="not_intercepted", tags=_TAG),
    Mutation(id="M1866", phase=1866,
             description="candidates are ranked over every document, not only what the caller may read",
             path=_F,
             anchor="    resolved = resolve(descriptor, allowed_document_ids=allowed_document_ids, topic=topic)\n",
             replacement="    resolved = resolve(descriptor, allowed_document_ids=search.every_document_id(), topic=topic)\n",
             target=_T, keyword="may_not_read", tags=_TAG),
    Mutation(id="M1867", phase=1867,
             description="any readable document, not only a COMPANY_STANDARD, can be a candidate",
             path=_F,
             anchor="WHERE c.document_role = 'COMPANY_STANDARD' AND d.id IN",
             replacement="WHERE d.id IN",
             target=_T, keyword="not_a_standard", tags=_TAG),
    Mutation(id="M1868", phase=1868,
             description="the cap of 8 standards is lifted",
             path=_F,
             anchor="MAX_STANDARDS = 8\n",
             replacement="MAX_STANDARDS = 50\n",
             target=_T, keyword="no_more_than_eight", tags=_TAG),
    Mutation(id="M1869", phase=1869,
             description="a family that resolves to one standard is still presented as a per-standard search",
             path=_F,
             anchor="    if len(sides) < 2:\n",
             replacement="    if len(sides) < 1:\n",
             target=_T, keyword="fewer_than_two", tags=_TAG),
    Mutation(id="M1881", phase=1881,
             description="a trailing e is no longer trimmed, so valve and valves stop meeting",
             path=_F,
             anchor='    if w.endswith("e") and len(w) > 3:\n        w = w[:-1]\n',
             replacement='',
             target=_T, keyword="singular_plural_and_ing", tags=_TAG),
)
