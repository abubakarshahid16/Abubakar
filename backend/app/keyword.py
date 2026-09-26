"""SQLite FTS5 keyword index.

Built immediately after chunking and BEFORE any embedding, because keyword
search needs no vectors. A 1,200-page specification is therefore answerable
seconds after upload, while embedding continues in the background and upgrades
retrieval from keyword-only to hybrid.

Tokenisation matters more here than it looks. Petroleum specifications are full
of identifiers - `API 610`, clause `5.3.2`, `ASTM A216 WCB`, `P-101A` - and the
default unicode61 tokenizer splits on `.` and `-`, turning `5.3.2` into three
separate tokens and destroying exactly the lookups lexical search exists to get
right. Those characters are kept inside tokens instead.
"""

from __future__ import annotations

import difflib
import re
import sqlite3

from .db import connect
from .rates import Timer, rate

#: Keep `.`, `-`, `/` and `_` inside tokens so identifiers survive intact.
TOKENIZER = "unicode61 remove_diacritics 2 tokenchars '.-/_'"

SCHEMA = f"""
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text,
    section,
    filename,
    chunk_id UNINDEXED,
    document_id UNINDEXED,
    tokenize = "{TOKENIZER}"
);
"""

#: An engineering identifier, in the shapes that actually occur in petroleum
#: standards. Written as explicit alternatives rather than one clever pattern,
#: because each shape is a real convention and a missed one is a lookup that
#: silently fails:
#:
#:   API 610        standard body + number
#:   ISO 13709      standard body + number
#:   ASTM A216      standard body + lettered grade
#:   NORSOK L-001   standard body + lettered series
#:   AISI 4140      material standard + number
#:   CA6NM          material grade
#:   P-101A         equipment tag
#:   5.3.2 / 7.1    clause number
IDENTIFIER = re.compile(
    r"""\b(?:
          [A-Z]{2,}[-\s][A-Z]-?\d+[A-Za-z0-9.\-]*   # ASTM A216, NORSOK L-001
        | [A-Z]{2,}[-\s]?\d+[A-Za-z0-9.\-]*         # API 610, ISO 13709, AISI 4140
        | [A-Z]{1,3}-\d+[A-Za-z0-9\-]*              # P-101A, L-001
        | [A-Z]{2}\d[A-Z0-9]{2,}                    # CA6NM
        | \d+(?:\.\d+){1,3}                         # 5.3.2, 7.1
    )\b""",
    re.VERBOSE,
)

#: A designator: a noun followed by a number or alphanumeric suffix.
#:   "coating system no. 1", "system 3B", "type 2", "class 300", "grade B"
#: These are NOT code-shaped, so the pattern above misses them entirely - and
#: missing one is worse than missing a code, because the retrieved passage is
#: about a DIFFERENT system and reads perfectly plausible. On a coating
#: specification that means reporting system 4's film thickness as system 1's.
DESIGNATOR_WORDS = (
    "system", "type", "class", "grade", "category", "level", "group",
    "table", "figure", "annex", "clause", "section", "revision", "rev",
)
DESIGNATOR = re.compile(
    r"\b(" + "|".join(DESIGNATOR_WORDS) + r")\b"
    r"(?:\s+(?:no\.?|number|nr\.?))?"
    r"\s*[:.]?\s*"
    r"(\d+[A-Za-z]?)\b",
    re.IGNORECASE,
)


def find_designators(text: str) -> list[str]:
    """Normalised designators, e.g. "system 1", "type 2", "class 300"."""
    return [f"{m.group(1).lower()} {m.group(2).upper()}" for m in DESIGNATOR.finditer(text)]


def designator_variants(designator: str) -> list[str]:
    """The spellings a document might use for one designator.

    "system 1" appears as "system no. 1", "system No. 1", "system 1" - all of
    which must match, or requiring the designator would exclude the very
    passage that answers the question.
    """
    word, _, value = designator.partition(" ")
    return [
        f"{word} {value}",
        f"{word} no. {value}",
        f"{word} no {value}",
        f"{word} number {value}",
    ]


