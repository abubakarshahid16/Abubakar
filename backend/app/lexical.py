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

import contextlib
import contextvars
import re

from . import acronyms
from . import glossary
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
    # Question filler: the verbs and prepositions a reader wraps round a topic
    # ("what does X say about Y", "is it mentioned", "according to"). A
    # standard does not write them about itself, so as terms they were always
    # absent and pushed a short question over LONG_QUESTION_TERM_COUNT.
    "say", "says", "said", "saying", "mention", "mentions", "mentioned",
    "state", "states", "stated", "according", "describe", "describes",
    "described", "define", "defines", "defined", "provide", "provides",
    "provided", "regarding", "concerning", "concerns",
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

#: A question naming this many distinctive terms or more must share at least
#: two of them (see SHARED_TERMS_REQUIRED_LONG) rather than one. Refusal
#: calibration on the real corpus (2026-09-29) found four absent-topic
#: questions answered confidently, each sharing exactly one distinctive term
#: with an unrelated passage - a single coincidental match was enough to pass
#: a longer, more specific question. A short question has less to share in
#: the first place, so the one-term rule (SHARED_TERMS_REQUIRED_SHORT) stays
#: for it.
LONG_QUESTION_TERM_COUNT = 3
SHARED_TERMS_REQUIRED_LONG = 2
SHARED_TERMS_REQUIRED_SHORT = 1

#: Shorter than this and a word is not a subject term.
MIN_TERM_LENGTH = 3

#: An identifier-shaped fragment of a designation must be at least this long
#: (normalised) to count as naming the document.
MIN_FRAGMENT_LENGTH = 8

_TERM = re.compile(r"[A-Za-z][A-Za-z0-9./-]*")

