"""The only text that may leave this machine, built by whitelist.

THE PROMISE THIS FILE IMPLEMENTS, in the client's words: *"only the phrase you
type leaves this machine, you approve it first, and nothing from your documents
is ever part of it."*

The raw question can never be that phrase. "compare design requirements in
doc13.pdf and doc16.pdf" carries FILENAMES, and a filename is corpus metadata:
it tells an outside service which documents this organisation holds. Sent to a
search engine one question at a time, the corpus inventory leaks without a
single passage ever being transmitted.

WHY A WHITELIST AND NOT A BLACKLIST. This is the whole design and it is worth
being explicit about, because the blacklist is the obvious implementation and
it is wrong.

A blacklist removes the things we thought of - filenames, page references,
quoted spans - and PASSES EVERYTHING ELSE THROUGH. So it fails OPEN on the
first input nobody anticipated: a document title typed without its extension,
a project code, a client's internal name for a facility, a rev number in a
format we did not pattern-match, an equipment tag, a person's name. Every one
of those reaches the network, and the failure is silent - the phrase looks
plausible and nobody discovers the leak by reading it.

A whitelist inverts the default. A token reaches the output ONLY by
affirmatively matching something we have decided is safe to say out loud: an
ordinary English subject word, or a public standard designator. Anything
unrecognised is dropped. So the failure mode of an input nobody thought of is
a SHORTER phrase, or no phrase at all - the feature declines to search rather
than over-sharing. That is the direction a privacy control has to fail in.

The cost is real and accepted: this will sometimes drop a term the user
genuinely wanted to search for, and the phrase will be blunter than what they
typed. The preview endpoint exists so they see exactly that before approving.

RETURNING None MEANS DO NOT SEARCH. It never falls through to the raw
question. That is enforced by construction rather than by a rule someone has
to remember: the output string is assembled ONLY from tokens that survived the
whitelist, so there is no code path on which the original text can be
returned. `market_phrase` never sees a reason to reach for the input again.

WHAT THIS FILE DELIBERATELY CANNOT DO. It has no idea what is in the corpus
beyond the filenames it is handed, and it does not import anything that could
find out - no db, no search, no chunker. See
tests/test_market_no_document_leak.py, which enforces that by inspecting the
imports rather than trusting this paragraph.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

#: Hard cap on what may leave, matching `market.preview_query`'s own cap. A
#: phrase longer than this is not a search term, it is a paragraph.
MAX_PHRASE_CHARS = 200

#: The most tokens worth sending. A search engine ignores the tail of a long
#: query anyway, and a short phrase is easier for a human to approve honestly:
#: nobody reads twenty words carefully before clicking a button.
MAX_TOKENS = 12

#: Minimum surviving length. Below this there is nothing to search for.
MIN_PHRASE_CHARS = 3

# --------------------------------------------------------------- removal pass
# These run BEFORE tokenising. They are not the security control - the
# whitelist below is - but they matter for a different reason: they delete
# whole SPANS, so the words inside a quotation or a section reference never
# reach the token stage to be judged individually. Without this,
# "section 7.2 Design Analysis" would lose "7.2" to the whitelist and keep
# "design analysis", quietly turning the client's section heading into a
# search term.

#: Anything the user quoted. A person quoting a clause is quoting THEIR OWN
#: DOCUMENT - that is what quotation marks mean in this context - so the
#: quoted span is treated as document text regardless of how it got there.
#: Curly quotes included: real questions are pasted from Word.
#: The curly quotes and guillemets are DELIBERATE and load-bearing, not
#: characters ruff should straighten: a real question is pasted out of Word or
#: a PDF viewer, and those emit U+2018/U+2019/U+201C/U+201D rather than ASCII.
#: Matching only `"` and `'` would let every pasted quotation through, which is
#: the exact input this pattern exists to catch.
_QUOTED = re.compile(
    r"""["'‘’“”«»]"""      # opening        # noqa: RUF001
    r"""[^"'‘’“”«»]{0,400}"""               # noqa: RUF001
    r"""["'‘’“”«»]"""      # closing        # noqa: RUF001
)