def ensure_schema(conn: sqlite3.Connection | None = None) -> None:
    conn = conn or connect()
    conn.executescript(SCHEMA)
    conn.commit()


def index_document(
    document_id: str,
    advance_to: str | None = None,
    expect_status: str | None = None,
) -> dict:
    """(Re)build the keyword index for one document.

    Only retrievable chunks are indexed, so search can never return a chunk
    the quality gate or classifier excluded - the exclusion is enforced at
    index time rather than relying on every query remembering to filter.

    `advance_to` moves the document's status IN THE SAME TRANSACTION as the
    index write. Doing the work and advancing the state used to be two
    separate steps, which left a document with a fully built, searchable
    index still sitting at `indexing_keyword` - so embedding never started
    and the document was stranded. Either both happen or neither does.
    """
    timer = Timer()
    conn = connect()
    ensure_schema(conn)

    rows = conn.execute(
        """SELECT id, text, section, filename FROM chunks
           WHERE document_id = ? AND retrievable = 1 ORDER BY ordinal""",
        (document_id,),
    ).fetchall()

    with conn:
        conn.execute("DELETE FROM chunks_fts WHERE document_id = ?", (document_id,))
        conn.executemany(
            """INSERT INTO chunks_fts (text, section, filename, chunk_id, document_id)
               VALUES (?, ?, ?, ?, ?)""",
            [(r["text"], r["section"] or "", r["filename"], r["id"], document_id) for r in rows],
        )
        if advance_to is not None:
            # compare-and-set, so a concurrent change cannot be overwritten
            if expect_status is None:
                conn.execute(
                    "UPDATE documents SET status = ? WHERE id = ?",
                    (advance_to, document_id),
                )
            else:
                conn.execute(
                    "UPDATE documents SET status = ? WHERE id = ? AND status = ?",
                    (advance_to, document_id, expect_status),
                )

    elapsed = timer.seconds()
    return {
        "document_id": document_id,
        "indexed": len(rows),
        "seconds": elapsed,
        "chunks_per_sec": rate(len(rows), elapsed),
    }


def _scope_predicate(
    allowed_document_ids: frozenset[str],
) -> tuple[str, list[object]]:
    """` AND document_id IN (...)`, and the ids to bind.

    Same construction as `search` above, for the same reason: the restriction
    goes INSIDE the SQL. Ids are bound as parameters, never concatenated.
    """
    marks = ",".join("?" * len(allowed_document_ids))
    return f" AND document_id IN ({marks})", sorted(allowed_document_ids)


def indexed_count(
    document_id: str | None = None,
    *,
    allowed_document_ids: frozenset[str],
) -> int:
    """How many indexed chunks the caller may read.

    `allowed_document_ids` is REQUIRED and keyword-only, and has no default -
    the same discipline as `search`, and for the same reason. This count is
    the denominator the lexical gate judges commonness against and the switch
    that decides whether the gate runs at all, so an unscoped value let a
    caller's answerability verdict be decided by documents they cannot read.
    """
    conn = connect()
    ensure_schema(conn)
    if not allowed_document_ids:
        # A real answer: this caller may read nothing, so nothing is indexed
        # for them. The gate treats 0 as "abstain", which is the safe
        # direction - it never becomes a claim that a term is absent.
        return 0
    scope_sql, scope_params = _scope_predicate(allowed_document_ids)
    params: list[object] = []
    where = "1 = 1"
    if document_id is not None:
        where += " AND document_id = ?"
        params.append(document_id)
    where += scope_sql
    params.extend(scope_params)
    return conn.execute(
        f"SELECT COUNT(*) FROM chunks_fts WHERE {where}", params
    ).fetchone()[0]


def drop_document(document_id: str) -> None:
    conn = connect()
    ensure_schema(conn)
    with conn:
        conn.execute("DELETE FROM chunks_fts WHERE document_id = ?", (document_id,))


