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

from . import acronyms
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

#: Coverage is REPORTED but no longer GATED on, because measurement said it
#: contributes nothing and costs real answers.
#:
#: Swept over the independently written 15-question set:
#:
#:   fraction   answerable answered   unanswerable refused   false refusals
#:   0.00               10/10                  5/5                0
#:   0.15               10/10                  5/5                0
#:   0.20               10/10                  5/5                0
#:   0.25                9/10                  5/5                1   (Q5)
#:   0.34                8/10                  5/5                2   (Q4, Q5)
#:
#: Nothing was gained anywhere on the way up and two correct answers were
#: lost. A FRACTION also penalises exactly the wrong questions: a precisely
#: worded one carries more distinctive terms, so needing a fixed proportion of
#: them gets harder the more specific the question is. "which standard gives
#: the holiday detection voltage" names five things and the right passage
#: mentions one of them - the standard.
#:
#: What actually separates answerable from unanswerable is the pair of rules
#: that remain: a named subject absent from the corpus, and requiring at least
#: one covered term that DISTINGUISHES something.
MIN_COVERAGE = 0.0

#: A term in more than this fraction of indexed chunks distinguishes nothing.
COMMON_TERM_FRACTION = 0.25

#: Below this many indexed chunks, "common in the corpus" is not a meaningful
#: idea and the requirement is skipped entirely.
#:
#: On a two-chunk corpus the cutoff computes to 1, so a term appearing twice -
#: which is every term in a two-chunk corpus - counts as common and nothing
#: can distinguish anything. That is arithmetically right and practically
#: useless: it refused "what is ndft" against a document whose abbreviations
#: clause defines NDFT. Same shape as the second-passage margin: a fraction of
#: the corpus does not transfer to a corpus too small to take fractions of.
MIN_CORPUS_FOR_COMMONNESS = 20

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


