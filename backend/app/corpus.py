"""Questions about the corpus itself, and counts that pretend to be about it.

THE DEFECT. Document Q&A was asked how many standards there are, and answered
"there are 12 distinct standards" - from three retrieved passages, while the
library held 272. Two things were wrong, and this module is the fix for both:

1. THE QUESTION WENT TO THE WRONG PLACE. "How many standards do you have" is
   not a question about what any document SAYS. It is a question about the
   library, and the library is a table: a scoped COUNT answers it exactly.
   Retrieval can only ever return the closest few passages, so any count
   derived from it is a count of those passages - and the model, shown three
   passages, reported what it saw as though it had seen everything.

2. THE ANSWER STATED A COUNT AS A FACT ABOUT THE CORPUS. CLAUDE.md rule 4:
   every count states its boundary. A generated answer sees only the passages
   it was given, so any count of DOCUMENTS it produces is a count of those
   passages and must say so, in those words. That is enforced here on the
   model's OUTPUT, not requested in its prompt: the local model can ignore a
   prompt, and "enforced in code" is what the rule says.

WHY DOCUMENT KINDS AND NOT EVERY NUMBER. "The vessel has 4 nozzles [S1]" is a
count of things IN a cited passage, and the citation is its boundary - the
reader can open [S1] and count. "There are 12 standards" ranges over the
LIBRARY, which no passage contains and no citation can bound. So the guard
applies to counts of documents and their kinds - standards, specifications,
documents, files, datasheets, submittals, drawings, procedures, reports,
manuals, codes - and not to counts of things a single passage describes.

Classification is CONSERVATIVE, the rule intent.py already follows: a
question this module is unsure about is left to retrieval, which is where it
was before. A false positive would answer "which standards cover coating?"
with a library total and never search - the worse failure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .db import connect

# ---------------------------------------------------------------- vocabulary

#: The noun a reader uses -> the document_role it means (None = every role).
#: Singular and plural, because "how many standard are there" still means it.
_NOUN_ROLE: dict[str, str | None] = {
    "standard": "COMPANY_STANDARD", "standards": "COMPANY_STANDARD",
    "specification": "COMPANY_STANDARD", "specifications": "COMPANY_STANDARD",
    "spec": "COMPANY_STANDARD", "specs": "COMPANY_STANDARD",
    "submittal": "CONTRACTOR_SUBMITTAL", "submittals": "CONTRACTOR_SUBMITTAL",
    "datasheet": "CONTRACTOR_SUBMITTAL", "datasheets": "CONTRACTOR_SUBMITTAL",
    "document": None, "documents": None, "file": None, "files": None,
    "pdf": None, "pdfs": None,
}

#: How each role is named in an answer, singular and plural.
ROLE_LABEL: dict[str | None, tuple[str, str]] = {
    "COMPANY_STANDARD": ("company standard", "company standards"),
    "CONTRACTOR_SUBMITTAL": ("contractor submittal", "contractor submittals"),
    "CONTRACT_DOCUMENT": ("contract document", "contract documents"),
    "SUPPORTING_DOCUMENT": ("supporting document", "supporting documents"),
    "CRS_TEMPLATE": ("CRS template", "CRS templates"),
    None: ("document", "documents"),
}

#: Where the full list lives, for "list all" - a chat answer is the wrong
#: place to print 272 filenames, and a partial list would imply completeness.
_WHERE_LISTED: dict[str | None, str] = {
    "COMPANY_STANDARD": "the Standards Library page",
    None: "the Documents page",
}

#: A document is LOADED once it can answer questions. Anything else in scope
#: is still being processed, or failed, and is reported separately rather than
#: silently counted as loaded.
_LOADED = ("ready", "partially_searchable")

_NOUN = r"(?:" + "|".join(sorted(_NOUN_ROLE, key=len, reverse=True)) + r")"
#: Words that can sit between the verb and the noun without changing what is
#: being counted: "how many COMPANY standards", "list all THE documents".
_MODIFIERS = (r"(?:(?:company|contractor|distinct|different|unique|total|"
              r"separate|individual|the|your|all|every|of)\s+)*")

#: The phrasings of a question about the library. Each captures the noun.
_CORPUS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("count", re.compile(r"\bhow\s+many\s+" + _MODIFIERS + r"(" + _NOUN + r")\b")),
    ("count", re.compile(r"\b(?:total\s+)?number\s+of\s+" + _MODIFIERS
                         + r"(" + _NOUN + r")\b")),
    ("count", re.compile(r"\bcount\s+(?:of\s+)?" + _MODIFIERS + r"(" + _NOUN + r")\b")),
    ("list", re.compile(r"\b(?:list|show|name|enumerate)\s+(?:me\s+)?" + _MODIFIERS
                        + r"(" + _NOUN + r")\b")),
    ("list", re.compile(r"\b(?:which|what)\s+" + _MODIFIERS + r"(" + _NOUN
                        + r")\s+(?:do\s+you\s+have|have\s+you\s+got|are\s+"
                        r"(?:there|loaded|uploaded|available|stored|indexed|"
                        r"in\s+the\s+(?:library|system))|exist)\b")),
)

#: "what is loaded", "what's in the library" - no noun, so every role.
_WHAT_IS_LOADED = re.compile(
    r"\bwhat(?:'s|\s+is|\s+has\s+been)\s+(?:been\s+)?"
    r"(?:loaded|uploaded|available|indexed|in\s+the\s+(?:library|system))\b")

#: Words that ask about the collection without narrowing it. Anything a
#: question carries BEYOND these is content - "which standards cover
#: HYDROTESTING" - and makes it a question for retrieval as well.
_NEUTRAL = frozenset("""
    a an the all any every each of in on to for is are was were be been has
    have had do does did you your we our i my me us it its there here this
    that these those how many much what which whats list show name enumerate
    number count total tell give see read access can could would will please
    now currently today loaded uploaded available stored indexed ingested held
    library system corpus collection database repository machine altogether
    overall exist exists existing got company contractor distinct different
    unique separate individual readable accessible
