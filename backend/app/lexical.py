"""The lexical gate: is this passage plausibly about what was asked?

One threshold was doing two jobs and getting both wrong. The right chunk was
retrieved for a question about NACE RP0188 and refused. Nothing relevant was
retrieved for a question about Inconel, and a passive-fire-protection passage
was returned labelled QUOTED VERBATIM. Raising the threshold fixes the second
and worsens the first; lowering it does the reverse. It is one knob for two
independent failures.

Lexical presence separates them, and it is both cheaper and more reliable than
tuning. "Inconel" appears zero times in the corpus - that alone is enough to
refuse, with no semantic judgement required at all. The semantic score then
decides only among candidates that are lexically plausible, which is the job a
cross-encoder is actually good at.

Two rules, in order of decisiveness:

  1. A NAMED SUBJECT ABSENT FROM THE CORPUS. A material, standard or tag that
     appears in no indexed chunk makes the question unanswerable outright.
  2. COVERAGE. The passage must share enough of the question's distinctive
     terms, and at least one of them must actually distinguish something -
     "coating" in a coating specification is not evidence.
"""

from __future__ import annotations

import re

from . import keyword

#: Words that carry no subject. A question is not ABOUT "what" or "required".
STOPWORDS = {
    "what", "which", "who", "whom", "whose", "when", "where", "why", "how",
    "is", "are", "was", "were", "be", "been", "being", "am",
    "do", "does", "did", "doing", "done",
    "the", "and", "or", "but", "if", "then", "than", "that", "this",
    "these", "those", "there", "here", "its", "they", "them", "their",
    "of", "in", "on", "at", "to", "for", "from", "by", "with", "without",
    "into", "onto", "over", "under", "about", "as", "per", "via",
    "can", "could", "shall", "should", "will", "would", "may", "might", "must",
    "have", "has", "had", "any", "all", "both", "each", "some", "not",
    "you", "your", "our", "tell", "give", "show", "please",
    "used", "use", "using", "need", "needs", "needed", "get", "gets",
    "specified", "specify", "require", "required", "requirement", "requirements",
    # designator connectives: "system no. 1" carries its meaning in the number
    "no", "nos", "number", "numbered",
}

#: A passage must cover at least this fraction of the question's distinctive
#: terms that exist in the corpus at all. Calibrated, not guessed.
MIN_COVERAGE = 0.34

#: A term in more than this fraction of indexed chunks distinguishes nothing.
COMMON_TERM_FRACTION = 0.25

#: Shorter than this and a word is not a subject term.
MIN_TERM_LENGTH = 3

_TERM = re.compile(r"[A-Za-z][A-Za-z0-9./-]*")


#: A question asking for TWO things. Only a compound question can justify a
#: second passage - and this, not a score, is what separates the cases.
#:
#: "what is the check frequency AND the relative humidity limit" is answered by
#: clause 11 plus clause 4.4, and neither alone. "what is the NDFT for coating
#: system no. 1" asks one thing, and a second passage there was pure noise: it
#: picked up a water-absorption table from clause 10.1 that merely mentioned
#: NDFT, because A.1's own table is labelled MDFT.
#:
#: A score threshold cannot separate these. The spurious second passage scored
#: 3.90 and the legitimate one -1.50 - the wrong way round. The difference is
#: in the question, not in the candidates.
_COMPOUND = re.compile(
    r"\b(?:and|as well as|along with|together with|plus)\b", re.IGNORECASE
)


def is_compound_question(question: str) -> bool:
    """Does this question ask for more than one thing?"""
    return bool(_COMPOUND.search(question))


def distinctive_terms(question: str) -> list[str]:
    """The terms that say what the question is ABOUT, in order, deduplicated.

    Identifiers are included as written, because "B16.5" is the entire subject
    of the question that carries it.
    """
    terms: list[str] = []
    seen: set[str] = set()

    def add(term: str) -> None:
        key = term.lower()
        if key and key not in seen:
            seen.add(key)
            terms.append(term)

    for ident in keyword.IDENTIFIER.findall(question):
        add(ident)
    for word in _TERM.findall(question):
        word = word.rstrip(".")
        if len(word) < MIN_TERM_LENGTH or word.lower() in STOPWORDS:
            continue
        add(word)
    return terms


