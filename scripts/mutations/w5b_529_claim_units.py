"""#529: claim units for written documents. Ids M5301-M5313."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_w5b_529_claim_units.py"
_P = APP / "claim_units.py"
_TAG = ("w5b", "claims")


def _m(i, desc, anchor, repl, kw=None):
    return Mutation(id=f"M{i}", phase=i, description=desc, path=_P, anchor=anchor,
                    replacement=repl, target=_T, keyword=kw, tags=_TAG)


MUTATIONS: tuple[Mutation, ...] = (
    _m(5301, "a sentence with no obligation word becomes a unit",
       "            if not standards._MANDATORY.search(sentence):\n                continue\n", "",
       "without_an_obligation_word"),
    _m(5302, "a heading that happens to hold 'shall' becomes a unit",
       "            if len(sentence.split()) < standards.MIN_REQUIREMENT_WORDS:\n                continue      # a heading or a cell that happens to contain \"shall\"\n", ""),
    _m(5303, "the running footer is left inside the sentence",
       "claims.split_sentences(standards.strip_page_furniture(text))", "claims.split_sentences(text)",
       "running_footer"),
    _m(5304, "a numbered list is one unit, not one per item",
       "        for sentence in standards._requirement_parts(joined):", "        for sentence in [joined]:",
       "numbered_list"),
    _m(5305, "table rows are never produced",
       "            units += table_rows_on_page(document_id, page[\"page_no\"], stored)", "            pass",
       "ruled_table"),
    _m(5306, "a Word file's tables are sent to the row parser",
       "        if stored and not office:", "        if stored:", "word_files_tables"),
    _m(5307, "a standard named twice on a page is two units",
       "    for printed in standard_ids.cited_standards(text):",
       "    for printed, _s, _e in standard_ids.find_citations(text):", "named_twice"),
    _m(5308, "pages with no text are not counted", "            unread += 1\n            continue", "            continue",
       "no_text_are_counted"),
    _m(5309, "a document with no readable page is reported ok", "    if read == 0:", "    if False:", "no_readable_page"),
    _m(5310, "a document with no unit is reported ok", "    elif not units:", "    elif False:", "no_unit"),
    _m(5311, "a document the caller may not read is read",
       "    if document_id not in allowed_document_ids:", "    if False:", "may_not_read"),
    _m(5312, "every unit is cited to page 1",
       "        units += obligations_on_page(document_id, page[\"page_no\"], text)",
       "        units += obligations_on_page(document_id, 1, text)", "its_page"),
    _m(5313, "the unit id changes between calls (unstable)",
       "    ident = hashlib.sha1(f\"{document_id}|{kind}|{page}|{ordinal}|{text}\".encode(\"utf-8\")).hexdigest()[:16]",
       "    import time\n    ident = hashlib.sha1(f\"{time.time_ns()}{text}\".encode(\"utf-8\")).hexdigest()[:16]", "stable"),
)
