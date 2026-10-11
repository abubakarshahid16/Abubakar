"""#454 (audit B04): a tool-only answer keeps its document ids. Ids M6601-M6606."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_w3_454_tool_answer_ids.py"
_C = APP / "chat_tools.py"
_TAG = ("w3", "citations")


def _m(i, desc, anchor, repl, kw=None):
    return Mutation(id=f"M{i}", phase=i, description=desc, path=_C, anchor=anchor,
                    replacement=repl, target=_T, keyword=kw, tags=_TAG)


MUTATIONS: tuple[Mutation, ...] = (
    _m(6601, "the cited-standards tool returns text only again",
       "                   _cited_standard_sources(doc, document_id, cited, held,\n"
       "                                           allowed_document_ids=allowed_document_ids),\n", "",
       "returns_sources or not_general_knowledge"),
    _m(6602, "a citation with no page gets a guessed page",
       "        if page is None or not quote:\n            continue\n",
       "        if not quote:\n            page, quote = 1, identifier\n", "no_page"),
    _m(6603, "the submittal's citations are not sources",
       "        sources.append({\"chunk_id\": f\"cite_{document_id}_{i}\", \"document_id\": document_id,",
       "        (lambda *_: None)({\"chunk_id\": f\"cite_{document_id}_{i}\", \"document_id\": document_id,",
       "returns_sources"),
    _m(6604, "a held standard is not a source", "    for h in held:\n        std_id", "    for h in []:\n        std_id",
       "returns_sources"),
    _m(6605, "a standard outside the grants becomes a source",
       "        std = _readable(std_id or \"\", allowed_document_ids=allowed_document_ids)\n        if std is None:\n            continue\n",
       "        std = {\"filename\": h.get(\"filename\")}\n",
       "outside_the_grants"),
    _m(6606, "the source's page is not the page the citation is on",
       "                        \"filename\": doc[\"filename\"], \"page_start\": page, \"page_end\": page,",
       "                        \"filename\": doc[\"filename\"], \"page_start\": None, \"page_end\": None,",
       "returns_sources"),
)