# ------------------------------------------------------------------ querying


#: Punctuation that carries no meaning in a question. `.`, `-`, `/` and `_`
#: are DELIBERATELY kept: they live inside the identifiers this index exists to
#: get right, and stripping them turns `5.3.2` into `532` and `P-101A` into
#: `P101A`, neither of which is in the index.
_QUERY_PUNCTUATION = re.compile(r"[^\w\s./\-]+")


def normalise_query(question: str) -> str:
    """The question as the FTS query builder should see it.

    Punctuation removed, whitespace collapsed. CASE IS DELIBERATELY LEFT
    ALONE: FTS5 matching is already case-insensitive, so folding buys nothing
    here, and IDENTIFIER and DESIGNATOR both key off capitalisation - lower
    casing the question stops `API 610` being recognised as an identifier and
    silently turns a required term into an optional one.
    """
    return " ".join(_QUERY_PUNCTUATION.sub(" ", question).split())


# ------------------------------------------------------- typo tolerance
#
# Issue #85: a misspelled query went to FTS exactly as typed, matched nothing,
# and the answer layer refused - because lexical.assess saw every distinctive
# term as absent from the corpus. Real users type badly and the product must
# degrade, never refuse.
#
# The correction is drawn from the INDEX ITSELF - the fts5vocab table is the
# exact set of terms that could ever match - so no dictionary, no model and no
# new dependency is involved. difflib is stdlib.

#: Below this similarity two words are different words, not a typo. 0.82 keeps
#: "strctural"->"structural" (0.947) and "sumbittal"->"submittal" (0.889) and
#: rejects "steel"/"steal" (0.8) and "class"/"clause" (0.727) - see
#: tests/test_typo_tolerance.py, which asserts both directions.
FUZZY_CUTOFF = 0.82

#: Shorter words are not corrected. At three characters a single edit is a
#: different word far more often than it is a typo.
FUZZY_MIN_WORD = 5

#: A query returning fewer than this many rows is treated as a miss worth
#: retrying. Not just zero: one weak hit on a common word is the same failure
#: as no hit, and it is what "sumbittal requirements" produces.
FUZZY_MIN_HITS = 3

#: Vocabulary is rebuilt when the number of indexed chunks changes, the same
#: cache key acronyms.py uses.
_vocab_cache: dict[tuple[str | None, int], list[str]] = {}


def vocabulary(
    document_id: str | None = None,
    *,
    allowed_document_ids: frozenset[str],
) -> list[str]:
    """Every term the keyword index actually contains.

    Read from fts5vocab, which is the index's own term list, so a correction
    can only ever be a word that is really there. Returns [] if the SQLite
    build has no fts5vocab - typo tolerance then simply does not happen, which
    is the same graceful degradation the reranker gets.

    CORPUS-WIDE, BY NECESSITY: fts5vocab holds one term list for the whole
    index and cannot be filtered by document, whatever scope is passed. So
    this list is CANDIDATES ONLY and must never be shown to anyone as it is.
    `fuzzy_corpus_match` checks each candidate against the caller's scope
    with `term_occurrences` before offering it (B12, fixed 2026-09-22 - before
    that, a correction could name a word occurring only in a document the
    caller may not read).
    """
    conn = connect()
    ensure_schema(conn)
    key = (
        document_id,
        indexed_count(document_id, allowed_document_ids=allowed_document_ids),
    )
    cached = _vocab_cache.get(key)
    if cached is not None:
        return cached
    try:
        conn.executescript(
            "CREATE VIRTUAL TABLE IF NOT EXISTS chunks_vocab "
            "USING fts5vocab(chunks_fts, 'row');"
        )
        terms = [
            r[0] for r in conn.execute(
                "SELECT term FROM chunks_vocab WHERE length(term) >= ?",
                (FUZZY_MIN_WORD - 2,),
            )
        ]
    except sqlite3.OperationalError:
        terms = []
    _vocab_cache.clear()          # one corpus state at a time; keep it small
    _vocab_cache[key] = terms
    return terms