""".split())


@dataclass(frozen=True)
class CorpusQuestion:
    """What a corpus question asks for."""

    kind: str               # "count" or "list"
    role: str | None        # document_role, or None for every role
    #: Content beyond the collection itself - "which standards cover
    #: hydrotesting". Such a question gets BOTH answers, clearly separated:
    #: the library's count from the database, and retrieval for the rest.
    qualified: bool
    #: The words that made it qualified, for the record and the tests.
    content: tuple[str, ...] = ()


def _normalise(question: str) -> str:
    return " ".join(re.sub(r"[^\w'\s-]", " ", (question or "").lower()).split())


def classify(question: str) -> CorpusQuestion | None:
    """A question about the library, or None if it is not one.

    None is the default and the safe answer: it sends the question to
    retrieval, exactly where it went before this module existed.
    """
    text = _normalise(question)
    if not text:
        return None
    kind = role = None
    span = None
    for pattern_kind, pattern in _CORPUS_PATTERNS:
        m = pattern.search(text)
        if m:
            kind, role, span = pattern_kind, _NOUN_ROLE[m.group(1)], m.span()
            break
    if kind is None:
        m = _WHAT_IS_LOADED.search(text)
        if not m:
            return None
        kind, role, span = "list", None, m.span()

    # Whatever is left once the corpus phrase and neutral words are gone is
    # CONTENT. "how many standards are there" leaves nothing; "how many
    # standards cover hydrotesting" leaves ("cover", "hydrotesting").
    rest = (text[:span[0]] + " " + text[span[1]:]).split()
    content = tuple(w for w in rest
                    if w.strip("'-") not in _NEUTRAL and w not in _NOUN_ROLE
                    and not w.isdigit())
    return CorpusQuestion(kind=kind, role=role, qualified=bool(content),
                          content=content)


# -------------------------------------------------------------- the count


def counts(*, allowed_document_ids: frozenset[str]) -> dict[str | None, dict]:
    """Documents the caller may read, by role, split into loaded and not.

    SCOPED IN THE QUERY, never in Python, and an empty scope counts nothing:
    the same rule as everywhere else, so a corpus answer cannot become the
    cheapest way to learn how many documents exist that you cannot read.
    """
    if not allowed_document_ids:
        return {}
    marks = ",".join("?" for _ in allowed_document_ids)
    rows = connect().execute(
        f"""SELECT c.document_role AS role, d.status AS status, COUNT(*) AS n
            FROM documents d
            LEFT JOIN document_classification c ON c.document_id = d.id
            WHERE d.id IN ({marks})
            GROUP BY c.document_role, d.status""",
        sorted(allowed_document_ids)).fetchall()
    out: dict[str | None, dict] = {}
    for r in rows:
        slot = out.setdefault(r["role"], {"loaded": 0, "not_loaded": 0})
        slot["loaded" if r["status"] in _LOADED else "not_loaded"] += r["n"]
    return out


def _label(role: str | None, n: int) -> str:
    singular, plural = ROLE_LABEL.get(role, (str(role), str(role)))
    return singular if n == 1 else plural


def statement(question: CorpusQuestion, *,
              allowed_document_ids: frozenset[str]) -> dict:
    """The database's answer, as a sentence and as numbers.

    "272 company standards are loaded and readable by you." - the boundary is
    in the sentence itself: READABLE BY YOU is the scope, and LOADED is the
    status. A count with neither would read as the size of the world.
    """
    by_role = counts(allowed_document_ids=allowed_document_ids)
    if question.role is None:
        loaded = sum(v["loaded"] for v in by_role.values())
        not_loaded = sum(v["not_loaded"] for v in by_role.values())
    else:
        slot = by_role.get(question.role, {"loaded": 0, "not_loaded": 0})
        loaded, not_loaded = slot["loaded"], slot["not_loaded"]

    if loaded == 0:
        # Not "0 standards exist": that would be a claim about documents this
        # caller cannot see. It is a claim about what THEY can read.
        text = f"No {_label(question.role, 0)} are loaded that you can read."
    else:
        verb = "is" if loaded == 1 else "are"
        text = f"{loaded} {_label(question.role, loaded)} {verb} loaded and readable by you."

    if question.role is None and loaded:
        # "What is loaded" deserves the breakdown, not just the total.
        parts = [f"{v['loaded']} {_label(role, v['loaded'])}"
                 for role, v in sorted(by_role.items(), key=lambda kv: -kv[1]["loaded"])
                 if v["loaded"] and role is not None]
        unassigned = by_role.get(None, {}).get("loaded", 0)
        if unassigned:
            parts.append(f"{unassigned} with no role recorded")
        # Only when it says something: "1 document is loaded: 1 with no role
        # recorded" repeats the total as its own breakdown.
        if len(parts) > 1:
            text = text[:-1] + ": " + _join(parts) + "."
    if not_loaded:
        text += (f" {not_loaded} more {'is' if not_loaded == 1 else 'are'} not"
                 f" yet loaded - still being processed, or failed.")
    if question.kind == "list" and loaded:
        where = _WHERE_LISTED.get(question.role, _WHERE_LISTED[None])
        text += f" The full list is on {where}."
    return {"text": text, "role": question.role, "loaded": loaded,
            "not_loaded": not_loaded, "kind": question.kind,
            "source": "database", "qualified": question.qualified}


def _join(parts: list[str]) -> str:
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


# ------------------------------------------ counts in a GENERATED answer

_NUMBER = (r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|"
           r"twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|"
           r"nineteen|twenty|thirty|forty|fifty|a\s+dozen)")
#: Markdown emphasis the model may wrap around any word of the count. FOUND ON
#: THE REAL MODEL: asked "how many standards cover hydrostatic testing", it
#: wrote "**five** distinct standards are referenced" - and the first version
#: of this pattern required whitespace straight after the number, so the bold
#: markers hid the count from it. The synthetic tests had used plain text.
_MD = r"[*_`]{0,3}"
_COUNT_ADJ = (r"(?:(?:distinct|different|separate|unique|individual|total|"
              r"other|relevant|applicable|company|contractor|referenced|"
              r"related|such|additional|more)" + _MD + r"\s+" + _MD + r"){0,3}")
_DOC_KINDS = (r"(?:standards|specifications|specs|documents|files|datasheets|"
              r"data\s+sheets|submittals|drawings|procedures|reports|manuals|"
              r"codes)")
#: "12 distinct standards", "twelve documents", "a total of 12 specs",
#: "**five** distinct standards".
#: Letter/digit lookarounds, not `\b`: an underscore is a WORD character to the
#: regex engine, so `\b` finds no boundary inside "_twelve_" and Markdown's
#: underscore emphasis would hide the count exactly as the bold did.
COUNT_CLAIM = re.compile(r"(?<![A-Za-z0-9])" + _NUMBER + _MD + r"\s+" + _MD
                         + _COUNT_ADJ + _DOC_KINDS + r"(?![A-Za-z0-9])",
                         re.IGNORECASE)

#: The words that make a count honest, required verbatim: the task says any
#: count "must say so IN THOSE WORDS". A sentence already carrying one is
#: left exactly as the model wrote it.
_BOUNDED = re.compile(r"\bretrieved\b", re.IGNORECASE)

#: Framing that asserts the LIBRARY, neutralised where it sits beside a count
#: so the corrected sentence does not argue with itself.
_FRAMING = (
    (re.compile(r"\b(?:the|this|your|our)\s+(?:library|corpus|collection|system|"
                r"database|repository)\s+(?:contains|holds|has|includes|lists)\b",
                re.IGNORECASE), "the retrieved passages mention"),
    (re.compile(r"\b(?:in|within|across)\s+(?:the|this|your|our)\s+(?:library|"
                r"corpus|collection|system|database|repository)\b",
                re.IGNORECASE), "in the retrieved passages"),
    (re.compile(r"\s+in\s+total\b", re.IGNORECASE), ""),
)

#: Sentence AND line boundaries, CAPTURED so they survive the round trip. A
#: first version split on sentences and re-joined with one space, which would
#: have flattened the paragraphs and bullet lists the prompt asks the model
#: for; and each bullet line needs checking on its own, not as one "sentence".
_SEPARATOR = re.compile(r"((?<=[.!?])[ \t]+|\n+)")


def bound_counts(text: str, retrieved: int) -> tuple[str, int]:
    """Make every count of documents in a generated answer name its boundary.

    Returns the corrected text and how many sentences were corrected.

    A sentence that counts documents and does NOT say "retrieved" gets the
    boundary inserted right after the count, where it cannot be missed:

        There are 12 distinct standards [S1].
     -> There are 12 distinct standards (counted in the 3 passages retrieved
        for this question, not in the library) [S1].

    Edited, not refused. The count may be a true count of what the passages
    show, and the citation still lets the reader check it; what was false was
    only its reach. This is the same kind of correction `answer` already
    makes to model text when it strips an invented citation.
    """
    if not text:
        return text, 0
    boundary = (f"counted in the {retrieved} passage{'' if retrieved == 1 else 's'}"
                f" retrieved for this question, not in the library")
    corrected = 0
    parts = _SEPARATOR.split(text)
    # Even indices are sentences or lines; odd indices are the separators,
    # passed through untouched.
    for i in range(0, len(parts), 2):
        sentence = parts[i]
        match = COUNT_CLAIM.search(sentence)
        if match is None or _BOUNDED.search(sentence):
            continue
        corrected += 1
        head, tail = sentence[:match.end()], sentence[match.end():]
        leading_capital = head[:1].isupper()
        for pattern, replacement in _FRAMING:
            head = pattern.sub(replacement, head)
            tail = pattern.sub(replacement, tail)
        # A substitution at the very start of a sentence ("The library
        # contains" -> "the retrieved passages mention") must keep the
        # sentence's capital.
        if leading_capital and head[:1].islower():
            head = head[0].upper() + head[1:]
        parts[i] = f"{head} ({boundary}){tail}"
    return "".join(parts), corrected
