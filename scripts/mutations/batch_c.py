"""Mutations for batch C (2026-10-02, M1930-M1939): a standard that covers the
topic was refused as "common", quotes cut at "P-No.", and the family's eight
chosen by name. Files: backend/app/chat_comparison.py, lexical.py,
sentence_guard.py, answer.py, claims.py, chat_stream.py, family_search.py.
Targets: test_compare_commonness.py, test_sentence_abbreviations.py,
test_family_search.py.
"""

from __future__ import annotations

from ._base import APP, Mutation

_C = "tests/test_compare_commonness.py"
_S = "tests/test_sentence_abbreviations.py"
_F = "tests/test_family_search.py"
_TAG = ("batch_c",)

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1930", phase=1930,
             description="compare judges a word's commonness inside the one standard again",
             path=APP / "chat_comparison.py",
             anchor="        with lexical.commonness_against(allowed_document_ids):\n",
             replacement="        if True:\n",
             target=_C, keyword="compare_gives_the_covering_standard", tags=_TAG),
    Mutation(id="M1931", phase=1931,
             description="the lexical gate ignores the library-wide commonness scope",
             path=APP / "lexical.py",
             anchor="    common_ids = _COMMONNESS_IDS.get()\n",
             replacement="    common_ids = None\n",
             target=_C, keyword="not_refused_as_common or compare_gives_the_covering", tags=_TAG),
    Mutation(id="M1932", phase=1932,
             description="no full stop is treated as part of an abbreviation any more",
             path=APP / "sentence_guard.py",
             anchor="_ABBREVIATIONS = (\n",
             replacement='_ABBREVIATIONS = ("zz",)\n_UNUSED = (\n',
             target=_S, keyword="full_stop_does_not_cut", tags=_TAG),
    Mutation(id="M1933", phase=1933,
             description="answer.py cuts a quote at P-No. again",
             path=APP / "answer.py",
             anchor='_SENTENCE = re.compile(r"(?<=[.!?])" + NOT_AN_ABBREVIATION + r"\\s+")',
             replacement='_SENTENCE = re.compile(r"(?<=[.!?])\\s+")',
             target=_S, keyword="full_stop_does_not_cut and answer_sentence", tags=_TAG),
    Mutation(id="M1934", phase=1934,
             description="claims.py cuts a sentence at para. again",
             path=APP / "claims.py",
             anchor='    r"(?<=[.!?;])" + NOT_AN_ABBREVIATION + r"\\s+(?=[A-Z0-9\\"“(\\[])")',
             replacement='    r"(?<=[.!?;])\\s+(?=[A-Z0-9\\"“(\\[])")',
             target=_S, keyword="full_stop_does_not_cut and claims", tags=_TAG),
    Mutation(id="M1935", phase=1935,
             description="the streamed answer is released in halves at P-No. again",
             path=APP / "chat_stream.py",
             anchor='_BOUNDARY = re.compile(r"(?<=[.!?])" + NOT_AN_ABBREVIATION + r"\\s+|\\n")',
             replacement='_BOUNDARY = re.compile(r"(?<=[.!?])\\s+|\\n")',
             target=_S, keyword="full_stop_does_not_cut and stream", tags=_TAG),
    Mutation(id="M1936", phase=1936,
             description="a real sentence end no longer splits",
             path=APP / "sentence_guard.py",
             anchor='    + r"(?<!\\be\\.g\\.)(?<!\\bi\\.e\\.)"\n',
             replacement='    + r"(?<!\\.)"\n',
             target=_S, keyword="real_sentence_end_still_splits", tags=_TAG),
    Mutation(id="M1937", phase=1937,
             description="the family's eight are ranked by scope and name, not by the topic",
             path=APP / "family_search.py",
             anchor='        -kv[1]["topic"], -kv[1]["scope"],',
             replacement='        0, -kv[1]["scope"],',
             target=_F, keyword="chosen_by_evidence", tags=_TAG),
    Mutation(id="M1938", phase=1938,
             description="the family answer no longer says the eight were ranked by the topic",
             path=APP / "family_search.py",
             anchor='        how = (f"ranked by how much of each is about {topic}" if topic',
             replacement='        how = (f"best ranked" if topic',
             target=_F, keyword="no_more_than_eight", tags=_TAG),
)
