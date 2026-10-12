"""Shared [S#] citation-marker syntax, used by both answer.py and synthesis.py.

Deliberately its own module with zero dependencies beyond `re`: synthesis.py
must stay free of the retrieval stack (httpx, search, db) to remain a pure
engine, and this module is the shared ground both it and answer.py can import
without either depending on the other.
"""

from __future__ import annotations

import re

_CITATION = re.compile(r"\[S(\d+)\]")
#: A citation marker the generator started and did not finish, because the
#: token budget ran out inside it: "[", "[S", "[S1" with no closing bracket,
#: at the very end of the text. Anchored to the end on purpose - a bare "["
#: mid-sentence is ordinary prose and must survive.
_HALF_CITATION = re.compile(r"\s*\[S?\d*$")


def strip_half_citation(text: str) -> str:
    """Remove a citation marker the output cap cut in half.

    Text that stops inside `[S2` reads as a malformed citation system rather
    than as a length limit. A broken citation is worse than a missing one -
    the same reasoning that makes an invented citation get stripped, and the
    same machinery.

    Only the trailing fragment goes. The sentence it was attached to is left
    alone: it is still the model's text and still supported by the citations
    that did survive.
    """
    return _HALF_CITATION.sub("", text).rstrip()


def validate_citations(text: str, count: int) -> tuple[list[int], list[int]]:
    """Split the citations into those that exist and those the model invented."""
    cited = [int(n) for n in _CITATION.findall(text)]
    valid = sorted({n for n in cited if 1 <= n <= count})
    invented = sorted({n for n in cited if not 1 <= n <= count})
    return valid, invented