def distinctive_terms(
    question: str,
    document_id: str | None = None,
    *,
    allowed_document_ids: frozenset[str],
) -> list[str]:
    """The terms that say what the question is ABOUT, in order, deduplicated.

    Identifiers are included as written, because "B16.5" is the entire subject
    of the question that carries it.

    A multi-word expansion the corpus defines counts as ONE term and its
    constituent words are removed. Without that, "nominal dry film thickness"
    became four separate terms, the phrase was never looked up so its acronym
    was never found, and the four words then inflated the denominator badly
    enough to fail the coverage test on a passage that answered the question.
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

    remaining = question
    for phrase in acronyms.known_expansions(
            document_id, allowed_document_ids=allowed_document_ids):
        if phrase in remaining.lower():
            add(phrase)
            # case-insensitive removal, so the phrase's own words are not
            # counted a second time as individual terms
            pattern = re.compile(re.escape(phrase), re.IGNORECASE)
            remaining = pattern.sub(" ", remaining)

    for word in _TERM.findall(remaining):
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


def assess(
    question: str,
    passage_text: str,
    document_id: str | None = None,
    *,
    allowed_document_ids: frozenset[str],
) -> dict:
    """Whether this passage is lexically plausible as an answer.

    Returns the evidence as well as the verdict, so a refusal can name the
    term that was missing rather than only saying it was not confident.

    `allowed_document_ids` is REQUIRED and keyword-only. This function's
    absolute presence gate produces the user-visible refusal "none of the
    terms in this question appear in the indexed documents", and it used to
    compute that over the WHOLE corpus: a term present only in a document the
    caller has no grant on made the answer "it exists, just not for you"
    without saying so, and a term absent everywhere made a claim about
    documents they cannot see. Both are a presence oracle. The scope is the
    caller's, and it reaches every count below.
    """
    terms = distinctive_terms(
        question, document_id, allowed_document_ids=allowed_document_ids)
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

    indexed = keyword.indexed_count(
        document_id, allowed_document_ids=allowed_document_ids)
    if not indexed:
        return empty
    common_cutoff = max(1, int(indexed * COMMON_TERM_FRACTION))
    judge_commonness = indexed >= MIN_CORPUS_FOR_COMMONNESS

    body = passage_text.lower()
    covered: list[str] = []
    absent: list[str] = []
    present: list[str] = []
    covered_distinguishing = False

    for term in terms:
        # Every way this corpus writes the same thing. A document that spells
        # out "nominal dry film thickness" and never writes NDFT used to
        # refuse a question about the NDFT: the term genuinely was not there,
        # and the reader was still asking a fair question. Bidirectional, so
        # asking for the full term also matches chunks that only write the
        # acronym. See app/acronyms.py - the map is built FROM the documents.
        forms = [term, *acronyms.equivalents(
            term, document_id, allowed_document_ids=allowed_document_ids)]

        occurrences = 0
        unparseable = True
        for form in forms:
            count = keyword.term_occurrences(
                form, document_id, allowed_document_ids=allowed_document_ids)
            if count >= 0:
                unparseable = False
                occurrences = max(occurrences, count)
        if unparseable:
            # FTS could not parse any form; it tells us nothing either way
            continue
        if occurrences == 0:
            absent.append(term)
            continue

        present.append(term)
        if any(form.lower() in body for form in forms):
            covered.append(term)
            if not judge_commonness or occurrences <= common_cutoff:
                covered_distinguishing = True

    named_absent = [t for t in absent if looks_like_a_named_subject(t, question)]
    if named_absent:
        joined = ", ".join(named_absent)
        verb = "does" if len(named_absent) == 1 else "do"
        reason = f"{joined} {verb} not appear anywhere in the indexed documents"
        # A dead end is not a useful refusal. If the missing term is written
        # like an abbreviation, the corpus may spell it out under a name the
        # reader has not tried - and the expansion map only knows the forms
        # the documents actually define.
        if any(acronyms.looks_like_acronym(t) for t in named_absent):
            reason += ". If it is an abbreviation, try the full term"
        return {
            "ok": False,
            "reason": reason,
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
    # Coverage is reported, not gated on - see MIN_COVERAGE for the sweep that
    # showed the fraction cost two correct answers and bought nothing.
    ok = covered_distinguishing

    reason = None
    if not ok:
        if not covered:
            reason = "the closest passage shares no distinctive term with the question"
        else:
            reason = (
                "the closest passage matches only terms common to the whole "
                "document, not the specific subject of the question"
            )

    return {
        "ok": ok,
        "reason": reason,
        "terms": terms,
        "covered": covered,
        "absent_from_corpus": absent,
        "coverage": round(coverage, 3),
    }


def uncovered_terms(
    question: str, passage_text: str, *, allowed_document_ids: frozenset[str]
) -> list[str]:
    """Distinctive terms the question asks about that this passage does not
    mention. Used to decide whether a SECOND passage is needed: a question
    asking for a check frequency and a humidity limit is answered by one
    passage only if that passage covers both."""
    body = passage_text.lower()
    return [t for t in distinctive_terms(
        question, allowed_document_ids=allowed_document_ids)
        if t.lower() not in body]


def distinguishing_uncovered_terms(
    question: str,
    passage_text: str,
    document_id: str | None = None,
    *,
    allowed_document_ids: frozenset[str],
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
    indexed = keyword.indexed_count(
        document_id, allowed_document_ids=allowed_document_ids)
    if not indexed:
        return []
    cutoff = (
        max(1, int(indexed * COMMON_TERM_FRACTION))
        if indexed >= MIN_CORPUS_FOR_COMMONNESS
        else indexed          # too small to judge commonness; nothing is common
    )
    body = passage_text.lower()
    out: list[str] = []
    for term in distinctive_terms(
            question, document_id, allowed_document_ids=allowed_document_ids):
        if term.lower() in body:
            continue
        occurrences = keyword.term_occurrences(
            term, document_id, allowed_document_ids=allowed_document_ids)
        if 0 < occurrences <= cutoff:
            out.append(term)
    return out
