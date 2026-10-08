"""Mutations of the citation reader (#623): `standard_ids.find_citations` /
`cited_standards`, which `datasheets.referenced_standards` and
`referenced_standard_spans` now delegate to. Each puts one old defect back or
removes one false-positive guard; its target test must fail.
Target: backend/tests/test_citation_reader.py. Ids M2801 onwards.
"""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_citation_reader.py"
_IDS = APP / "standard_ids.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M2801", phase=2801, description="the general shape is not used in running text: IEC, EN and ISA go unread again",
             path=_IDS,
             anchor="    for pattern in [general, *classes]:\n",
             replacement="    for pattern in classes:\n",
             target=_T, keyword="iec_en_isa_and_iso or unseen_citations", tags=("w3",)),
    Mutation(id="M2802", phase=2802, description="a body name inside a tag or a document number is read as a citation",
             path=_IDS,
             anchor="        if start < taken_until or not _standalone(text, start, end):\n",
             replacement="        if start < taken_until:\n",
             target=_T, keyword="tags_document_numbers", tags=("w3",)),
    Mutation(id="M2803", phase=2803, description="the general shape reads lower-case words as bodies (\"rated en 1200 rpm\")",
             path=_IDS,
             anchor="        for m in pattern.finditer(folded):\n",
             replacement="        for m in pattern.finditer(upper):\n",
             target=_T, keyword="tags_document_numbers", tags=("w3",)),
    Mutation(id="M2804", phase=2804, description="a short API number in prose is read as a citation (\"API 20 units\")",
             path=_IDS,
             anchor="        return bool(_API_IN_TEXT.fullmatch(m.group(\"num\")))\n",
             replacement="        return True\n",
             target=_T, keyword="tags_document_numbers", tags=("w3",)),
    Mutation(id="M2805", phase=2805, description="two equivalent standards that were both cited are merged into one",
             path=_IDS,
             anchor="        seen.setdefault(ident.literal_key() if ident else flat_key(raw), raw)\n",
             replacement="        seen.setdefault(ident.key() if ident else flat_key(raw), raw)\n",
             target=_T, keyword="equivalent_standards_both_cited", tags=("w3",)),
    Mutation(id="M2806", phase=2806, description="a sub-part is cut off, so IEC 60534-2-1 is rejected as a glued code",
             path=_IDS,
             anchor="        while (sub := _SUB_PART.match(text, end)) is not None:\n",
             replacement="        while False and (sub := _SUB_PART.match(text, end)) is not None:\n",
             target=_T, keyword="unseen_citations", tags=("w3",)),
    Mutation(id="M2807", phase=2807, description="the issuing bodies are no longer read from the vocabulary file",
             path=_IDS,
             anchor="        \"citation_bodies\": [b.upper() for b in data.get(\"citation_bodies\") or []],\n",
             replacement="        \"citation_bodies\": [\"IEC\", \"EN\", \"BS\", \"ISA\", \"ANSI\", \"DIN\", \"NORSOK\", \"KOC\"],\n",
             target=_T, keyword="issuing_bodies_come_from", tags=("w3",)),
)