#: Document, page, section and revision references, as spans.
#: `doc13`, `document 4`, `p.125`, `pp 12-14`, `page 7`, `section 7.2`,
#: `clause 3.2`, `table 1`, `figure 4b`, `appendix A`, `annex B`, `rev 2`.
_REFERENCES = (
    re.compile(r"\b(?:doc|docs|document|documents)\s*[-_]?\s*\d+\w*", re.I),
    # The en dash in these two ranges is deliberate for the same reason as the
    # curly quotes above: a page range copied out of a document uses an en
    # dash about as often as a plain hyphen.
    re.compile(r"\bpp?\s*\.\s*\d+(?:\s*[-–]\s*\d+)?", re.I),  # noqa: RUF001
    re.compile(r"\b(?:page|pages)\s+\d+(?:\s*[-–]\s*\d+)?", re.I),  # noqa: RUF001
    re.compile(
        r"\b(?:section|sections|clause|clauses|subsection|table|tables|"
        r"figure|figures|fig|appendix|annex|rev|revision|para|paragraph|"
        r"item|sheet|attachment)\s+[A-Za-z]?[\d.]+[A-Za-z]?\b",
        re.I,
    ),
)

# ------------------------------------------------------------- the whitelist

#: Standards bodies whose designators are PUBLIC identifiers. This is the
#: reason tier 3 exists: the standards this corpus cites - ISO 12944,
#: NORSOK M-501, NIST SP 800-207 - are not DOI-registered works, so a
#: scholarly index cannot answer "what is this standard" and a general
#: reference source has to. Naming a published standard discloses nothing
#: about the client: the standard exists whether or not they hold a copy.
_STANDARD_BODIES = frozenset({
    "iso", "iec", "en", "din", "bs", "astm", "api", "nace", "sspc", "norsok",
    "dnv", "dnvgl", "nist", "ieee", "asme", "aws", "eurocode", "csa", "nfpa",
    "ansi", "saes", "ul", "iogp", "shell", "aramco",
})

#: A designator token: `12944`, `M-501`, `800-207`, `SP`, `RP0188`, `9001`.
#: Allowed ONLY when it trails a standards body - see `_designator_window`.
_DESIGNATOR = re.compile(r"^[A-Za-z]{0,3}-?\d{2,6}(?:[-.]\d{1,4})*[A-Za-z]?$")

#: `SP`, `TR`, `RP`, `TS` - the series letters that sit between a body and its
#: number (NIST **SP** 800-207). Allowed only in the same trailing window.
_SERIES = frozenset({"sp", "tr", "rp", "ts", "pd", "cp", "m", "z", "d"})

#: How many tokens after a standards body a designator may still appear in.
#: "NIST SP 800-207" needs two.
_DESIGNATOR_WINDOW = 2

#: An ordinary subject word: letters only, three or more. Hyphenated compounds
#: are split before this is applied, so "corrosion-resistant" arrives as two
#: tokens and both pass on their own merits.
_SUBJECT_WORD = re.compile(r"^[a-z]{3,}$")

