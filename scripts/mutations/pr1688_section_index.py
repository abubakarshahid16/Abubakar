"""Mutations of the review-time section index (test B / HAZOP, part of #805; PR 1688)."""

from __future__ import annotations

from ._base import REPO, Mutation

_S = REPO / "backend" / "app" / "section_index.py"
_P = REPO / "backend" / "app" / "playbooks.py"
_T = "tests/test_section_index.py"


def _m(
    n: int, description: str, path, anchor: str, replacement: str, keyword: str
) -> Mutation:
    return Mutation(
        id=f"M1688-{n:02d}",
        phase=1688,
        description=description,
        path=path,
        anchor=anchor,
        replacement=replacement,
        target=_T,
        keyword=keyword,
        tags=("playbook", "sections"),
    )


MUTATIONS: tuple[Mutation, ...] = (
    _m(
        1,
        "the switch is ignored: the index re-splits the body even when off",
        _S,
        "    if not enabled():\n        return body\n",
        "    if False:\n        return body\n",
        "refine_off_returns",
    ),
    _m(
        2,
        "a numbered item is a heading outside an attachment too",
        _S,
        '    if in_attachment and d["item"].match(text)',
        '    if True and d["item"].match(text)',
        "heading_only_inside_an_attachment",
    ),
    _m(
        3,
        "a generic title word is a cue again",
        _S,
        "p for p in phrases if p.lower() not in generic",
        "p for p in phrases",
        "generic_title",
    ),
    _m(
        4,
        "an indexed title is the element's own section on one cue word alone",
        _S,
        "    return _about(element.title, title)\n",
        "    return True\n",
        "more_than_one_word_in_common",
    ),
    _m(
        5,
        "one shared word is enough for an indexed title to be about the element",
        _S,
        "    return len(shared) >= 2 or (bool(shared) and theirs <= mine)",
        "    return bool(shared)",
        "more_than_one_word_in_common",
    ),
    _m(
        6,
        "the playbook review never uses the index",
        _P,
        "    body = section_index.refine(body, document_id)\n",
        "    body = body\n",
        "attachment_titled_for_the_element",
    ),
    _m(
        7,
        "a partial hit still claims a section of its own",
        _S,
        '        "the closest section is at"\n        if enabled()\n        else "a section of its own was found at"\n',
        '        "a section of its own was found at"\n        if enabled()\n        else "a section of its own was found at"\n',
        "words_of_a_partial_hit",
    ),
    _m(
        8,
        "a heading is cited at the first page it is printed on, not the page of its own print",
        _S,
        "                cursor = (at[0], at[1] + 1)\n",
        '                cursor = (chunk.get("page_start") or 0, 0)\n',
        "heading_printed_twice",
    ),
    _m(
        9,
        "a title repeated on every page is a heading",
        _S,
        "            if heading and _flat(heading) not in running:\n",
        "            if heading:\n",
        "running_header",
    ),
    _m(
        10,
        "a table of contents entry with dot leaders is a heading",
        _S,
        '    if _LEADERS.search(str(line or "")):\n        return None\n',
        "",
        "contents_list_without_a_contents_heading",
    ),
    _m(
        11,
        "a list of headings printed on a page is taken for the headings",
        _S,
        "            if lines[at] == heading and at not in listed:\n",
        "            if lines[at] == heading:\n",
        "list_of_headings_on_an_earlier_page",
    ),
    _m(
        14,
        "three heading-like lines in a row inside a passage are sections",
        _S,
        "        for i, heading in _drop_contents_runs(found, lines):\n",
        "        for i, heading in found:\n",
        "three_heading_like_lines",
    ),
    _m(
        12,
        "a coded attachment with one cue word is the element's section (found), not the closest",
        _S,
        '    if near and chunk.get("heading_code"):\n        return True\n',
        '    if chunk.get("heading_code"):\n        return True\n',
        "closest_section_never_found",
    ),
    _m(
        13,
        "a row citing a title-only section loses its verified quote",
        _P,
        "    for title in section_index.heading_quotes(_chunk_of(ev, body)) if quote is None else ():\n",
        "    for title in ():\n",
        "verified_title",
    ),
)