def looks_like_a_named_subject(term: str, question: str) -> bool:
    """Is this term the thing the question names?

    An identifier, or a capitalised word that is not merely the first word of
    the sentence. Those are materials, standards and equipment tags - the
    terms whose absence from the corpus makes a question unanswerable rather
    than merely poorly matched. A lowercase ordinary word is not held to this
    standard, because a reader's wording need not match the document's.
    """
    if keyword.IDENTIFIER.fullmatch(term):
        return True
    if len(term) < 4 or not term[:1].isupper():
        return False
    return not question.strip().startswith(term)


def assess(question: str, passage_text: str, document_id: str | None = None) -> dict:
    """Whether this passage is lexically plausible as an answer.

    Returns the evidence as well as the verdict, so a refusal can name the
    term that was missing rather than only saying it was not confident.
    """
    terms = distinctive_terms(question)
    empty = {
        "ok": True,
        "reason": None,
        "terms": terms,
        "covered": [],
        "absent_from_corpus": [],
        "coverage": None,
    }
    if not terms:
        # nothing distinctive to check; the semantic score decides alone
        return empty

    indexed = keyword.indexed_count(document_id)
    if not indexed:
        return empty
    common_cutoff = max(1, int(indexed * COMMON_TERM_FRACTION))

    body = passage_text.lower()
    covered: list[str] = []
    absent: list[str] = []
    present: list[str] = []
    covered_distinguishing = False

    for term in terms:
        occurrences = keyword.term_occurrences(term, document_id)
        if occurrences == 0:
            absent.append(term)
            continue
        if occurrences < 0:
            # FTS could not parse the term; it tells us nothing either way
            continue
        present.append(term)
        if term.lower() in body:
            covered.append(term)
            if occurrences <= common_cutoff:
                covered_distinguishing = True

    named_absent = [t for t in absent if looks_like_a_named_subject(t, question)]
    if named_absent:
        joined = ", ".join(named_absent)
        return {
            "ok": False,
            "reason": (
                f"{joined} does not appear anywhere in the indexed documents"
                if len(named_absent) == 1
                else f"{joined} do not appear anywhere in the indexed documents"
            ),
            "terms": terms,
            "covered": covered,
            "absent_from_corpus": absent,
            "coverage": 0.0,
        }

    if not present:
        return {
            "ok": False,
            "reason": "none of the terms in this question appear in the indexed documents",
            "terms": terms,
            "covered": covered,
            "absent_from_corpus": absent,
            "coverage": 0.0,
        }

    coverage = len(covered) / len(present)
    ok = coverage >= MIN_COVERAGE and covered_distinguishing

    reason = None
    if not ok:
        if not covered:
            reason = "the closest passage shares no distinctive term with the question"
        elif not covered_distinguishing:
            reason = (
                "the closest passage matches only terms common to the whole "
                "document, not the specific subject of the question"
            )
        else:
            reason = (
                f"the closest passage covers only {len(covered)} of {len(present)} "
                f"distinctive terms in the question"
            )

    return {
        "ok": ok,
        "reason": reason,
        "terms": terms,
        "covered": covered,
        "absent_from_corpus": absent,
        "coverage": round(coverage, 3),
    }


def uncovered_terms(question: str, passage_text: str) -> list[str]:
    """Distinctive terms the question asks about that this passage does not
    mention. Used to decide whether a SECOND passage is needed: a question
    asking for a check frequency and a humidity limit is answered by one
    passage only if that passage covers both."""
    body = passage_text.lower()
    return [t for t in distinctive_terms(question) if t.lower() not in body]


def distinguishing_uncovered_terms(
    question: str, passage_text: str, document_id: str | None = None
) -> list[str]:
    """Uncovered terms that would actually change the answer if covered.

    A second passage is only worth adding when the first one misses something
    SPECIFIC. Judged by corpus frequency: a term the whole document uses is
    not a gap, it is background. Without this, an NDFT question picked up a
    water-absorption passage from another clause because that passage happened
    to contain a common word the first one lacked.
    """
    if not is_compound_question(question):
        # a single-subject question is answered by one passage or not at all
        return []
    indexed = keyword.indexed_count(document_id)
    if not indexed:
        return []
    cutoff = max(1, int(indexed * COMMON_TERM_FRACTION))
    body = passage_text.lower()
    out: list[str] = []
    for term in distinctive_terms(question):
        if term.lower() in body:
            continue
        occurrences = keyword.term_occurrences(term, document_id)
        if 0 < occurrences <= cutoff:
            out.append(term)
    return out
