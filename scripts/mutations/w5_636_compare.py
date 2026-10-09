"""#636 "chat compare: one named standard is one side": each entry deletes one
part; backend/tests/test_w5_636_compare_one_standard.py must notice."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_w5_636_compare_one_standard.py"
_TAG = ("w5_636", "compare")


def _m(i, desc, path, anchor, repl, kw=None):
    return Mutation(id=f"M{i}", phase=i, description=desc, path=APP / path,
                    anchor=anchor, replacement=repl, target=_T, keyword=kw, tags=_TAG)


C = "chat_comparison.py"
MUTATIONS: tuple[Mutation, ...] = (
    _m(3901, "sides are grouped by document, not by the standard's identity", C,
       "groups.setdefault(_identity_key(_stem(documents[doc_id])), []).append(doc_id)",
       "groups.setdefault(doc_id, []).append(doc_id)"),
    _m(3902, "two editions of one standard are merged into one side", C,
       "        if len({e for e in editions if e}) < 2:\n", "        if True:\n",
       "two_editions"),
    _m(3903, "the chat route goes back to the old side matcher", "chat.py",
       "        comparison_sides, comparison_missing = chat_comparison.resolve_sides(\n            resolved, documents_map)\n",
       "        comparison_sides = chat_comparison.matched_sides(resolved, documents_map)\n"
       "        comparison_missing = (chat_comparison.missing_designations(\n"
       "            resolved, [n for n, _ in comparison_sides]) if comparison_sides else [])\n",
       "the_route_gives_one_side"),
    _m(3904, "the topic keeps the standards' names", C,
       "for _label, start, end in sorted(standard_ids.find_citations(text), key=lambda c: -c[1]):",
       "for _label, start, end in []:", "topic"),
    _m(3905, "a standard typed without its issuing body is not the held one", C,
       "    return bool(have) and (want.endswith(have) or have.endswith(want))\n", "    return False\n"),
    _m(3906, "a bare designation inside a citation is counted as a second standard", C,
       'if not re.search(r"\\d", token) or any(s <= m.start() and m.end() <= e for s, e in spans):',
       'if not re.search(r"\\d", token):'),
    _m(3907, "an edition side carries no edition label", C,
       'label = f"{base} ({edition})" if edition else f"{base} (edition not stated)"',
       'label = f"{base}"', "edition"),
    _m(3908, "the first printed year wins as the edition", "standard_ids.py",
       "    return years[-1] if years else None\n", "    return years[0] if years else None\n",
       "edition_is_a_printed_year"),
)