#: A plain decimal ("2.5", "0.75", "1.6"): a value the reader typed, not a
#: designation. `keyword.IDENTIFIER` matches it through its clause-number
#: shape, which made every decimal in a question a named subject that had to
#: appear in the corpus. Three-part clause numbers (5.3.2) are not decimals
#: and still count; so does anything with a letter (A106, API 5L).
_PLAIN_DECIMAL = re.compile(r"\d+\.\d+")


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
    expansions: list[str] | None = None,
) -> list[str]:
    """The terms that say what the question is ABOUT, in order, deduplicated.

    `expansions` is the corpus's multi-word expansions (`acronyms.known_expansions`).
    A caller that tokenises MANY sentences against one scope reads them ONCE and
    passes them in: looking them up per sentence cost one corpus-wide database
    query per sentence (#606, 44 claims = 44 queries, 4 to 5 s).

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
        if _PLAIN_DECIMAL.fullmatch(ident):
            continue
        add(ident)

    remaining = question
    if expansions is None:
        expansions = acronyms.known_expansions(
            document_id, allowed_document_ids=allowed_document_ids)
    for phrase in expansions:
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
    if _PLAIN_DECIMAL.fullmatch(term):
        return False
    if keyword.IDENTIFIER.fullmatch(term):
        return True
    # A user may paste a heading or a whole question in ALL CAPS. Long
    # alphabetic words in that style are ordinary prose, not named subjects;
    # treating `ORIGINAL` or `PARAGRAPH` as missing engineering identifiers
    # causes a valid document question to be refused before answer generation.
    # Short all-caps tokens remain eligible as abbreviations (for example
    # NDFT), while code-shaped standards/tags were handled above.
    if term.isalpha() and term.isupper() and len(term) > 5:
        return False
    if len(term) < 4 or not term[:1].isupper():
        return False
    return not question.strip().startswith(term)


#: A hyphenated qualifier: a capitalised first part and a lowercase word after
#: the hyphen - "ASME-certified", "UL-listed", "Code-stamped". The lowercase
#: tail is what makes it describe something rather than name it; a designation
#: ("STD-Q-999") has no lowercase tail and is never a qualifier.
_QUALIFIER = re.compile(r"[A-Z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*-[a-z]{3,}")


def is_absent_qualifier(term: str, question: str, present: list[str]) -> bool:
    """Is this missing term a word DESCRIBING the subject, not the subject?

    Only a hyphenated qualifier (see _QUALIFIER) that is not an identifier,
    and only when the very next word of the question is a term found in the
    documents - the thing it qualifies. "ASME-certified relief valves" sets
    the qualifier aside when "relief" is indexed; "ASME-certified" at the end
    of a question qualifies nothing and still refuses.
    """
    if keyword.IDENTIFIER.fullmatch(term) or not _QUALIFIER.fullmatch(term):
        return False
    after = re.search(re.escape(term) + r"\s+([A-Za-z][A-Za-z0-9./-]*)", question)
    if not after:
        return False
    following = after.group(1).rstrip(".").lower()
    return any(following == p.lower() or p.lower().startswith(following + " ")
               for p in present)


def searched_scope(
    document_id: str | None, allowed_document_ids: frozenset[str]
) -> str:
    """What a refusal says it looked in. One named, permitted document is
    reported as that document and its passage count - "not mentioned in
    STD-A-001.pdf (12 passages searched)" - never as "the indexed documents",
    which would claim a library-wide search that did not happen. Anything
    else keeps the library-wide wording."""
    if document_id and document_id in allowed_document_ids:
        from .db import connect

        row = connect().execute(
            "SELECT filename FROM documents WHERE id = ?", (document_id,)).fetchone()
        count = keyword.indexed_count(
            document_id, allowed_document_ids=allowed_document_ids)
        if row and count:
            noun = "passage" if count == 1 else "passages"
            return f"{row['filename']} ({count} {noun} searched)"
    return "the indexed documents"


_NON_ALNUM = re.compile(r"[^A-Za-z0-9]+")


def _norm_id(text: str) -> str:
    return _NON_ALNUM.sub("", text).upper()


def _names_an_indexed_document(
    term: str, document_id: str | None, *, allowed_document_ids: frozenset[str]
) -> bool:
    """True when `term` is the designation of a document already indexed
    AND permitted for this caller - by FILE NAME, the same
    `understanding.designation` the rest of the system already uses to
    recognise "our SAES-W-010" in a question, never by content search.

    Scoped to `document_id` when the question is already narrowed to one
    document, else to `allowed_document_ids` - never the whole corpus
    (CLAUDE.md rule 5: a filter only narrows what a caller may already read).
    """
    from . import understanding
    from .db import connect

    scope = frozenset({document_id}) if document_id else allowed_document_ids
    if not scope:
        return False
    wanted = _norm_id(term)
    if not wanted:
        return False
    marks = ",".join("?" * len(scope))
    rows = connect().execute(
        f"SELECT filename FROM documents WHERE id IN ({marks})", list(scope)).fetchall()
    for row in rows:
        designation = understanding.designation(row["filename"])
        if designation and _norm_id(designation) == wanted:
            return True
    return False


def _scope_wholly_named(term: str, scope: frozenset[str]) -> bool:
    """True when EVERY document in `scope` is designated `term` by file name.
    Never true for an empty scope or one that includes any other document."""
    from . import understanding
    from .db import connect

    wanted = _norm_id(term)
    if not scope or not wanted:
        return False
    marks = ",".join("?" * len(scope))
    rows = connect().execute(
        f"SELECT filename FROM documents WHERE id IN ({marks})", list(scope)).fetchall()
    if len(rows) != len(scope):
        return False
    # A long designation is found twice by `distinctive_terms`: whole (the word
    # scan) and as the tail the identifier pattern happens to match
    # ("NACE-MR0175-ISO15156-specification" and "MR0175-ISO15156-specification").
    # The tail is part of the document's own name, so an identifier-shaped
    # term that sits inside the designation counts as naming it.
    fragment_ok = bool(keyword.IDENTIFIER.fullmatch(term)) and len(wanted) >= MIN_FRAGMENT_LENGTH
    for row in rows:
        designation = understanding.designation(row["filename"])
        if not designation:
            return False
        have = _norm_id(designation)
        if have != wanted and not (fragment_ok and wanted in have):
            return False
    return True


#: The documents a word's COMMONNESS is judged against, when that differs from
#: the documents being searched. `chat_comparison` narrows each side to ONE
#: standard on purpose; judged inside that one standard, a word the standard
#: is about ("heat treatment" in a welding standard that covers it in 10 of
#: its chunks) looked "common to the whole document", stopped counting as a
#: distinctive term, and the side was refused as having no answer - the more a
#: standard covered the topic the likelier it was reported silent. Set it to
#: what the CALLER may read (never wider: rule 5) and commonness is judged
#: across that library instead. Unset, nothing changes.
_COMMONNESS_IDS: contextvars.ContextVar[frozenset[str] | None] = contextvars.ContextVar(
    "lexical_commonness_ids", default=None)


@contextlib.contextmanager
def commonness_against(document_ids: frozenset[str]):
    """Judge term commonness across `document_ids` (the caller's readable
    set) for every `assess` call inside the block."""
    token = _COMMONNESS_IDS.set(frozenset(document_ids))
    try:
        yield
    finally:
        _COMMONNESS_IDS.reset(token)


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
        "spelling_corrections": {},
    }
    if not terms:
        # nothing distinctive to check; the semantic score decides alone
        return empty

    indexed = keyword.indexed_count(
        document_id, allowed_document_ids=allowed_document_ids)
    if not indexed:
        return empty
    common_ids = _COMMONNESS_IDS.get()
    common_indexed = indexed
    if common_ids is not None:
        common_indexed = keyword.indexed_count(None, allowed_document_ids=common_ids)
    common_cutoff = max(1, int(common_indexed * COMMON_TERM_FRACTION))
    judge_commonness = common_indexed >= MIN_CORPUS_FOR_COMMONNESS

    body = passage_text.lower()
    expanded = glossary.expansions(question)
    covered: list[str] = []
    absent: list[str] = []
    corrections: dict[str, str] = {}
    present: list[str] = []
    distinguishing_count = 0

    # When the search is narrowed to documents that ALL carry one designation
    # (one file, or several files of the same standard such as a re-issue or a
    # duplicate upload), every passage in scope is "about" that designation by
    # construction. A standard almost never prints its own number on the page
    # that answers a topic, so asking "What does SAES-W-017 say about <topic>"
    # turned the designation into a third distinctive term, pushed the
    # question over LONG_QUESTION_TERM_COUNT, demanded two shared terms from a
    # passage that can only supply the topic, and refused the right page
    # (2026-10-02, owner's library). The designation is credited ONLY when
    # every document in scope is named by it (by file name); in any wider or
    # mixed scope a passage gets no credit.
    scope_ids = frozenset({document_id}) if document_id else allowed_document_ids

    for term in terms:
        if _scope_wholly_named(term, scope_ids):
            present.append(term)
            covered.append(term)
            distinguishing_count += 1
            continue
        # Every way this corpus writes the same thing. A document that spells
        # out "nominal dry film thickness" and never writes NDFT used to
        # refuse a question about the NDFT: the term genuinely was not there,
        # and the reader was still asking a fair question. Bidirectional, so
        # asking for the full term also matches chunks that only write the
        # acronym. See app/acronyms.py - the map is built FROM the documents.
        forms = [term, *acronyms.equivalents(
            term, document_id, allowed_document_ids=allowed_document_ids)]
        # ...and the phrasings a standard prints for a lay word (app/
        # glossary.py): "humid" is covered by a passage about "relative
        # humidity". The same argument as the acronyms, from a curated list
        # an engineer reviews rather than from the corpus. It can only make a
        # term COUNT as present; the reranker's floor still decides.
        forms.extend(expanded.get(term.lower(), ()))

        # ...and the spelling the corpus uses, when the reader's spelling is
        # not in it at all. Issue #85: "sumbittal requirements" refused with
        # "none of the terms in this question appear in the indexed
        # documents", because every distinctive term was a typo. The word is
        # genuinely absent and the question is still a fair one, which is the
        # same argument acronyms.py makes about an expansion the document
        # never abbreviates. The correction comes from the INDEX, never from a
        # dictionary, and identifiers are excluded from it - see
        # keyword._correctable, where API 610 and API 611 are one edit apart.
        corrected = keyword.fuzzy_corpus_match(
            term, document_id, allowed_document_ids=allowed_document_ids)
        if corrected:
            forms.append(corrected)
            corrections[term] = corrected

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
            # FOUND 2026-10-01: a standard's own pages almost never print its
            # own file name ("SAES-W-010 says..." is not how a standard
            # refers to itself), so a content search alone - the only thing
            # `occurrences` measures - reports the term absent even when the
            # document is indexed, permitted and exactly the one the reader
            # named. Checked by FILENAME, scoped to what this caller may
            # read, never corpus-wide (CLAUDE.md rule 5).
            if _names_an_indexed_document(
                    term, document_id, allowed_document_ids=allowed_document_ids):
                present.append(term)
                covered.append(term)
                distinguishing_count += 1
                continue
            absent.append(term)
            continue

        present.append(term)
        if any(form.lower() in body for form in forms):
            covered.append(term)
            common_occurrences = occurrences
            if common_ids is not None:
                common_occurrences = 0
                for form in forms:
                    count = keyword.term_occurrences(
                        form, None, allowed_document_ids=common_ids)
                    if count >= 0:
                        common_occurrences = max(common_occurrences, count)
            if not judge_commonness or common_occurrences <= common_cutoff:
                distinguishing_count += 1

    named_absent = [t for t in absent if looks_like_a_named_subject(t, question)]
    # A QUALIFIER IS NOT THE SUBJECT (#602). "ASME-certified liquid service
    # relief valves" names relief valves; the certification word describes
    # them. Refusing because that one word is not printed anywhere threw away
    # strong matches for everything else the reader asked. Such a word is set
    # aside - and named to the reader - only when the word it describes is in
    # the documents; the remaining terms must still pass the gate below.
    qualifiers = [t for t in named_absent
                  if is_absent_qualifier(t, question, present)]
    named_absent = [t for t in named_absent if t not in qualifiers]
    if named_absent:
        joined = ", ".join(named_absent)
        verb = "does" if len(named_absent) == 1 else "do"
        where = searched_scope(document_id, allowed_document_ids)
        reason = (f"{joined} {verb} not appear anywhere in the indexed documents"
                  if where == "the indexed documents"
                  else f"{joined} {verb} not appear in {where}")
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
            "spelling_corrections": corrections,
        }

    if not present:
        return {
            "ok": False,
            "reason": "none of the terms in this question appear in "
                      + searched_scope(document_id, allowed_document_ids),
            "terms": terms,
            "covered": covered,
            "absent_from_corpus": absent,
            "coverage": 0.0,
            "spelling_corrections": corrections,
        }

    coverage = len(covered) / len(present)
    # Coverage is reported, not gated on - see MIN_COVERAGE for the sweep that
    # showed the fraction cost two correct answers and bought nothing.
    required = (SHARED_TERMS_REQUIRED_LONG if len(terms) >= LONG_QUESTION_TERM_COUNT
               else SHARED_TERMS_REQUIRED_SHORT)
    ok = distinguishing_count >= required

    reason = None
    if not ok:
        if not covered:
            reason = "the closest passage shares no distinctive term with the question"
        elif distinguishing_count == 0:
            reason = (
                "the closest passage matches only terms common to the whole "
                "document, not the specific subject of the question"
            )
        else:
            reason = (
                f"the closest passage shares only {distinguishing_count} of the "
                f"{required} distinctive terms this question needs"
            )

    return {
        "ok": ok,
        "reason": reason,
        "terms": terms,
        "covered": covered,
        "absent_from_corpus": absent,
        "coverage": round(coverage, 3),
        "spelling_corrections": corrections,
        # Qualifier words not found anywhere in scope, set aside rather than
        # refused over (#602). The answer names them to the reader.
        "unmatched_qualifiers": qualifiers,
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
