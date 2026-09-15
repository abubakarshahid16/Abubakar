"""Nothing from the corpus may appear in an outbound payload. Ever.

THIS IS THE DELIVERABLE THAT MATTERS. The product's central promise is *"only
the phrase you type leaves this machine, you approve it first, and nothing
from your documents is ever part of it."* Everything else in the market
feature is a convenience; this file is the promise, expressed as something
that runs.

It was written BEFORE the providers, and it defined their interface rather
than being fitted to one that already existed. That ordering is deliberate: a
leak test written afterwards tends to assert what the code happens to do.

FOUR INDEPENDENT CONTROLS ARE ASSERTED, because a single one would be a
single point of failure:

  1. CONTENT - no four consecutive words from any document appear in any
     payload, compared after normalising case, punctuation and whitespace so a
     comma cannot hide a match.
  2. SHAPE - the payload's field set is CLOSED. A values-only test would pass
     a payload that grew a new field carrying passage text, which is exactly
     how this kind of leak actually happens: someone adds `context` "just for
     relevance".
  3. REFUSAL - handing passages to the builder raises. It is not sanitised.
     Silently stripping is worse than refusing, because the caller believes it
     succeeded and ships a feature that quietly does less than it says.
  4. STRUCTURE - the market modules import none of db, search, keyword,
     chunker, passages, claims or analysis. Enforced by parsing the source,
     not by asking anyone to be careful. This is the structural form of the
     promise: a module that cannot reach the corpus cannot leak it, whatever
     a future edit does to its logic.

WHAT THIS FILE HONESTLY CANNOT DO is at the bottom, in
`test_a_sentence_the_user_copied_out_of_a_document_is_not_blocked`. Read it.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from app import market, market_phrase, market_providers

APP = Path(market.__file__).resolve().parent

#: The modules that can reach the corpus. A market module importing any of
#: these has, by construction, acquired the ability to leak document content -
#: whether or not the code that does so has been written yet.
FORBIDDEN_IMPORTS = frozenset({
    "db", "search", "keyword", "chunker", "passages", "claims", "analysis",
})

#: The files this promise covers. NONE of these may import an HTTP client and
#: none may reach the corpus.
MARKET_MODULES = ("market.py", "market_phrase.py", "market_providers.py")

#: THE TRANSPORT IS THE EXCEPTION, AND ONLY TO ONE HALF OF THE RULE.
#:
#: `market_transport.py` exists to open sockets, so forbidding it an HTTP
#: client would be forbidding it its purpose. It is held to the OTHER half
#: instead, and more strictly: it must not be able to reach the corpus at all.
#:
#: That is the whole shape of the control. The two halves of a leak - being
#: able to READ document content, and being able to SEND anything - live in
#: different files, and no file can do both. A module that cannot make a
#: request cannot leak a document however wrong its logic goes; a module that
#: cannot read a document has nothing to leak however wrong its network code
#: goes. Checked by parsing the source, so the day someone adds a convenience
#: import to either side it fails by name.
TRANSPORT_MODULE = "market_transport.py"


# --------------------------------------------------------------- the corpus

#: REALISTIC DOCUMENT TEXT, FABRICATED HERE. It deliberately does NOT read the
#: client's database: that file is not in git, so a test depending on it fails
#: on a clean clone and passes only on one developer's machine. This codebase
#: has already shipped one test that used the developer's real 71 MB database
#: and therefore proved nothing anywhere else.
#:
#: The wording imitates the real corpus closely enough to be a fair test:
#: clause numbering, standard designators, the units and the register of a
#: specification.
CORPUS: dict[str, str] = {
    "doc13.pdf": (
        "7.2 Design Analysis. Provide an exterior finish and colour board for "
        "the principal exterior material selections. The Contractor shall "
        "submit a Preliminary (35%) design submittal for review by the "
        "Company prior to proceeding to detailed design. Deliverables shall "
        "include calculations, drawings and a basis of design narrative."
    ),
    "doc16.pdf": (
        "4.4 Submittal Stages. A draft submission (usually at least a 50% "
        "design submission) shall be provided for interdisciplinary review. "
        "Structural models shall be delivered in native format together with "
        "an IFC export. Attachment F lists the required drawing sizes."
    ),
    "NORSOK-M-501.pdf": (
        "11.3 Holiday detection. Holiday detection shall be carried out in "
        "accordance with NACE RP0188 at a voltage appropriate to the total "
        "nominal dry film thickness. The nominal dry film thickness of "
        "coating system no. 1 shall be 280 micrometres."
    ),
    "book2-Differential-Equations.pdf": (
        "Chapter 4. Separation of variables applies when the equation can be "
        "written as a product of a function of x and a function of t. The "
        "resulting ordinary differential equations are solved independently "
        "and recombined subject to the boundary conditions."
    ),
}

CORPUS_FILENAMES = tuple(CORPUS)

#: Questions a real user would type. Some carry filenames, some carry
#: quotations lifted straight out of the documents above, some are innocuous.
QUESTIONS = (
    "compare design requirements in doc13.pdf and doc16.pdf",
    "what does doc13 require for the preliminary design submittal",
    "do your deep analysis find all structural models from all documents",
    "what is ISO 12944 and how does it relate to NORSOK M-501",
    "in section 7.2 what is the nominal dry film thickness",
    'the spec says "a draft submission (usually at least a 50% design '
    'submission)" is that an industry norm',
    "explain NIST SP 800-207 zero trust architecture",
    "holiday detection voltage for coating system no. 1",
    "p.125 and pp. 12-14 and page 7",
    "doc13.pdf",
    "book2-Differential-Equations",
)


# ---------------------------------------------------------------- normalising

_PUNCT = re.compile(r"[^\w\s]+", re.UNICODE)
_SPACE = re.compile(r"\s+")


def normalise(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace.

    Done to BOTH sides before comparing, so `"design submission)"` and
    `design submission` are the same four words. Comparing raw strings is how
    a leak test passes while the leak is present: one comma between the words
    and the substring search misses it.
    """
    return _SPACE.sub(" ", _PUNCT.sub(" ", (text or "").lower())).strip()