#: Function and instruction words. Dropped because they carry no subject and
#: make the phrase longer for a human to approve, NOT for privacy reasons -
#: the whitelist is what provides privacy. Kept small on purpose: an
#: over-eager stopword list starts deleting real search terms.
_NOISE = frozenset({
    # instruction verbs - the user is addressing the product, not searching
    "compare", "comparing", "list", "find", "show", "tell", "give", "explain",
    "describe", "summarise", "summarize", "analyse", "analyze", "check",
    "identify", "review", "provide", "does", "did", "can", "could", "should",
    "would", "will", "please", "need", "want", "help", "make", "get", "let",
    "deep", "detailed",
    # interrogatives and function words
    "what", "which", "who", "whom", "whose", "when", "where", "why", "how",
    "the", "and", "but", "for", "with", "without", "from", "into", "onto",
    "between", "across", "among", "about", "against", "over", "under",
    "than", "that", "this", "these", "those", "there", "their", "them",
    "they", "your", "yours", "mine", "our", "ours", "its", "his", "her",
    "you", "any", "all", "both", "each", "every", "some", "none", "not",
    "are", "was", "were", "been", "being", "have", "has", "had", "having",
    "also", "only", "just", "very", "more", "most", "much", "many", "such",
    "same", "other", "another", "versus", "documents", "document", "docs",
    "doc", "file", "files", "pdf", "pdfs", "page", "pages", "section",
    "sections", "clause", "clauses", "appendix", "annex", "table", "figure",
    # Document-structure words. Not a privacy matter - "attachment" discloses
    # nothing - but they are never the SUBJECT of a search, and leaving them
    # in produces phrases like "attachment" from "attachment F rev 2", which
    # is a search nobody wanted. "tag" is here for a sharper reason: an
    # equipment tag is exactly the internal identifier this whitelist exists
    # to drop, and the word adds nothing once the number is gone.
    "attachment", "attachments", "sheet", "sheets", "exhibit", "enclosure",
    "schedule", "tag", "tags", "drawing", "drawings", "rev", "revision",
    "para", "paragraph", "item", "items", "no", "nos",
})


def _strip_filenames(text: str, corpus_filenames: Iterable[str]) -> str:
    """Remove every corpus filename, with and without its extension.

    Longest first, so `doc13.pdf` is removed as a unit before the bare stem
    `doc13` can match inside it and leave a stray `.pdf` behind. Case
    insensitive, because a user types `Doc13.PDF` and a filesystem does not
    care.

    The STEM matters as much as the full name and is the case a blacklist
    typically misses: a user who writes "what does doc13 require" never typed
    an extension, and `doc13` on its own is still an inventory disclosure.
    """
    names: set[str] = set()
    for raw in corpus_filenames or ():
        name = str(raw or "").strip()
        if not name:
            continue
        names.add(name)
        stem = re.sub(r"\.[A-Za-z0-9]{1,8}$", "", name)
        if stem:
            names.add(stem)
        # A filename is frequently written with separators the user did not
        # copy exactly. Strip to a comparable core as well.
        core = re.sub(r"[^A-Za-z0-9]+", "", stem)
        if len(core) >= 4:
            names.add(core)

    for name in sorted(names, key=len, reverse=True):
        text = re.sub(re.escape(name), " ", text, flags=re.IGNORECASE)

    # THE SAME NAME, TYPED ANY WAY A PERSON TYPES IT. A reader names
    # `coating-inspection-plan.pdf` as "coating inspection plan", "Coating_
    # Inspection.Plan" or "coatinginspectionplan": the parts in order, with
    # spaces, hyphens, underscores or dots - in any mix, or none - between
    # them, with or without the extension. The exact forms above miss every
    # one of those, and each is still an inventory disclosure. (Found
    # 2026-09-26 building chat web search; honesty audit entry 67.)
    for raw in corpus_filenames or ():
        pattern = _flexible_name(str(raw or ""))
        if pattern is not None:
            text = pattern.sub(" ", text)
    return text


#: What may sit between two parts of a file name as a reader types it.
_NAME_GAP = r"[\s._-]*"


def _is_public_standard_name(parts: list[str]) -> bool:
    """A standards body followed only by designator and series tokens -
    `NORSOK M 501`, `ISO 12944 5` - and nothing else."""
    if len(parts) < 2 or parts[0].lower() not in _STANDARD_BODIES:
        return False
    return all(p.lower() in _SERIES or re.fullmatch(r"[A-Za-z]{0,3}\d{1,6}[A-Za-z]?", p)
               for p in parts[1:])