def reset_vocabulary_cache() -> None:
    _vocab_cache.clear()


def _correctable(word: str) -> bool:
    """Is this a word a typo correction may touch at all?

    NOT identifiers and NOT anything containing a digit. `API 610` and
    `API 611` are one edit apart and are different standards; "correcting" one
    to the other would answer a question nobody asked, which is far worse than
    returning nothing. Only ordinary alphabetic words are eligible.
    """
    if len(word) < FUZZY_MIN_WORD:
        return False
    if not word.isalpha():
        return False
    return not IDENTIFIER.fullmatch(word)


def fuzzy_corpus_match(
    word: str,
    document_id: str | None = None,
    *,
    allowed_document_ids: frozenset[str],
) -> str | None:
    """The corpus term this word is probably a misspelling of, or None.

    A word that IS in the corpus is never corrected - the reader's spelling
    wins whenever it matches something.

    SCOPED, AND THE SCOPE IS REQUIRED, for the reason `term_occurrences`
    gives: "is this word in the corpus" is the question a caller must not be
    able to ask about documents they hold no grant on. A word present only in
    a document they may not read has to count as absent FOR THEM, or the
    correction itself reports that the document exists.
    """
    if not _correctable(word):
        return None
    lowered = word.lower()
    if term_occurrences(
        lowered, document_id, allowed_document_ids=allowed_document_ids
    ) > 0:
        return None
    terms = vocabulary(document_id, allowed_document_ids=allowed_document_ids)
    if not terms:
        return None
    # A candidate more than three characters different in length cannot reach
    # the cutoff; skipping them keeps this linear-but-cheap on a large corpus.
    near = [t for t in terms if abs(len(t) - len(lowered)) <= 3]
    if not near:
        # No word close enough in length to be a misspelling of this one.
        # `difflib.get_close_matches` raises on n=0, and it did: a question
        # whose word had no length-neighbour in the vocabulary crashed the
        # search instead of simply having no correction.
        return None
    # B12: `terms` is the WHOLE index's vocabulary - fts5vocab cannot be
    # filtered by document - so every candidate is checked against this
    # caller's scope before it is offered, best first. A closer word that
    # occurs only in a document they may not read is skipped, never named.
    for candidate in difflib.get_close_matches(
        lowered, near, n=len(near), cutoff=FUZZY_CUTOFF
    ):
        if candidate == lowered:
            continue
        if term_occurrences(
            candidate, document_id, allowed_document_ids=allowed_document_ids
        ) > 0:
            return candidate
    return None


def spelling_corrections(
    question: str,
    document_id: str | None = None,
    *,
    allowed_document_ids: frozenset[str],
) -> dict[str, str]:
    """{word as typed: word as the corpus spells it} for this question.

    Only words ABSENT from the corpus are considered, so this can never
    rewrite a term that already matches something. The result is reported, not
    hidden: the caller shows the reader what was searched.
    """
    out: dict[str, str] = {}
    for word in re.findall(r"[A-Za-z][\w.\-/]*", normalise_query(question)):
        if word.lower() in out:
            continue
        correction = fuzzy_corpus_match(
            word, document_id, allowed_document_ids=allowed_document_ids
        )
        if correction:
            out[word.lower()] = correction
    return out


def tolerant_variants(
    question: str, corrections: dict[str, str]
) -> dict[str, list[str]]:
    """{word as typed: every spelling worth trying for it}.

    Three forms per correctable word: the word AS TYPED (its own matches are
    never given up), the corpus spelling difflib found, and the prefix form,
    which catches the truncation case - "struct" for "structural" - that an
    edit-distance correction does not.

    They are OR-ed, never substituted, so a tolerant query can only ADD
    passages. The meaning of the question does not change: "strctural" is
    searched as (strctural OR structural OR strctural*), and a reader asking
    about submittals is never quietly answered about something else.
    """
    variants: dict[str, list[str]] = {}
    for word in normalise_query(question).split():
        key = word.lower()
        if not _correctable(word):
            continue
        forms = [key]
        correction = corrections.get(key)
        if correction and correction not in forms:
            forms.append(correction)
        variants[key] = forms
    return variants


