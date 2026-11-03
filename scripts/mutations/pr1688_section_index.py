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
        '    if (\n        in_attachment\n        and (m := d["item"].match(text))',
        '    if (\n        True\n        and (m := d["item"].match(text))',
        "heading_only_inside_an_attachment",
    ),
    _m(
        3,
        "a dash that differs between the chunk and the page text no longer finds the page",
        _S,
        '    return " ".join(str(line).replace("\\u2013", "-").replace("\\u2014", "-").split())',
        '    return " ".join(str(line).split())',
        "dash_that_differs",
    ),
    _m(
        4,
        "a generic title word is a cue again",
        _S,
        "p for p in phrases if p.lower() not in generic",
        "p for p in phrases",
        "generic_title",
    ),
    _m(
        5,
        "an indexed item or table title is the element's own section on one cue word alone",
        _S,
        '    if cued and chunk.get("heading_loose"):',
        "    if False:",
        "more_than_one_word_in_common",
    ),
    _m(
        6,
        "one shared word is enough for an item title to be about the element",
        _S,
        "    return len(shared) >= 2 or (bool(shared) and theirs <= mine)",
        "    return bool(shared)",
        "more_than_one_word_in_common",
    ),
    _m(
        7,
        "the playbook review never uses the index",
        _P,
        "    body = section_index.refine(body, document_id)\n",
        "    body = body\n",
        "attachment_titled_for_the_element",
    ),
    _m(
        8,
        "a partial hit still claims a section of its own",
        _S,
        '        "the closest section is at"\n        if enabled()\n        else "a section of its own was found at"\n',
        '        "a section of its own was found at"\n        if enabled()\n        else "a section of its own was found at"\n',
        "words_of_a_partial_hit",
    ),
)
