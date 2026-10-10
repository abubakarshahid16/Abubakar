"""#618: the text-quality gate uses a real word list. Ids M6401-M6405."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_w2b_618_word_list.py"
_Q = APP / "requirement_quality.py"
_TAG = ("w2b", "quality")


def _m(i, desc, anchor, repl, kw=None):
    return Mutation(id=f"M{i}", phase=i, description=desc, path=_Q, anchor=anchor,
                    replacement=repl, target=_T, keyword=kw, tags=_TAG)


MUTATIONS: tuple[Mutation, ...] = (
    _m(6401, "the short built-in list is the only vocabulary again",
       "    return word in _COMMON or vouched_for(word)", "    return word in _COMMON",
       "committed_dictionary or ordinary_engineering"),
    _m(6402, "the dictionary-share rule is not applied",
       "    if forward / len(words) < _MIN_KNOWN_SHARE:\n        return TEXT_QUALITY\n", "",
       "keeps_its_vowels"),
    _m(6403, "the share threshold is loosened to one half",
       "_MIN_KNOWN_SHARE = 0.6\n", "_MIN_KNOWN_SHARE = 0.5\n", "first_word or keeps_its_vowels"),
    _m(6404, "unknown capitalised names count as garbling",
       "             if i == 0 or not (w[:1].isupper() and not _known(w.lower()))]",
       "             if True]", "trade_names or ordinary_engineering"),
    _m(6405, "the first word is treated as a name",
       "             if i == 0 or not (w[:1].isupper() and not _known(w.lower()))]",
       "             if not (w[:1].isupper() and not _known(w.lower()))]", "first_word"),
)