def _escape(token: str) -> str:
    """FTS5 treats several characters as syntax. Quote every token."""
    return '"' + token.replace('"', '""') + '"'


# Deliberately small and query-oriented.  Domain words (including short ones
# such as ``oil`` and ``gas``) do not belong here: removing a useful term is
# much more damaging than leaving an uncommon conversational word behind.
STOPWORDS = frozenset({
    "a", "about", "an", "and", "are", "as", "at", "be", "by", "can",
    "could", "do", "does", "for", "from", "how", "i", "in", "is", "it",
    "me", "of", "on", "or", "please", "tell", "that", "the", "this", "to",
    "us", "was", "what", "when", "where", "which", "who", "why", "with",
    "would", "you", "your",
})

_QUERY_TOKEN = re.compile(r"[\w.\-/]{2,}")


def content_phrases(question: str) -> list[str]:
    """Consecutive runs of two or more meaningful query words.

    Identifiers and numbered designators already have stricter handling, so
    they are blanked before phrase extraction.  Stopwords split a run: this
    avoids inventing a phrase across words the user actually placed between
    its terms.
    """
    excluded = [m.span() for m in IDENTIFIER.finditer(question)]
    excluded.extend(m.span() for m in DESIGNATOR.finditer(question))
    runs: list[list[str]] = []
    run: list[str] = []
    for match in _QUERY_TOKEN.finditer(question):
        if any(start < match.end() and match.start() < end for start, end in excluded):
            if len(run) >= 2:
                runs.append(run)
            run = []
            continue
        token = match.group(0)
        if token.lower() in STOPWORDS:
            if len(run) >= 2:
                runs.append(run)
            run = []
        else:
            run.append(token)
    if len(run) >= 2:
        runs.append(run)
    return [" ".join(words) for words in runs]


def build_phrase_query(question: str) -> str:
    """An optional exact-phrase MATCH expression used as a lexical boost."""
    return " OR ".join(_escape(phrase) for phrase in content_phrases(question))


def build_match_query(
    question: str, variants: dict[str, list[str]] | None = None
) -> str:
    """Turn a natural question into an FTS5 MATCH expression.

    Identifiers are required rather than merely preferred: a question naming
    `API 610` is asking about API 610, and a passage that does not mention it
    is not an answer. Remaining words are OR-ed so a partial match still
    returns something rather than nothing.
    """
    identifiers = IDENTIFIER.findall(question)
    designators = find_designators(question)
    excluded = [m.span() for m in IDENTIFIER.finditer(question)]
    excluded.extend(m.span() for m in DESIGNATOR.finditer(question))
    words = [
        match.group(0)
        for match in _QUERY_TOKEN.finditer(question)
        if match.group(0).lower() not in STOPWORDS
        and not any(start < match.end() and match.start() < end for start, end in excluded)
    ]

    parts: list[str] = []
    if identifiers:
        parts.append(" AND ".join(_escape(i) for i in identifiers))
    if designators:
        # A designator is REQUIRED, like an identifier, but matched across its
        # spellings. "coating system no. 1" and "coating system 1" are the same
        # thing, and retrieving system 4 for a question about system 1 is not a
        # missing answer - it is a confidently wrong one.
        for d in designators:
            # NOT named `variants`: that is this function's parameter, and
            # rebinding it here left it a str by the time the `words` branch
            # called `.get()` on it - AttributeError for every question that
            # carried a designator AND an ordinary word.
            spelled = " OR ".join(_escape(v) for v in designator_variants(d))
            parts.append(f"({spelled})")
    if words:
        spellings: list[str] = []
        for w in words:
            forms = (variants or {}).get(w.lower())
            if forms:
                # every spelling of a word the corpus does not contain, OR-ed
                # with the word as typed and with its prefix form. See
                # tolerant_variants - additive, never a substitution.
                spellings.extend(_escape(f) for f in forms)
                if _correctable(w):
                    spellings.append(_escape(w) + "*")
            else:
                spellings.append(_escape(w))
        ors = " OR ".join(spellings)
        parts.append(f"({ors})")
    if not parts:
        return ""
    return " AND ".join(parts)