def ngrams(text: str, n: int = 4) -> set[str]:
    words = normalise(text).split()
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


CORPUS_4GRAMS: set[str] = set()
for _name, _body in CORPUS.items():
    CORPUS_4GRAMS |= ngrams(_body, 4)


def test_the_fixture_itself_produces_enough_ngrams_to_be_a_real_test():
    """A guard on the guard.

    If `CORPUS` were ever trimmed to a few words, `CORPUS_4GRAMS` would shrink
    towards empty and every leak assertion below would pass by having nothing
    to look for. That is the vacuous-test failure this repository has shipped
    before, so the fixture asserts its own weight.
    """
    assert len(CORPUS_4GRAMS) > 100, (
        f"only {len(CORPUS_4GRAMS)} four-grams in the corpus fixture - the "
        f"leak assertions would be close to vacuous"
    )


# ------------------------------------------------------- 1. CONTENT does not leak


def _all_payloads_for(question: str) -> list[dict]:
    """Every outbound object this question could produce, across every tier."""
    phrase = market_phrase.market_phrase(question, CORPUS_FILENAMES)
    if phrase is None:
        return []
    return [
        market_providers.build_payload(phrase, tier=tier)
        for tier in market_providers.TIERS
    ]


#: Documents whose names disclose nothing but the fact that they exist. These
#: must NEVER leak in any form - full name or stem - under any input.
OPAQUE_FILES = ("doc13.pdf", "doc16.pdf", "book2-Differential-Equations.pdf")

#: One file is NAMED AFTER A PUBLIC STANDARD, and that collision is real
#: rather than contrived - it is how the client's corpus is actually named.
#: `NORSOK-M-501.pdf` shares its stem with a designator that tier 3 exists to
#: look up, so "norsok m-501" surviving is the whitelist working, not failing.
#: Asserted separately and deliberately below.
STANDARD_NAMED_FILE = "NORSOK-M-501.pdf"


