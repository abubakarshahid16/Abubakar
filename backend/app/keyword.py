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


def build_match_query(question: str) -> str:
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
            variants = " OR ".join(_escape(v) for v in designator_variants(d))
            parts.append(f"({variants})")
    if words:
        ors = " OR ".join(_escape(w) for w in words)
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
    """
    match = build_match_query(question)
    if not match:
        return []

    conn = connect()
    ensure_schema(conn)
    if not allowed_document_ids:
        # An empty scope is a real answer: this caller may see nothing.
        return []

    params: list[object] = [match]
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
    params.append(limit)

    def run_match(expression: str) -> list[sqlite3.Row]:
        query_params = [expression, *params[1:]]
        return conn.execute(
            f"""SELECT chunk_id, document_id, filename, section,
                       bm25(chunks_fts, 4.0, 2.0, 1.0) AS score
                FROM chunks_fts
                WHERE {where}
                ORDER BY score LIMIT ?""",
            query_params,
        ).fetchall()

    try:
        # Exact consecutive content words are a preference, not a requirement.
        # Run them separately so a tight glossary phrase is guaranteed entry
        # to the lexical candidate list, then retain ordinary broad recall.
        phrase_match = build_phrase_query(question)
        phrase_rows = run_match(phrase_match) if phrase_match else []
        broad_rows = run_match(match)
    except sqlite3.OperationalError:
        # a malformed MATCH expression must not 500 the API
        return []

    seen: set[str] = set()
    rows = []
    for row in [*phrase_rows, *broad_rows]:
        if row["chunk_id"] not in seen:
            seen.add(row["chunk_id"])
            rows.append(row)
        if len(rows) == limit:
            break

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