def search(
    question: str,
    limit: int = 30,
    document_id: str | None = None,
    *,
    allowed_document_ids: frozenset[str],
    corrections: dict[str, str] | None = None,
) -> list[dict]:
    """Keyword search over retrievable chunks. bm25: lower is better.

    `allowed_document_ids` is REQUIRED and keyword-only, and has no default.
    A default would eventually come to mean "every document", which is the one
    thing this parameter exists to prevent - and it would do so silently, at
    whichever call site forgot to pass a scope.

    The restriction is applied INSIDE the SQL, before `ORDER BY ... LIMIT`.
    Filtering the returned rows instead would let an unauthorised chunk consume
    a slot in the candidate set and push an authorised one out, so the caller
    would get fewer results because of a document they are not allowed to know
    exists. Discarding results after selection is not access control.

    IDs are bound as parameters. They are never concatenated into the SQL.

    TYPO TOLERANCE (issue #85). The exact query runs first and its rows are
    kept whatever happens. Only if it comes back with fewer than
    FUZZY_MIN_HITS rows is a second, tolerant query run - the same question
    with each word the corpus does not contain OR-ed against its corpus
    spelling and its prefix form - and its rows are APPENDED to the exact
    ones. A tolerant retry can therefore only ever add passages; it cannot
    reorder or displace what the reader's own spelling found.

    `corrections`, when given, is filled in with {typed: corpus spelling} for
    whatever the retry corrected. An out-parameter, following `deduplicate`'s
    `dropped`, so the signature stays a list of hits for every caller that
    does not care what was corrected.
    """
    question = normalise_query(question)
    match = build_match_query(
        question,
        _acronym_variants(
            question, document_id, allowed_document_ids=allowed_document_ids
        ),
    )
    if not match:
        return []

    conn = connect()
    ensure_schema(conn)
    if not allowed_document_ids:
        # An empty scope is a real answer: this caller may see nothing.
        return []

    where, scope_params = _scope_clause(document_id, allowed_document_ids)

    # Exact consecutive content words are a preference, not a requirement.
    # Run them separately so a tight glossary phrase is guaranteed entry to
    # the lexical candidate list, then retain ordinary broad recall.
    phrase = build_phrase_query(question)
    hits = _run_match(conn, phrase, where, scope_params, limit) if phrase else []
    seen = {hit["chunk_id"] for hit in hits}
    for hit in _run_match(conn, match, where, scope_params, limit):
        if hit["chunk_id"] not in seen:
            seen.add(hit["chunk_id"])
            hits.append(hit)
    hits = hits[:limit]

    if len(hits) < FUZZY_MIN_HITS:
        found = spelling_corrections(
            question, document_id, allowed_document_ids=allowed_document_ids
        )
        if found:
            if corrections is not None:
                corrections.update(found)
            tolerant = build_match_query(
                question, tolerant_variants(question, found)
            )
            if tolerant and tolerant != match:
                seen = {h["chunk_id"] for h in hits}
                for hit in _run_match(
                    conn, tolerant, where, scope_params, limit
                ):
                    if hit["chunk_id"] not in seen:
                        seen.add(hit["chunk_id"])
                        hits.append(hit)
                hits = hits[:limit]

    return hits