def _added_beyond_the_question(question: str, payload: dict) -> set[str]:
    """Document four-grams in the payload that the QUESTION did not contain.

    THIS IS THE INVARIANT THAT IS ACTUALLY TRUE, and getting here took one
    failed assertion. The first version of this test asserted that no document
    four-gram reaches a payload at all, and it FAILED on
    "in section 7.2 what is the nominal dry film thickness" - because
    "nominal dry film thickness" is both a phrase in NORSOK-M-501.pdf and
    exactly what a corrosion engineer types from memory.

    That failure was the test being wrong, not the code. The promise is
    "nothing from your documents is ever part of it" - meaning the SYSTEM
    never contributes document content. It cannot mean the user is prevented
    from typing words that happen to appear in their own specification; no
    filter can separate that from legitimate technical vocabulary, and one
    claiming to would block real searches while passing anything reworded.

    So the assertion is: the payload adds NO document text of its own. Every
    document four-gram in it was already in what the user typed and approved.
    """
    question_grams = ngrams(question, 4)
    blob = normalise(repr(payload))
    return {
        gram for gram in CORPUS_4GRAMS
        if gram in blob and gram not in question_grams
    }


@pytest.mark.parametrize("question", QUESTIONS)
def test_the_payload_adds_no_document_text_of_its_own(question):
    """The core assertion. Four words is short enough to catch a leaked clause
    fragment and long enough not to fire on ordinary shared vocabulary - two
    documents and a search phrase can all legitimately contain "design" or
    "shall be provided"."""
    for payload in _all_payloads_for(question):
        added = _added_beyond_the_question(question, payload)
        assert not added, (
            f"the payload contains document text the user never typed.\n"
            f"  question: {question!r}\n"
            f"  added   : {sorted(added)}\n"
            f"  payload : {payload!r}"
        )


#: Questions containing no document phrasing at all. For these the STRICT rule
#: applies with no allowance whatsoever: not one four-gram from any document
#: may appear, because there is no innocent explanation available.
CLEAN_QUESTIONS = (
    "compare design requirements in doc13.pdf and doc16.pdf",
    "do your deep analysis find all structural models from all documents",
    "what is ISO 12944",
    "explain NIST SP 800-207 zero trust architecture",
    "p.125 and pp. 12-14 and page 7",
    "doc13.pdf",
)


@pytest.mark.parametrize("question", CLEAN_QUESTIONS)
def test_a_question_carrying_no_document_phrasing_leaks_nothing_at_all(question):
    """The strict form, with the copy-paste allowance removed.

    If the mechanism ever starts enriching a phrase from the corpus - a
    "related terms" feature, a synonym expansion read off the index - these
    questions are where it shows, because none of them hands the system a
    document phrase it could hide behind.
    """
    for payload in _all_payloads_for(question):
        blob = normalise(repr(payload))
        for gram in CORPUS_4GRAMS:
            assert gram not in blob, (
                f"document text reached a payload from a question that "
                f"contained none.\n  question: {question!r}\n"
                f"  leaked  : {gram!r}\n  payload : {payload!r}"
            )


@pytest.mark.parametrize("question", QUESTIONS)
def test_no_opaque_corpus_filename_or_stem_ever_reaches_a_payload(question):
    """A filename is corpus metadata: it tells an outside service which
    documents this organisation holds. The stem matters as much as the full
    name - `doc13` without an extension is the same disclosure - and this
    holds even when the user typed it, because a filename is never a search
    term anyone wants.
    """
    for payload in _all_payloads_for(question):
        blob = normalise(repr(payload))
        words = blob.split()
        for name in OPAQUE_FILES:
            assert normalise(name) not in blob, f"{name!r} leaked: {payload!r}"
            stem = normalise(re.sub(r"\.[A-Za-z0-9]+$", "", name))
            for part in stem.split():
                assert part not in words, (
                    f"filename stem {part!r} from {name!r} leaked: {payload!r}"
                )


