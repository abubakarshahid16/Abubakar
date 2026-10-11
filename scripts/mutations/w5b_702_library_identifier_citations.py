"""#702: a standard cited by the library's own identifier is found. Ids M5401-M5412."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_w5b_702_library_identifier_citations.py"
_A = APP / "applicability.py"
_TAG = ("w5b", "applicability")


def _m(i, desc, anchor, repl, kw=None, path=_A):
    return Mutation(id=f"M{i}", phase=i, description=desc, path=path, anchor=anchor,
                    replacement=repl, target=_T, keyword=kw, tags=_TAG)


MUTATIONS: tuple[Mutation, ...] = (
    _m(5401, "the library's own numbers are never looked for in the submittal",
       "        library_citations(library, submittal_text),\n", "", "citing_the_librarys_document_number"),
    _m(5402, "a document number match is only a possible match",
       '                "method": METHOD_REFERENCED, "identifier": number,',
       '                "method": METHOD_POSSIBLE, "identifier": number,', "citing_the_librarys_document_number"),
    _m(5403, "a number is matched as a substring",
       "if _identifier_like(number) and standard_ids.names_standard(text, number):",
       "if _identifier_like(number) and number.upper() in text.upper():", "longer_number"),
    _m(5404, "a file name number counts as a full citation",
       '                "method": METHOD_POSSIBLE, "identifier": from_file,',
       '                "method": METHOD_REFERENCED, "identifier": from_file,', "file_name"),
    _m(5405, "a file name number is not looked for",
       "        if from_file and standard_ids.names_standard(text, from_file):", "        if False:", "file_name"),
    _m(5406, "the edition group stays in the file-name number",
       "    while len(groups) > 2 and _EDITION_GROUP.match(groups[-1]):", "    while False:", "edition_group"),
    _m(5407, "a one- or two-word title is matched",
       '        if len(title.split()) >= 3 and f" {title} " in folded_text:',
       '        if len(title.split()) >= 1 and f" {title} " in folded_text:', "fewer_than_three_words"),
    _m(5408, "titles are never matched",
       '        if len(title.split()) >= 3 and f" {title} " in folded_text:', "        if False:", "title"),
    _m(5409, "a possible match is included in the review",
       '    "manual", "referenced", "equipment_type", "scope", "service", "project"})',
       '    "manual", "referenced", "possible_citation", "equipment_type", "scope", "service", "project"})',
       "possible_match"),
    _m(5410, "no evidence page or quote for a library-number citation",
       "        if row[\"method\"] in (METHOD_REFERENCED, METHOD_POSSIBLE) and row.get(\"identifier\"):",
       "        if row[\"method\"] == METHOD_REFERENCED and row.get(\"identifier\") and False:", "citing_the_librarys_document_number or only_in_its_file_name"),
    _m(5411, "the printed line is not searched for the library's own number",
       "    pattern = standard_ids._token_pattern(identifier) if identifier else None",
       "    pattern = None", "citing_the_librarys_document_number or only_in_its_file_name"),
    _m(5412, "the chat tool does not list library-number citations",
       "    for std_id, hit in applicability.library_citations(library, text).items():",
       "    for std_id, hit in {}.items():", "chat_tool_lists", path=APP / "chat_tools.py"),
)