def _scope_clause(
    document_id: str | None, allowed_document_ids: frozenset[str]
) -> tuple[str, list[object]]:
    """The WHERE tail and its bound parameters. Extracted only so the exact
    query and the tolerant retry cannot drift apart on access control."""
    params: list[object] = []
    where = "chunks_fts MATCH ?"
    if document_id:
        where += " AND document_id = ?"
        params.append(document_id)
    # SQLITE_MAX_VARIABLE_NUMBER is 32,766 here, measured; a 20-document
    # prototype is far inside it. See docs/preflight-inventory.md for the
    # note on what to do at 1,200 documents.
    marks = ",".join("?" * len(allowed_document_ids))
    where += f" AND document_id IN ({marks})"
    params.extend(sorted(allowed_document_ids))
    return where, params

def _run_match(
    conn: sqlite3.Connection,
    match: str,
    where: str,
    scope_params: list[object],
    limit: int,
) -> list[dict]:
    try:
        rows = conn.execute(
            f"""SELECT chunk_id, document_id, filename, section,
                       bm25(chunks_fts, 4.0, 2.0, 1.0) AS score
                FROM chunks_fts
                WHERE {where}
                ORDER BY score LIMIT ?""",
            [match, *scope_params, limit],
        ).fetchall()
    except sqlite3.OperationalError:
        # a malformed MATCH expression must not 500 the API
        return []

    return [
        {
            "chunk_id": r["chunk_id"],
            "document_id": r["document_id"],
            "filename": r["filename"],
            "section": r["section"] or None,
            "bm25": r["score"],
        }
        for r in rows
    ]


def _acronym_variants(
    question: str,
    document_id: str | None = None,
    *,
    allowed_document_ids: frozenset[str],
) -> dict[str, list[str]]:
    """{acronym as typed: [acronym, ...expansions the CORPUS defines]}.

    The expansion map is harvested from the documents themselves, so this can
    only add spellings the corpus actually uses - see app/acronyms.py. Imported
    lazily because acronyms.py imports this module.
    """
    from . import acronyms

    out: dict[str, list[str]] = {}
    for word in re.findall(r"[A-Za-z][\w.\-/]*", question):
        key = word.lower()
        if key in out or not acronyms.looks_like_acronym(word):
            continue
        # A multi-word expansion is kept: _escape quotes it, and a quoted
        # multi-word string is an FTS5 PHRASE query, which is exactly the
        # match wanted for "nominal dry film thickness".
        equivalents = list(
            acronyms.equivalents(
                word, document_id, allowed_document_ids=allowed_document_ids
            )
        )
        if equivalents:
            out[key] = [key, *equivalents]
    return out


def term_occurrences(
    term: str,
    document_id: str | None = None,
    *,
    allowed_document_ids: frozenset[str],
) -> int:
    """How many indexed chunks the caller may read contain this term at all.

    Zero is decisive. A question about Inconel against a corpus where Inconel
    appears nowhere needs no semantic judgement to refuse - and the semantic
    score will happily return a confident-looking passage about something else
    if it is the only thing asked. Lexical presence is the cheaper and more
    reliable first gate.

    SCOPED, AND THE SCOPE IS REQUIRED. "Decisive" is exactly why: this count
    reaching zero is what produces the user-visible refusal "none of the terms
    in this question appear in the indexed documents". Computed corpus-wide it
    answered a question about documents the caller has no grant on - a
    presence oracle, and one whose verdict is then read aloud to them. A term
    that appears only in a document they may not read must count as absent
    FOR THEM, because for them it is.
    """
    conn = connect()
    ensure_schema(conn)
    if not allowed_document_ids:
        return 0
    params: list[object] = [_escape(term)]
    where = "chunks_fts MATCH ?"
    if document_id:
        where += " AND document_id = ?"
        params.append(document_id)
    scope_sql, scope_params = _scope_predicate(allowed_document_ids)
    where += scope_sql
    params.extend(scope_params)
    try:
        return conn.execute(
            f"SELECT COUNT(*) FROM chunks_fts WHERE {where}", params
        ).fetchone()[0]
    except sqlite3.OperationalError:
        # a term FTS cannot parse tells us nothing either way
        return -1