def test_the_standard_named_file_leaks_only_the_public_designator():
    """THE COLLISION, ASSERTED RATHER THAN AVOIDED.

    `NORSOK-M-501.pdf` is named after a published standard. Its stem cannot be
    banned outright: "what is NORSOK M-501" is the exact question tier 3 exists
    to answer, and the designator is public - the standard exists whether or
    not this client holds a copy.

    What must NOT happen is the FILENAME leaking as a filename. So this asserts
    the boundary precisely: the designator survives, and the `.pdf`, the
    filename's punctuation form, and any other corpus filename do not.
    """
    payloads = _all_payloads_for(
        "what is ISO 12944 and how does it relate to NORSOK M-501")
    assert payloads
    for payload in payloads:
        blob = normalise(repr(payload))
        assert "pdf" not in blob.split(), f"an extension leaked: {payload!r}"
        assert normalise(STANDARD_NAMED_FILE) not in blob, (
            f"the filename itself leaked: {payload!r}")
        for other in OPAQUE_FILES:
            assert normalise(other) not in blob
        # And the designator did survive, which is the point of tier 3.
        assert "norsok" in blob


def test_words_inside_a_quotation_never_reach_a_payload():
    """A GAP FOUND BY MUTATION, not by reading the code.

    Deleting the quoted-span removal passed every other assertion in this
    file. The reason is instructive: the surviving words of an unstripped
    quotation do not form a CONTIGUOUS four-gram matching the document,
    because the whitelist drops "shall", "be" and "in" from between them. The
    n-gram assertion is a good net for a copied passage and a poor one for a
    passage the whitelist has already thinned.

    So this asserts the property directly - no word from inside the quotation
    reaches the payload - which is what the quote removal is actually for. A
    user putting quotation marks around text is telling us it came from their
    document.
    """
    quoted = "structural models shall be delivered in native format"
    question = f'is "{quoted}" standard practice in the industry'

    payloads = _all_payloads_for(question)
    assert payloads, "the question should still yield a searchable phrase"
    for payload in payloads:
        words = set(normalise(repr(payload)).split())
        for word in normalise(quoted).split():
            if len(word) < 4:
                continue          # the whitelist drops these regardless
            assert word not in words, (
                f"{word!r} came from inside a quotation and reached the "
                f"payload: {payload!r}"
            )
        # ...and the unquoted part of the question still survives, or the
        # test would pass by the phrase being empty.
        assert "standard" in words or "industry" in words, payload


def test_the_character_limit_refuses_on_its_own():
    """ALSO A GAP FOUND BY MUTATION. Disabling the character check left the
    over-long-passage test green, because the WORD-count check caught the
    same input. Two overlapping guards are good defence and bad evidence: one
    of them was untested.

    This input is nine words and 260 characters, so only the character limit
    can refuse it.
    """
    long_few_words = " ".join(["coatingspecificationdocument"] * 9)
    assert len(long_few_words.split()) <= market_providers.MAX_PHRASE_WORDS
    assert len(long_few_words) > market_providers.MAX_PHRASE_CHARS

    with pytest.raises(market_providers.PassageRefused, match="characters"):
        market_providers.build_payload(
            long_few_words, tier=market_providers.TIER_REFERENCE)


def test_the_word_limit_refuses_on_its_own():
    """The mirror of the above: twenty short words, well under the character
    limit, so only the word count can refuse it."""
    many_short_words = " ".join(["coating"] * 20)
    assert len(many_short_words) <= market_providers.MAX_PHRASE_CHARS
    assert len(many_short_words.split()) > market_providers.MAX_PHRASE_WORDS

    with pytest.raises(market_providers.PassageRefused, match="words"):
        market_providers.build_payload(
            many_short_words, tier=market_providers.TIER_REFERENCE)


