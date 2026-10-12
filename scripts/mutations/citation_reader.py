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
    # ---- #628 review: number-group separators and plain words
    Mutation(id="M2808", phase=2808, description="only the first reading is compared: ASME-B16-47 is B16 Part 47 again",
             path=_IDS,
             anchor="               for x in a.readings() for y in b.readings())\n",
             replacement="               for x in (a,) for y in (b,))\n",
             target=_T, keyword="hyphens_and_no_metadata or separators_are_spelling or hyphen_named_held_file",
             tags=("w3",)),
    Mutation(id="M2809", phase=2809, description="the ASME B shape needs a dot again, so B16-47 in running text is not read",
             path=_IDS,
             anchor=r'(?P<num>\d{1,2}(?:(?:\.\d{1,3}){1,2}|[-_ ]\d{1,3}(?![\d.])))" + _END),',
             replacement=r'(?P<num>\d{1,2}(?:\.\d{1,3}){1,2})" + _END),',
             target=_T, keyword="written_asme_number_is_read_in_running_text", tags=("w3",)),
    Mutation(id="M2810", phase=2810, description="an underscore is not a space, so asme_b16_47 is not read",
             path=_IDS,
             anchor='    return _DASHES.sub("-", " ".join((text or "").replace("_", " ").split())).upper()\n',
             replacement='    return _DASHES.sub("-", " ".join((text or "").split())).upper()\n',
             target=_T, keyword="hyphens_and_no_metadata or separators_are_spelling", tags=("w3",)),
    Mutation(id="M2811", phase=2811, description="the alternative reading of trailing number groups is never made",
             path=_IDS,
             anchor='            tail = _NUMBER_TAIL.match(clean, m.end("num"))\n',
             replacement="            tail = None\n",
             target=_T, keyword="hyphens_and_no_metadata or separators_are_spelling", tags=("w3",)),
    Mutation(id="M2812", phase=2812, description="a deferral to a plain word (HVAC, CMP) is listed as a missing standard again",
             path=APP / "standards_inventory.py",
             anchor="        if not found:\n            continue\n        identifier = found[0][0]\n",
             replacement="",
             target=_T, keyword="deferral_to_a_plain_word", tags=("w3",)),
    Mutation(id="M2813", phase=2813, description="any upper-case word with a number is a body, so HVAC 3 and CMP 2 become standards",
             path=_IDS,
             anchor='    alt = "|".join(re.escape(b) for b in bodies) or "(?!)"\n',
             replacement='    alt = "[A-Z]{2,6}"\n',
             target=_T, keyword="plain_words_and_abbreviations", tags=("w3",)),
)