def _flexible_name(filename: str) -> re.Pattern[str] | None:
    """One pattern matching the file name's parts in order, with any mix of
    separators between them and an optional extension. None for a name with
    no letters or digits."""
    name = filename.strip()
    ext_match = re.search(r"\.([A-Za-z0-9]{1,8})$", name)
    stem = name[:ext_match.start()] if ext_match else name
    parts = re.findall(r"[A-Za-z0-9]+", stem)
    if not parts:
        return None
    if _is_public_standard_name(parts):
        # A FILE NAMED AFTER A PUBLISHED STANDARD - `NORSOK-M-501.pdf` - is
        # the one exception, and it is the collision
        # test_the_standard_named_file_leaks_only_the_public_designator
        # asserts: the standard's name is public (it exists whether or not
        # this client holds a copy), and removing it would make "is there a
        # newer edition of NORSOK M-501?" impossible to ask for any standard
        # in the library. Its exact filename forms are still removed above.
        return None
    body = _NAME_GAP.join(re.escape(p) for p in parts)
    if ext_match:
        body += f"(?:{_NAME_GAP}{re.escape(ext_match.group(1))})?"
    return re.compile(body, re.IGNORECASE)


def _tokenise(text: str) -> list[str]:
    """Split into candidate tokens, preserving designator punctuation.

    Hyphens inside words are split (`corrosion-resistant` -> two tokens) but a
    hyphen between letters and digits is kept (`M-501` stays one token),
    because that is the shape of a standard designator.
    """
    text = re.sub(r"(?<=[A-Za-z])-(?=[A-Za-z])", " ", text)
    return [t for t in re.split(r"[^A-Za-z0-9.\-]+", text) if t]


def market_phrase(question: str, corpus_filenames: Iterable[str]) -> str | None:
    """A phrase safe to send to a third party, or None meaning DO NOT SEARCH.

    None is a real answer and the caller must treat it as one. It never means
    "fall back to the question"; there is no code path here that returns the
    input.
    """
    if not question or not str(question).strip():
        return None

    text = str(question)

    # 1. SPAN REMOVAL. Quotations and references go as whole spans, before any
    #    token is judged, so the words inside them never get a chance to look
    #    like ordinary subject words.
    text = _QUOTED.sub(" ", text)
    text = _strip_filenames(text, corpus_filenames)
    for pattern in _REFERENCES:
        text = pattern.sub(" ", text)

    # 2. THE WHITELIST. From here nothing survives by default.
    kept: list[str] = []
    seen: set[str] = set()
    body_at: int | None = None      # index in `tokens` of the last standards body

    tokens = _tokenise(text)
    for i, raw in enumerate(tokens):
        token = raw.strip(".-")
        if not token:
            continue
        low = token.lower()

        # (a) a standards body - a public identifier, and it opens a window in
        #     which its designator may follow.
        if low in _STANDARD_BODIES:
            body_at = i
            if low not in seen:
                kept.append(low)
                seen.add(low)
            continue

        # (b) a series letter or a designator, but ONLY while trailing a body.
        #     Outside that window a bare number is a page reference and a bare
        #     code is an internal identifier, and neither may leave.
        in_window = body_at is not None and (i - body_at) <= _DESIGNATOR_WINDOW
        if in_window and (low in _SERIES or _DESIGNATOR.match(token)):
            # Extend the window so "NIST SP 800-207" reaches the number.
            body_at = i
            if low not in seen:
                kept.append(token.upper() if len(token) <= 3 else token)
                seen.add(low)
            continue

        # (c) an ordinary subject word.
        if _SUBJECT_WORD.match(low) and low not in _NOISE:
            if low not in seen:
                kept.append(low)
                seen.add(low)
            continue

        # (d) everything else is dropped. Unrecognised input shortens the
        #     phrase; it never widens it.

        if len(kept) >= MAX_TOKENS:
            break

    if not kept:
        return None

    phrase = " ".join(kept[:MAX_TOKENS])[:MAX_PHRASE_CHARS].strip()
    if len(phrase) < MIN_PHRASE_CHARS:
        return None
    return phrase