def test_the_phrase_is_the_only_free_text_in_the_payload():
    """Whatever text is in the payload must be the approved phrase and nothing
    else. This is what makes the human preview meaningful: if a payload could
    contain text the preview did not show, approving it would be approving
    something unseen."""
    phrase = market_phrase.market_phrase(
        "what is ISO 12944 for coatings", CORPUS_FILENAMES)
    assert phrase is not None
    for tier in market_providers.TIERS:
        payload = market_providers.build_payload(phrase, tier=tier)
        for key, value in payload.items():
            if isinstance(value, str) and key not in ("tier", "provider_label"):
                assert value in (phrase, "", None) or not _looks_like_prose(value), (
                    f"payload field {key!r} carries free text that is not the "
                    f"approved phrase: {value!r}"
                )


def _looks_like_prose(value: str) -> bool:
    return len(normalise(value).split()) >= 4


# ---------------------------------------------------------- 2. SHAPE is closed


@pytest.mark.parametrize("tier", market_providers.TIERS)
def test_the_payload_field_set_is_closed(tier):
    """A VALUES-ONLY TEST WOULD MISS THE REAL LEAK. The way this goes wrong in
    practice is not a bad value in a known field - it is a NEW field, added by
    someone improving relevance, carrying `context` or `evidence` or
    `surrounding_text`. Every assertion above would still pass. So the field
    set is pinned, and adding one is a test failure that has to be argued
    for."""
    payload = market_providers.build_payload("iso 12944 coatings", tier=tier)
    assert set(payload) == set(market_providers.ALLOWED_PAYLOAD_FIELDS), (
        f"payload shape changed for tier {tier!r}.\n"
        f"  unexpected: {sorted(set(payload) - set(market_providers.ALLOWED_PAYLOAD_FIELDS))}\n"
        f"  missing   : {sorted(set(market_providers.ALLOWED_PAYLOAD_FIELDS) - set(payload))}\n"
        f"If a field was added deliberately, it has to be justified here: "
        f"anything in this dict leaves the machine."
    )


def test_the_allowed_field_set_contains_nothing_that_could_hold_a_passage():
    """The field NAMES are themselves reviewed. A field called `context` or
    `evidence` is a passage carrier whatever it happens to hold today."""
    forbidden = {
        "context", "evidence", "passage", "passages", "text", "document",
        "documents", "chunk", "chunks", "excerpt", "snippet", "content",
        "body", "source_text", "surrounding_text", "quote",
    }
    overlap = forbidden & set(market_providers.ALLOWED_PAYLOAD_FIELDS)
    assert not overlap, (
        f"the outbound payload allows field(s) that read as passage carriers: "
        f"{sorted(overlap)}"
    )


# ------------------------------------------------------- 3. passages are REFUSED


@pytest.mark.parametrize("field", [
    "passages", "passage", "evidence", "context", "document_text", "chunks",
    "excerpt", "snippet", "corpus", "sources",
])
def test_passing_passages_to_the_builder_is_refused_not_sanitised(field):
    """REFUSED, LOUDLY. Silently dropping the argument is worse than raising:
    the caller believes the passages were used, ships the feature, and the
    quiet difference between what the code does and what its author thinks it
    does is where the next leak lives."""
    with pytest.raises(market_providers.PassageRefused, match=field):
        market_providers.build_payload(
            "iso 12944", tier=market_providers.TIER_REFERENCE,
            **{field: CORPUS["doc13.pdf"]},
        )


def test_a_phrase_long_enough_to_be_a_passage_is_refused_not_truncated():
    """Truncating a passage down to the length limit would send the first 200
    characters of a client's clause. The length limit is a REFUSAL, not a
    sanitiser."""
    with pytest.raises(market_providers.PassageRefused):
        market_providers.build_payload(
            CORPUS["doc13.pdf"], tier=market_providers.TIER_REFERENCE)


def test_a_multi_sentence_phrase_is_refused():
    """A search phrase is not prose. Several sentences arriving here means
    something upstream passed document text where a phrase was expected."""
    with pytest.raises(market_providers.PassageRefused):
        market_providers.build_payload(
            "Holiday detection shall be carried out. The thickness shall be "
            "280 micrometres. Deliverables shall include calculations.",
            tier=market_providers.TIER_REFERENCE,
        )


def test_none_is_refused_because_none_means_do_not_search():
    """`market_phrase` returns None to mean DO NOT SEARCH. If that ever
    reaches the builder it is a caller bug, and it must not be coerced into
    the string "None" and sent."""
    with pytest.raises(market_providers.PassageRefused):
        market_providers.build_payload(
            None, tier=market_providers.TIER_REFERENCE)  # type: ignore[arg-type]


# --------------------------------------------- 4. STRUCTURE: the imports cannot


def _imported_modules(path: Path) -> set[str]:
    """Every module name this file imports, from the AST.

    Parsed rather than grepped so a commented-out import does not count and a
    real one cannot hide behind formatting. Relative imports are resolved to
    their leaf name, because `from . import db` and `import db` are the same
    capability.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                found.update(node.module.split("."))
            for alias in node.names:
                found.add(alias.name.split(".")[0])
    return found


@pytest.mark.parametrize("module", MARKET_MODULES)
def test_market_modules_cannot_reach_the_corpus(module):
    """THE STRUCTURAL FORM OF THE PROMISE, and the one that survives a
    refactor. Every assertion above tests what the code currently does with
    the data it has. This one tests that it cannot obtain the data at all.

    Enforced by AST inspection rather than by a comment asking people to be
    careful, because the day someone adds `from . import search` to improve
    relevance is the day every other test in this file becomes an incomplete
    guard - and this one fails immediately, by name.
    """
    path = APP / module
    assert path.exists(), f"{module} not found at {path}"
    leaked = FORBIDDEN_IMPORTS & _imported_modules(path)
    assert not leaked, (
        f"{module} imports {sorted(leaked)}, which can reach the corpus.\n"
        f"The market feature must not be able to READ document content, not "
        f"merely refrain from sending it. If this import is genuinely needed, "
        f"the promise in market.py's docstring has changed and that has to be "
        f"a deliberate, reviewed decision - not a convenience import."
    )


def test_the_import_guard_would_actually_catch_a_forbidden_import():
    """A guard on the guard: proves `_imported_modules` finds what it claims
    to, so the test above cannot pass by parsing nothing."""
    probe = APP / "analysis.py"          # a module that certainly imports db
    assert "db" in _imported_modules(probe), (
        "the AST import scanner failed to find a known import - the structural "
        "test above would pass vacuously"
    )


def test_the_transport_cannot_reach_the_corpus():
    """The transport half of the split. It may open sockets; it may not read
    documents, and it is the module where that matters most - it is the only
    one holding something that can send."""
    leaked = FORBIDDEN_IMPORTS & _imported_modules(APP / TRANSPORT_MODULE)
    assert not leaked, (
        f"{TRANSPORT_MODULE} imports {sorted(leaked)}, which can reach the "
        f"corpus. This module holds the HTTP client: giving it corpus access "
        f"puts both halves of a leak in one file, which is the arrangement "
        f"the whole split exists to prevent."
    )


def test_the_transport_is_the_only_module_here_with_a_client():
    """States the split as an assertion rather than a comment: exactly one
    file in this feature can make a request."""
    with_client = []
    for module in (*MARKET_MODULES, TRANSPORT_MODULE):
        found = {"httpx", "requests", "urllib", "urllib3", "aiohttp", "socket"}
        if found & _imported_modules(APP / module):
            with_client.append(module)
    assert with_client == [TRANSPORT_MODULE], (
        f"expected only {TRANSPORT_MODULE} to hold an HTTP client, got "
        f"{with_client}"
    )


@pytest.mark.parametrize("module", MARKET_MODULES)
def test_market_modules_import_no_http_client(module):
    """market.py's docstring promised "no HTTP client". That is KEPT: the
    transport is injected by the caller, so no market module imports httpx,
    requests or urllib. A module with no HTTP client cannot make a request
    even if a bug tried to."""
    clients = {"httpx", "requests", "urllib", "urllib3", "http", "aiohttp",
               "socket", "ftplib", "telnetlib"}
    found = clients & _imported_modules(APP / module)
    assert not found, (
        f"{module} imports {sorted(found)}. The market modules build URLs and "
        f"payloads; they do not open sockets. Transport is passed in, which is "
        f"what lets the whole feature be tested air-gapped."
    )


# ----------------------------------------------- the case we cannot filter


def test_a_sentence_the_user_copied_out_of_a_document_is_not_blocked():
    """THE ADVERSARIAL CASE, STATED HONESTLY RATHER THAN PRETENDED AWAY.

    A user can paste a sentence out of their own specification into the
    question box. Some of it will survive the whitelist, because the whitelist
    keeps ordinary subject words and a specification is written in ordinary
    subject words.

    THE SYSTEM CANNOT DISTINGUISH THAT FROM A LEGITIMATE SEARCH. "nominal dry
    film thickness coating system" is both a phrase lifted from clause 11.3
    and exactly what a corrosion engineer would type into a search box from
    memory. There is no filter that separates them, because the difference is
    the user's intent, which is not in the string. A filter claiming to do it
    would be a comfort rather than a control, and would fail in the worse
    direction: it would block real searches while still passing anything
    phrased slightly differently.

    SO THE CONTROL IS NOT A FILTER. It is:

      * the human-approved preview - the user sees the exact phrase before it
        is sent, and pasting a clause is then a visible, deliberate act rather
        than a silent side effect of asking a question;
      * the audit record, asserted below, so what left is reviewable
        afterwards even when nobody objected at the time.

    This test therefore asserts the phrase is NOT empty - it documents that
    the leak is possible - and the two tests after it assert the controls that
    actually apply. Asserting a block here would be asserting a lie.
    """
    pasted = "nominal dry film thickness of coating system no. 1"
    phrase = market_phrase.market_phrase(pasted, CORPUS_FILENAMES)

    assert phrase is not None, (
        "this test exists to record that copied text is NOT blocked. If the "
        "whitelist has become strict enough to return None here, that is a "
        "behaviour change worth reviewing deliberately - and the comment above "
        "about the preview being the control needs revisiting."
    )
    assert "coating" in phrase


def test_the_audit_record_captures_exactly_what_left():
    """The compensating control for the case above. Whatever was sent is
    recorded verbatim, so a review after the fact can see the phrase itself
    rather than an assurance that it was fine."""
    phrase = market_phrase.market_phrase(
        "nominal dry film thickness of coating system no. 1", CORPUS_FILENAMES)
    record = market_providers.audit_record(
        phrase, tier=market_providers.TIER_REFERENCE, outcome="ok")

    assert record["detail"] == phrase, (
        "the audit record must hold the phrase VERBATIM. A summarised, hashed "
        "or truncated record cannot answer the only question it exists for: "
        "what exactly left this machine?"
    )
    assert record["action"] == "market.outbound_query"
    assert record["resource_id"] == market_providers.TIER_REFERENCE
    assert record["at"].endswith("Z"), record["at"]


def test_the_audit_record_holds_no_document_text():
    """The audit table is, in this codebase's own words, the one most likely
    to be exported. It records the phrase because the phrase already left the
    machine; it must never acquire anything that did not."""
    phrase = market_phrase.market_phrase(
        "compare design requirements in doc13.pdf and doc16.pdf",
        CORPUS_FILENAMES)
    record = market_providers.audit_record(
        phrase, tier=market_providers.TIER_LITERATURE, outcome="ok")

    blob = normalise(repr(record))
    for gram in CORPUS_4GRAMS:
        assert gram not in blob, f"document text in the audit record: {gram!r}"
