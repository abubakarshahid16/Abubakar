#!/usr/bin/env python3
"""Measure how often a chunk's stored ``section`` label is the section that is
actually in force at that point in the document.

WHY THIS FILE EXISTS
====================
The project has been reporting "section citation mismatch" figures -- "doc16
went from 11 to 4", "the corpus went from 81% to 78%" -- as headline quality
metrics.  No code in the repository measured them.  They entered the history
through a commit message (95650b7) that asserts "Measured, not estimated" and
committed no measurement, so the numbers could not be reproduced, checked, or
regenerated after a chunker change.  This script is the missing measurement.
Its output is allowed to disagree with those figures; a disagreement is a
result, not a bug.

WHAT "MISMATCH" MEANS HERE
==========================
No shared definition existed, so one is fixed here and used for every
document.  The unit of measurement is a **chunk** (rows of the ``chunks``
table, which are the blocks the chunker emitted and the things a citation
points at).  For a chunk, ``truth`` is the deepest section, drawn from the
document's own table of contents, whose start page is at or before the
chunk's ``page_start``.  ``assigned`` is the clause number off the front of
``chunks.section``.  Each measured chunk gets exactly one verdict:

  CORRECT
      ``assigned`` is the section in force.  Counts as correct.

  AMBIGUOUS
      The ground truth is PAGE-granular -- a contents page gives a section's
      start page, never the line it starts on -- and on some pages that is
      not enough to decide.  Two cases, both undecidable rather than wrong:

        * The chunk sits on the first page of the section in force and is
          labelled with the immediately preceding section.  Text above a
          heading genuinely belongs to the previous section; the chunker's
          own flush order depends on it (chunker.py, ``flush_prose`` is
          called with the section in force *before* the heading reassigns
          it).
        * Several sections start on the chunk's page -- a specification page
          carrying clauses 4.1 through 4.5 -- and the chunk is labelled with
          one of them.  Any of those labels can be right for a block on that
          page, and nothing at page granularity can say which.

      Counting these as wrong would manufacture failures out of the
      measurement's own resolution.  They are NOT counted as wrong and NOT
      counted as correct: excluded from the headline denominator, and always
      printed, because a large AMBIGUOUS count means the headline rests on
      far fewer blocks than the document contains.

  COARSE_PARENT
      ``assigned`` is a proper ancestor of ``truth`` -- it names 4.4 where
      4.4.2 is in force.  A reader sent to clause 4.4 lands within a few
      hundred words of the right text.  This IS counted as wrong, because a
      citation that names a parent clause is not the clause the answer came
      from and an engineer checking it will not find the sentence.  It is
      reported as its own column and never silently merged with FABRICATED:
      the two failures have completely different severity and a single number
      that hides the split is not honest.

  WRONG_SECTION
      ``assigned`` is a real section of this document, but a different one --
      not an ancestor, not a descendant.  Counted as wrong.  This is the
      severe case: the citation is confidently and specifically incorrect.

  FABRICATED
      ``assigned`` is not any real section of this document: it appears
      neither in the table of contents nor as a validated heading line
      anywhere in the document text.  Counted as wrong, and the worst case.

  REFINEMENT
      ``assigned`` is a proper *descendant* of ``truth`` -- it names 4.4.2
      where the table of contents only goes as deep as 4.  This is consistent
      with the ground truth but not confirmed by it, because the contents
      page never listed the subsection.  It is NOT counted as correct and NOT
      counted as wrong; it is excluded from the headline denominator and
      reported separately.  Calling it correct would inflate the score with
      labels the ground truth cannot actually check.

  NO_LABEL
      ``chunks.section`` is NULL.  A missing citation is a different defect
      from a wrong one -- the UI shows no clause at all rather than the wrong
      clause -- so it is counted and reported but excluded from the headline
      denominator.  Its size matters: a document can reach a high "percentage
      correct" by labelling almost nothing.

  UNNUMBERED
      ``chunks.section`` exists but carries no leading clause number, so
      there is no number to compare.  Counted, excluded from the denominator.

  NO_GROUND_TRUTH
      The chunk lies outside the page range the contents page covers, or
      inside a region the contents page names but does not number -- a
      foreword, an annex listed as "Annex B (Informative) Colours 20" with no
      clause numbering behind it.  Excluded.  This verdict is load-bearing:
      before unnumbered regions were parsed, the last numbered clause
      appeared to run to the end of the document, and every chunk in NORSOK's
      Annex A was reported as a mismatch against clause 11.  Fourteen false
      failures out of a twenty-page standard, from one unparsed line.

Only the clause NUMBER is compared, never the heading title.  Comparing
"1.1 Definitions and Terminology" as a string would measure title extraction
and page-furniture stripping at the same time, and a single number that mixes
three defects tells you which one to fix: none of them.

THE HEADLINE NUMBER
-------------------
    percentage correct = CORRECT / (CORRECT + COARSE_PARENT + WRONG_SECTION
                                    + FABRICATED)

That is: of the chunks where a machine-readable contents page can actually
adjudicate the label, what fraction is exactly right.  AMBIGUOUS, REFINEMENT,
NO_LABEL and NO_GROUND_TRUTH are outside the denominator and are printed
beside it so the denominator can be seen.

DOCUMENTS WITHOUT GROUND TRUTH
==============================
Ground truth is derived from the document itself, never hand-built.  A
document qualifies only if:

  1. ``chunker.classify_page`` finds at least one page it calls ``toc``, and
  2. that page yields parseable ``number / title / printed-page`` entries, and
  3. the printed-page-to-PDF-page offset can be derived AND corroborated.

A document failing any of these is reported as "no ground truth available"
and contributes nothing -- not a zero, not an estimate -- to the corpus
total.  Reporting six documents honestly is worth more than reporting twelve
wrongly.

THE PAGE OFFSET
===============
A contents page says "3.2 Nonlinear Models 94"; 94 is the number printed on
the paper, and the same text is on PDF page 115.  Every entry is useless
until that offset is known, and the offset is a property of the document, not
a constant.  Two independent derivations are run:

  * RUNNING-HEADER method.  The top and bottom lines of each page are scanned
    for a printed folio ("Page 34 of 46", or a bare number sitting alone).
    Each page votes ``pdf_page - printed_page``; the modal vote wins.

  * TOC-TITLE method.  For each contents entry, the document is searched for
    pages whose text opens a line with that entry's title.  An entry may hit
    several pages, so every offset an entry allows is pooled and the offset
    the most ENTRIES agree on wins -- one stray early match cannot outvote
    the body of the document.

Both reject impossible offsets before voting (negative, or past half the
document), so a document with no usable folios reports "undetermined" instead
of electing noise.

The script reports the offset, which method produced it, how many votes
agreed out of how many were cast, and -- when both methods produced an answer
-- whether they agree.  Two independent derivations landing on the same
integer is the verification.  If neither method reaches the confidence floor
(``--min-offset-votes``, default 3, and at least 60% of votes agreeing), the
document is reported UNMEASURABLE rather than measured against a guessed
offset.

DATABASE ACCESS
===============
Strictly read-only: the connection is opened with ``mode=ro`` on a file: URI,
so SQLite itself refuses a write.  Nothing in this file issues INSERT, UPDATE
or DELETE.

HOW TO RUN IT
=============
``backend/app/config.py`` builds ``db_path`` from ``BACKEND_DIR`` (line 17),
which is derived from ``__file__`` and is therefore correct no matter where
you invoke Python from.  Line 9's ``env_file=".env"`` is NOT: it is a bare
relative name, so pydantic-settings resolves it against the *current working
directory*.  Run from the repository root and ``backend/.env`` is never read;
run from ``backend/`` and it is.  If a ``.env`` overrides ``db_path``, the two
invocations therefore audit different databases.

    # Recommended -- reads backend/.env exactly as the application does:
    cd backend && python ../scripts/section_audit.py

    # From the repo root; config still resolves db_path from BACKEND_DIR,
    # but backend/.env is NOT applied:
    python scripts/section_audit.py

    # No import of the app at all:
    python scripts/section_audit.py --db backend/data/rag_intelligence.sqlite

If the database lives on a network or virtualised mount, SQLite can raise
"disk I/O error" on open.  Copy the file to local disk and point ``--db`` at
the copy; this script never writes, so a copy is a faithful subject.

No absolute path appears anywhere in this file.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------- verdicts

CORRECT = "CORRECT"
AMBIGUOUS = "AMBIGUOUS"
COARSE_PARENT = "COARSE_PARENT"
WRONG_SECTION = "WRONG_SECTION"
FABRICATED = "FABRICATED"
REFINEMENT = "REFINEMENT"
NO_LABEL = "NO_LABEL"
UNNUMBERED = "UNNUMBERED"
NO_GROUND_TRUTH = "NO_GROUND_TRUTH"

#: The verdicts that form the headline denominator, in report order.
SCORED = (CORRECT, COARSE_PARENT, WRONG_SECTION, FABRICATED)
#: Counted and shown, deliberately outside the denominator.
UNSCORED = (AMBIGUOUS, REFINEMENT, NO_LABEL, UNNUMBERED, NO_GROUND_TRUTH)
ALL_VERDICTS = SCORED + UNSCORED

# ------------------------------------------------------- TOC line patterns

#: "1.0 - ALL DISCIPLINES.......... 29"  (leader dots or wide gap)
_TOC_LEADERS = re.compile(
    r"^((?:[A-Z]\.)?\d+(?:\.\d+){0,3})\s*[-‐-―:.]?\s+(\S.*?)[\s.·_]{2,}(\d{1,4})$"
)
#: "5.3.1 Identity Theft 257"  (single space before the folio)
_TOC_PLAIN = re.compile(
    r"^((?:[A-Z]\.)?\d+(?:\.\d+){0,3})\s*[-‐-―:.]?\s+(\S.*?)\s+(\d{1,4})$"
)
#: A clause number alone on its line -- the left column of a three-column TOC.
_TOC_NUMBER_ONLY = re.compile(r"^((?:[A-Z]\.)?\d+(?:\.\d+){0,3})\.?$")
_BARE_NUMBER = re.compile(r"^(\d{1,4})$")
#: A contents entry with NO clause number: "Annex A (Normative) Coating
#: systems .... 15", "Foreword  2", "APPENDIX B ... 405".  These matter as
#: much as the numbered ones: an unnumbered entry marks a REGION the numbered
#: ground truth does not describe, and ignoring it makes the last numbered
#: clause appear to run to the end of the document.  That single omission was
#: enough to report every chunk in NORSOK's Annex A as a mismatch against
#: clause 11 -- fourteen fabricated failures out of a 20-page standard.
_TOC_UNNUMBERED = re.compile(r"^([A-Za-z(].*?)[\s.·_]{2,}(\d{1,4})$")
#: "Annex A", "Appendix B", "ANNEX C (Normative)" -- an unnumbered entry that
#: nonetheless names a lettered division, which IS a clause number namespace.
_ANNEX = re.compile(r"(?i)^(?:annex|appendix)\s+([A-Z])\b")

#: A printed folio in a running header or footer.
_FOLIO_OF = re.compile(r"(?i)\bpage\s+(\d{1,4})\s+of\s+\d{1,4}\b")
_FOLIO_BARE = re.compile(r"^(\d{1,4})$")

_LETTERS = re.compile(r"[A-Za-z]")
_WS = re.compile(r"\s+")

#: How many lines at each edge of a page count as running header/footer.
#: Matches ``settings.running_line_scan_lines`` (5) so "the edge of a page"
#: means the same thing here as it does in the chunker.
_EDGE_LINES = 5


def _norm_title(s: str) -> str:
    return _WS.sub(" ", s).strip(" .·_-–—").lower()


def clause_number_of(label: str) -> str | None:
    """The clause number off the front of a stored ``chunks.section`` label.

    The chunker stores the whole heading -- "1.1 Definitions and Terminology"
    -- and the number is the first token.  Comparing whole heading strings
    would measure title extraction, not section attribution, so only the
    number is compared.  A label with no leading clause number (an ALL-CAPS
    heading, say) has nothing this audit can adjudicate.
    """
    head = label.strip().split(" ", 1)[0].rstrip(".")
    if _TOC_NUMBER_ONLY.match(head):
        return head
    return None


def _norm_number(number: str) -> str:
    """Canonical clause number.

    "4.0" and "4" are the same section written two ways -- a contents page
    that lists "4.0 ARCHITECTURAL" and a body heading "4.1 GENERAL" are using
    one numbering scheme.  Trailing zero segments are dropped so ancestry
    comparisons work.  A number that is only zeros normalises to "0".
    """
    parts = number.split(".")
    while len(parts) > 1 and parts[-1] in ("0", "00"):
        parts.pop()
    return ".".join(parts)


def _parts(number: str) -> tuple[str, ...]:
    return tuple(_norm_number(number).split("."))


def _is_ancestor(a: str, b: str) -> bool:
    """Is ``a`` a PROPER ancestor of ``b``?  4.4 is an ancestor of 4.4.2."""
    pa, pb = _parts(a), _parts(b)
    return len(pa) < len(pb) and pb[: len(pa)] == pa


# ------------------------------------------------------------- data model


@dataclass
class TocEntry:
    #: None for an entry that carries no clause number at all ("Foreword",
    #: "CHAPTER TWO  THE FUNDAMENTALS").  Such an entry still fixes where a
    #: region of the document begins, and chunks inside a region the numbered
    #: scheme does not name are reported NO_GROUND_TRUTH rather than judged.
    number: str | None
    title: str
    printed_page: int


@dataclass
class Offset:
    value: int | None
    method: str
    votes_for: int
    votes_total: int
    cross_check: str

    @property
    def agreement(self) -> float:
        return self.votes_for / self.votes_total if self.votes_total else 0.0


@dataclass
class DocResult:
    document_id: str
    filename: str
    page_count: int
    chunk_count: int
    measurable: bool
    reason: str = ""
    toc_pages: list[int] = field(default_factory=list)
    toc_entries: int = 0
    toc_regions: int = 0
    offset: Offset | None = None
    verdicts: Counter = field(default_factory=Counter)
    examples: list[dict] = field(default_factory=list)

    @property
    def denominator(self) -> int:
        return sum(self.verdicts[v] for v in SCORED)

    @property
    def pct_correct(self) -> float | None:
        d = self.denominator
        return 100.0 * self.verdicts[CORRECT] / d if d else None


# ------------------------------------------------------------- TOC parsing


def parse_toc_page(text: str) -> list[TocEntry]:
    """Pull ``number / title / printed page`` triples out of one contents page.

    Two layouts are handled, because both occur in this corpus:

      * one line per entry, with leader dots or a wide gap before the folio
        (doc16's Part 3 contents);
      * three lines per entry -- number, title, folio -- which is how a
        two-column contents page extracts to text (book2's contents).
    """
    entries: list[TocEntry] = []
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    i = 0
    while i < len(lines):
        line = lines[i]
        m = _TOC_LEADERS.match(line) or _TOC_PLAIN.match(line)
        if m and _LETTERS.search(m.group(2)):
            entries.append(TocEntry(m.group(1), _norm_title(m.group(2)), int(m.group(3))))
            i += 1
            continue
        m = _TOC_NUMBER_ONLY.match(line)
        if m and i + 2 < len(lines):
            title, folio = lines[i + 1], lines[i + 2]
            if (
                _BARE_NUMBER.match(folio)
                and _LETTERS.search(title)
                and not _BARE_NUMBER.match(title)
            ):
                entries.append(TocEntry(m.group(1), _norm_title(title), int(folio)))
                i += 3
                continue
        m = _TOC_UNNUMBERED.match(line)
        if m and _LETTERS.search(m.group(1)) and not _TOC_NUMBER_ONLY.match(m.group(1).strip()):
            title = _norm_title(m.group(1))
            annex = _ANNEX.match(title)
            entries.append(
                TocEntry(annex.group(1).upper() if annex else None, title, int(m.group(2)))
            )
            i += 1
            continue
        # Two-line unnumbered form -- the same layout that splits a numbered
        # entry across three lines splits an unnumbered one across two:
        #     'Annex A (Normative) Coating systems '
        #     '15'
        if (
            i + 1 < len(lines)
            and _LETTERS.search(line)
            and not _BARE_NUMBER.match(line)
            and not _TOC_NUMBER_ONLY.match(line)
            and _BARE_NUMBER.match(lines[i + 1])
        ):
            title = _norm_title(line)
            annex = _ANNEX.match(title)
            entries.append(
                TocEntry(
                    annex.group(1).upper() if annex else None, title, int(lines[i + 1])
                )
            )
            i += 2
            continue
        i += 1
    return entries


def dedupe_toc(entries: list[TocEntry]) -> list[TocEntry]:
    """Keep the FIRST occurrence of each clause number.

    A contents page can list a number twice (a part contents repeating a
    chapter line).  The first listing is the one whose folio is the section's
    start.
    """
    seen: set[str] = set()
    out: list[TocEntry] = []
    for e in entries:
        if e.number is None:
            out.append(e)  # regions are keyed by position, not by number
            continue
        key = _norm_number(e.number)
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


def numbered(entries: list[TocEntry]) -> list[TocEntry]:
    return [e for e in entries if e.number is not None]


def keep_monotone(entries: list[TocEntry], page_count: int) -> tuple[list[TocEntry], int]:
    """Keep the largest set of entries whose folios never go backwards.

    A contents page lists the document in order, so its folios are
    non-decreasing down the page and across its pages.  Anything that goes
    backwards was not a contents entry: a stray body line that happened to
    match, a cross-reference, a column that extracted out of sequence.

    This is the gate that separates a real contents page from a page the
    classifier merely called one.  book4's front matter classifies as 29
    'toc' pages and parses into 127 numbered entries with folios running to
    2007 in a 1,400-page PDF -- shuffled, impossible, and enough to produce a
    confident, meaningless percentage.  After this filter almost nothing
    survives, and the document is correctly reported as having no ground
    truth.  Returns (kept, dropped_count).
    """
    usable = [e for e in entries if 0 < e.printed_page <= page_count]
    dropped = len(entries) - len(usable)
    if not usable:
        return [], dropped

    # The kept set is the LONGEST non-decreasing run, not a greedy scan from
    # the top.  A greedy scan is order-sensitive: one junk line near the start
    # carrying a high folio raises the running maximum and discards every
    # genuine entry after it, which is exactly how doc16's eight real Part 3
    # entries were thrown away by a single stray header line.
    n = len(usable)
    best = [1] * n
    prev = [-1] * n
    for i in range(n):
        for j in range(i):
            if usable[j].printed_page <= usable[i].printed_page and best[j] + 1 > best[i]:
                best[i] = best[j] + 1
                prev[i] = j
    end = max(range(n), key=lambda i: best[i])
    chain: list[TocEntry] = []
    while end != -1:
        chain.append(usable[end])
        end = prev[end]
    chain.reverse()
    return chain, dropped + (n - len(chain))


# ------------------------------------------------------------ page offset


def _edge_lines(text: str) -> list[str]:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) <= 2 * _EDGE_LINES:
        return lines
    return lines[:_EDGE_LINES] + lines[-_EDGE_LINES:]


def _plausible_offset(offset: int, page_count: int) -> bool:
    """Reject offsets no real document could have.

    A printed folio never precedes its own PDF page, so the offset is never
    negative; and front matter is a preamble, not the bulk of a book, so an
    offset past half the document is a matching accident (a chapter number
    read as a folio, an equation number at a page edge) rather than a
    pagination.  Both bounds exist to stop noise from winning a vote in a
    document that has no usable folios at all -- which must be reported as
    unmeasurable, not measured against a wrong offset.
    """
    return 0 <= offset <= max(30, page_count // 2)


def offset_from_running_header(pages: dict[int, str]) -> tuple[Counter, int]:
    """Vote on ``pdf_page - printed_page`` from printed folios.

    "Page 34 of 46" is unambiguous and is preferred.  A bare number alone on
    an edge line is accepted only when no "Page N of M" folio exists anywhere
    in the document, because a bare number at the edge of a body page is just
    as often a clause number or an equation number.
    """
    votes: Counter = Counter()
    cast = 0
    explicit = {
        p: int(m.group(1))
        for p, t in pages.items()
        for m in [_FOLIO_OF.search(t)]
        if m
    }
    n = len(pages)
    if explicit:
        for pdf, printed in explicit.items():
            cast += 1
            if _plausible_offset(pdf - printed, n):
                votes[pdf - printed] += 1
        return votes, cast
    for pdf, text in pages.items():
        for line in _edge_lines(text):
            m = _FOLIO_BARE.match(line)
            if m:
                cast += 1
                if _plausible_offset(pdf - int(m.group(1)), n):
                    votes[pdf - int(m.group(1))] += 1
                break
    return votes, cast


def offset_from_toc_titles(
    pages: dict[int, str], entries: list[TocEntry], toc_pages: set[int]
) -> tuple[Counter, int]:
    """Vote on the offset by finding where each contents title really sits.

    A title is matched only when it opens a line (optionally after its own
    clause number), which keeps a passing mention in body prose from voting.
    """
    votes: Counter = Counter()
    cast = 0
    prepared = {
        pdf: [_norm_title(ln) for ln in text.splitlines() if ln.strip()]
        for pdf, text in pages.items()
        if pdf not in toc_pages
    }
    # Two passes.  A title can appear on several pages (a chapter opener, a
    # cross-reference, a running head), so pass one collects every candidate
    # offset an entry allows and pass two lets the entries that agree decide.
    # Taking the first hit per entry instead lets one stray early match --
    # a title quoted in a preface -- outvote the body of the document.
    candidates: list[set[int]] = []
    for e in entries:
        if len(e.title) < 6:
            continue
        prefixes = [e.title]
        if e.number is not None:
            prefixes.append(f"{_norm_number(e.number)} {e.title}")
            prefixes.append(f"{e.number.lower()} {e.title}")
        offsets = {
            pdf - e.printed_page
            for pdf, lines in prepared.items()
            for ln in lines
            if any(ln.startswith(p) for p in prefixes)
        }
        offsets = {o for o in offsets if _plausible_offset(o, len(pages))}
        if offsets:
            candidates.append(offsets)
    pool: Counter = Counter()
    for offsets in candidates:
        pool.update(offsets)
    if not pool:
        return votes, 0
    winner = pool.most_common(1)[0][0]
    cast = len(candidates)
    votes[winner] = sum(1 for offsets in candidates if winner in offsets)
    return votes, cast


def derive_offset(
    pages: dict[int, str],
    entries: list[TocEntry],
    toc_pages: set[int],
    min_votes: int,
    min_agreement: float,
) -> Offset:
    """Derive the printed-to-PDF offset and say how it was verified."""
    header_votes, header_cast = offset_from_running_header(pages)
    title_votes, title_cast = offset_from_toc_titles(pages, entries, toc_pages)

    def best(votes: Counter, cast: int) -> tuple[int | None, int, int]:
        if not votes:
            return None, 0, cast
        value, n = votes.most_common(1)[0]
        return value, n, cast

    h_val, h_for, h_cast = best(header_votes, header_cast)
    t_val, t_for, t_cast = best(title_votes, title_cast)

    def ok(val, n, cast):
        return val is not None and n >= min_votes and cast and n / cast >= min_agreement

    h_ok, t_ok = ok(h_val, h_for, h_cast), ok(t_val, t_for, t_cast)

    if h_ok and t_ok and h_val == t_val:
        return Offset(
            h_val,
            "running-header + TOC-title (independent, agree)",
            h_for + t_for,
            h_cast + t_cast,
            f"both methods returned {h_val:+d}",
        )
    if h_ok and t_ok and h_val != t_val:
        # Two credible derivations disagreeing is exactly the situation where
        # picking one would manufacture a number.  Prefer the TOC-title
        # method -- it is the one tied to the entries being measured -- and
        # say loudly that the check failed.
        return Offset(
            t_val,
            "TOC-title (running-header DISAGREED)",
            t_for,
            t_cast,
            f"running-header said {h_val:+d}, TOC-title said {t_val:+d}",
        )
    if t_ok:
        return Offset(t_val, "TOC-title", t_for, t_cast, "running-header method inconclusive")
    if h_ok:
        return Offset(
            h_val, "running-header", h_for, h_cast, "TOC-title method inconclusive"
        )
    return Offset(
        None,
        "none",
        max(h_for, t_for),
        h_cast + t_cast,
        f"header best {h_val!r} ({h_for}/{h_cast}), title best {t_val!r} ({t_for}/{t_cast})",
    )


# ------------------------------------------------------------ ground truth


def build_truth_map(entries: list[TocEntry], offset: int) -> list[tuple[int, str | None]]:
    """(pdf_start_page, clause_number-or-None), sorted.

    At an equal start page the DEEPEST numbered section wins and an
    unnumbered region loses: a contents page that lists "CHAPTER TWO  THE
    FUNDAMENTALS  7" immediately above "2.1  REQUIREMENTS AND CONTROLS  7" is
    naming the same place twice, and 2.1 is the more specific truth.
    """
    rows = [
        (e.printed_page + offset, None if e.number is None else _norm_number(e.number))
        for e in entries
    ]
    rows.sort(key=lambda r: (r[0], 0 if r[1] is None else len(_parts(r[1]))))
    return rows


def truth_at(
    truth: list[tuple[int, str | None]], page: int
) -> tuple[str | None, int | None]:
    """Section in force at ``page``, and its start page.

    A None number means "inside a region the numbered scheme does not
    describe" -- an annex with no clause numbering, a foreword.  The caller
    must report those chunks as NO_GROUND_TRUTH, never judge them: judging
    them against the last numbered clause before the region is what turned
    NORSOK's whole Annex A into fourteen false mismatches against clause 11.
    """
    best_num, best_start = None, None
    for start, num in truth:
        if start <= page:
            best_num, best_start = num, start
        else:
            break
    return best_num, best_start


def previous_section(truth: list[tuple[int, str | None]], start_page: int) -> str | None:
    prev = None
    for start, num in truth:
        if start < start_page:
            prev = num
        else:
            break
    return prev


def admissible_at(truth: list[tuple[int, str | None]], page: int) -> set[str]:
    """Every section label that page-granular truth cannot rule out on ``page``.

    That is: every section STARTING on this page (a specification page often
    starts five clauses), plus the section that was in force on the way in.
    A block on such a page may legitimately carry any of them.
    """
    starting = {num for start, num in truth if start == page and num is not None}
    out = set(starting)
    if starting:
        prev = previous_section(truth, page)
        if prev is not None:
            out.add(prev)
    return out


def real_section_numbers(
    pages: dict[int, str], entries: list[TocEntry], toc_pages: set[int]
) -> set[str]:
    """Every clause number this document genuinely has.

    The union of the contents page and every heading the chunker's own
    detector validates in the body.  A document's real structure is usually
    deeper than its contents page, so judging FABRICATED on the contents page
    alone would libel correct labels for unlisted subsections.
    """
    real = {_norm_number(e.number) for e in numbered(entries)}
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
        from app.chunker import _split_line_heading, looks_like_heading  # type: ignore
    except Exception:
        return real
    for pdf, text in pages.items():
        if pdf in toc_pages:
            continue
        lines = [ln.strip() for ln in text.splitlines()]
        i = 0
        while i < len(lines):
            head = looks_like_heading(lines[i])
            consumed = 1
            if head is None:
                head, consumed = _split_line_heading(lines, i)
            if head:
                real.add(_norm_number(head.split(" ", 1)[0]))
            i += max(consumed, 1)
    return real


def classify_chunk(
    assigned: str | None,
    page_start: int,
    truth: list[tuple[int, str]],
    real: set[str],
    coverage: tuple[int, int],
) -> str:
    lo, hi = coverage
    if assigned is None:
        return NO_LABEL
    number = clause_number_of(assigned)
    if number is None:
        return UNNUMBERED
    if not (lo <= page_start <= hi):
        return NO_GROUND_TRUTH
    true_num, true_start = truth_at(truth, page_start)
    if true_num is None:
        return NO_GROUND_TRUTH
    a = _norm_number(number)
    if a == true_num:
        return CORRECT
    # Page-granular truth cannot adjudicate a label that is one of the
    # sections starting on this page, nor the section in force on the way in.
    if a in admissible_at(truth, page_start):
        return AMBIGUOUS
    if _is_ancestor(a, true_num):
        return COARSE_PARENT
    if _is_ancestor(true_num, a):
        return REFINEMENT
    if a not in real:
        return FABRICATED
    return WRONG_SECTION


# ------------------------------------------------------------------ audit


def audit_document(
    conn: sqlite3.Connection, row: sqlite3.Row, args: argparse.Namespace
) -> DocResult:
    from app.chunker import classify_page  # imported lazily; see resolve_backend

    did, filename = row["id"], row["filename"]
    pages = {
        p: t
        for p, t in conn.execute(
            "SELECT page_no, text FROM pages WHERE document_id = ? ORDER BY page_no",
            (did,),
        )
    }
    chunks = list(
        conn.execute(
            "SELECT section, page_start FROM chunks WHERE document_id = ? ORDER BY ordinal",
            (did,),
        )
    )
    res = DocResult(did, filename, len(pages), len(chunks), measurable=False)
    if not pages:
        res.reason = "no extracted pages in the database"
        return res

    total = len(pages)
    kinds = {p: classify_page(t, p, total) for p, t in pages.items()}
    toc_pages = {p for p, k in kinds.items() if k == "toc"}
    res.toc_pages = sorted(toc_pages)
    if not toc_pages:
        res.reason = "classify_page found no 'toc' page -- no machine-readable contents"
        return res

    entries: list[TocEntry] = []
    for p in sorted(toc_pages):
        entries += parse_toc_page(pages[p])
    parsed = len(entries)
    entries, dropped = keep_monotone(entries, total)
    entries = dedupe_toc(entries)
    if parsed and dropped / parsed > args.max_disordered:
        res.reason = (
            f"contents page(s) {res.toc_pages} are not a usable contents listing: "
            f"{dropped} of {parsed} entries have folios that go backwards or exceed "
            f"the {total}-page document (limit {args.max_disordered:.0%})"
        )
        return res
    res.toc_entries = len(numbered(entries))
    res.toc_regions = len(entries) - res.toc_entries
    if res.toc_entries < args.min_toc_entries:
        res.reason = (
            f"contents page(s) {res.toc_pages} yielded {res.toc_entries} parseable "
            f"NUMBERED entries, below the floor of {args.min_toc_entries}"
        )
        return res

    off = derive_offset(pages, entries, toc_pages, args.min_offset_votes, args.min_agreement)
    res.offset = off
    if off.value is None:
        res.reason = f"printed-to-PDF page offset could not be derived ({off.cross_check})"
        return res

    truth = build_truth_map(entries, off.value)
    lo = min(s for s, n in truth if n is not None)
    hi = max(pages)
    real = real_section_numbers(pages, entries, toc_pages)

    for ch in chunks:
        verdict = classify_chunk(ch["section"], ch["page_start"], truth, real, (lo, hi))
        res.verdicts[verdict] += 1
        if verdict in (FABRICATED, WRONG_SECTION, COARSE_PARENT) and len(res.examples) < 12:
            tn, _ = truth_at(truth, ch["page_start"])
            res.examples.append(
                {
                    "verdict": verdict,
                    "pdf_page": ch["page_start"],
                    "assigned": ch["section"],
                    "in_force": tn,
                }
            )
    if res.denominator == 0:
        # A percentage over nothing is not a small result, it is no result.
        res.verdicts.clear()
        res.reason = (
            "the contents page parsed and the offset resolved, but NO chunk fell "
            "somewhere the contents page can adjudicate (every chunk is unlabelled, "
            "outside the covered pages, or inside an unnumbered region)"
        )
        return res
    res.measurable = True
    return res


# ------------------------------------------------------------- db & config


def resolve_backend() -> Path | None:
    backend = Path(__file__).resolve().parent.parent / "backend"
    if backend.is_dir():
        sys.path.insert(0, str(backend))
        return backend
    return None


def resolve_db(explicit: str | None) -> tuple[Path, str]:
    if explicit:
        return Path(explicit).expanduser(), "--db flag"
    try:
        from app.config import settings  # type: ignore

        return Path(settings.db_path), "backend/app/config.py settings.db_path"
    except Exception as exc:  # pragma: no cover - depends on the environment
        raise SystemExit(
            f"Could not import backend/app/config.py ({exc.__class__.__name__}: {exc}).\n"
            "Pass the database explicitly, e.g.:\n"
            "    python scripts/section_audit.py --db backend/data/rag_intelligence.sqlite"
        ) from exc


def open_readonly(db: Path) -> sqlite3.Connection:
    """Open READ-ONLY.  mode=ro makes SQLite itself refuse any write."""
    if not db.exists():
        raise SystemExit(f"Database not found: {db}")
    uri = f"file:{db.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


# ----------------------------------------------------------------- output

_HEADERS = ["document", "filename", "chunks", "meas.", "corr", "coarse", "wrong", "fabr",
            "ambig", "refine", "nolabel", "unnum", "outside", "% correct"]


def render_table(results: list[DocResult]) -> str:
    rows = []
    for r in results:
        if not r.measurable:
            rows.append([r.document_id, r.filename, str(r.chunk_count),
                         "-", "-", "-", "-", "-", "-", "-", "-", "-", "-",
                         "NO GROUND TRUTH"])
            continue
        v = r.verdicts
        pct = r.pct_correct
        rows.append([
            r.document_id, r.filename, str(r.chunk_count), str(r.denominator),
            str(v[CORRECT]), str(v[COARSE_PARENT]), str(v[WRONG_SECTION]),
            str(v[FABRICATED]), str(v[AMBIGUOUS]), str(v[REFINEMENT]),
            str(v[NO_LABEL]), str(v[UNNUMBERED]), str(v[NO_GROUND_TRUTH]),
            f"{pct:.1f}%" if pct is not None else "n/a",
        ])
    widths = [max(len(_HEADERS[i]), *(len(r[i]) for r in rows)) if rows else len(_HEADERS[i])
              for i in range(len(_HEADERS))]
    def line(cells):
        return "  ".join(c.ljust(w) if i < 2 else c.rjust(w)
                         for i, (c, w) in enumerate(zip(cells, widths)))
    out = [line(_HEADERS), "  ".join("-" * w for w in widths)]
    out += [line(r) for r in rows]
    return "\n".join(out)


HOW_TO_READ = """\
HOW TO READ THIS OUTPUT
=======================
The percentage is one narrow thing: of the chunks whose label a machine-
readable contents page in that document can actually adjudicate, the share
whose clause number is exactly the clause in force on that page.

What it DOES prove
  * That the figure is reproducible.  Re-run this script and you get the same
    number; change the chunker and the number moves.  It is derived from the
    database and the documents' own contents pages, with no hand-built key
    and no judgement call at measurement time.
  * That a labelled chunk with a clearly wrong clause number is being counted
    as wrong, split by severity: COARSE_PARENT (right area, wrong precision),
    WRONG_SECTION (a different real clause), FABRICATED (a clause the document
    does not have).

What it does NOT prove
  * It is not answer quality.  A chunk with a perfect section label can still
    be the wrong passage to answer a question, and a NO_LABEL chunk can be
    exactly right.
  * The truth is PAGE-GRANULAR.  A contents page gives a section's start page,
    not the line it starts on.  Every chunk on a section's first page is
    therefore undecidable, which is why AMBIGUOUS exists and why it is
    excluded rather than guessed.  A document whose sections start mid-page
    will have a large AMBIGUOUS count and a correspondingly small denominator.
  * REFINEMENT chunks -- a label deeper than the contents page goes -- are
    consistent with the truth and unconfirmed by it.  They are excluded, not
    credited.  A document with a shallow contents page (chapters only) will
    push most of its chunks into REFINEMENT, and its percentage is then based
    on very few blocks.  Always read '% correct' next to 'meas.'.
  * NO_LABEL is excluded.  A document that labels almost nothing can score
    100%.  Read the nolabel column before believing a high percentage.
  * FABRICATED counts are checked against the document's real headings, not
    only against its contents page.  A zero in that column means the chunker
    is not inventing clause numbers -- it is not evidence that the labels are
    right.  The observed failure is a STALE label carried across a boundary,
    which lands in WRONG_SECTION.
  * Documents marked NO GROUND TRUTH are not evidence of anything, good or
    bad.  They are unmeasured.  The corpus total covers ONLY the measurable
    documents and states which they are.
  * The corpus total is chunk-weighted, so a 2,000-chunk textbook moves it far
    more than an 80-chunk specification.  It is not the mean of the per-
    document percentages, and the two will differ.
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Measure section-label correctness against each document's own "
                    "table of contents.  Read-only.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Run from backend/ so that backend/.env applies:  "
               "cd backend && python ../scripts/section_audit.py",
    )
    ap.add_argument("--db", help="Path to rag_intelligence.sqlite. Default: settings.db_path "
                                 "from backend/app/config.py.")
    ap.add_argument("--document", help="Audit one document: its id, or a substring "
                                       "of its filename (e.g. doc16, book2).")
    ap.add_argument("--json", action="store_true", help="Machine-readable output.")
    ap.add_argument("--examples", action="store_true",
                    help="Print sample mismatching chunks per document.")
    ap.add_argument("--min-toc-entries", type=int, default=4,
                    help="Fewest parseable contents entries to accept a document (default 4).")
    ap.add_argument("--min-offset-votes", type=int, default=3,
                    help="Fewest agreeing votes to accept a page offset (default 3).")
    ap.add_argument("--min-agreement", type=float, default=0.6,
                    help="Fraction of votes that must agree on the offset (default 0.6).")
    ap.add_argument("--max-disordered", type=float, default=0.25,
                    help="Reject a contents page if more than this fraction of its "
                         "entries have out-of-order or impossible folios (default 0.25).")
    args = ap.parse_args(argv)

    resolve_backend()
    db, db_source = resolve_db(args.db)
    conn = open_readonly(db)

    try:
        docs = list(conn.execute("SELECT id, filename FROM documents ORDER BY filename"))
    except sqlite3.OperationalError as exc:
        raise SystemExit(
            f"Could not read {db}: {exc}.\n"
            "SQLite raises 'disk I/O error' on some network and virtualised mounts.\n"
            "Copy the database to local disk and audit the copy -- this script never\n"
            "writes, so a copy is a faithful subject:\n"
            f"    cp '{db}' /tmp/rag_intelligence.sqlite\n"
            "    python scripts/section_audit.py --db /tmp/rag_intelligence.sqlite"
        ) from exc
    if args.document:
        needle = args.document.lower()
        docs = [d for d in docs if needle in d["id"].lower() or needle in d["filename"].lower()]
        if not docs:
            raise SystemExit(f"No document matching {args.document!r}.")

    results = [audit_document(conn, d, args) for d in docs]
    conn.close()

    measurable = [r for r in results if r.measurable]
    totals: Counter = Counter()
    for r in measurable:
        totals.update(r.verdicts)
    denom = sum(totals[v] for v in SCORED)
    corpus_pct = 100.0 * totals[CORRECT] / denom if denom else None

    if args.json:
        print(json.dumps({
            "database": str(db),
            "database_source": db_source,
            "definition": {
                "unit": "chunk",
                "counted_as_wrong": list(SCORED[1:]),
                "excluded_from_denominator": list(UNSCORED),
                "headline": "CORRECT / (CORRECT + COARSE_PARENT + WRONG_SECTION + FABRICATED)",
            },
            "documents": [{
                "document_id": r.document_id,
                "filename": r.filename,
                "page_count": r.page_count,
                "chunks": r.chunk_count,
                "measurable": r.measurable,
                "reason": r.reason,
                "toc_pages": r.toc_pages,
                "toc_numbered_entries": r.toc_entries,
                "toc_unnumbered_regions": r.toc_regions,
                "page_offset": (None if not r.offset else {
                    "value": r.offset.value,
                    "method": r.offset.method,
                    "votes_for": r.offset.votes_for,
                    "votes_total": r.offset.votes_total,
                    "verification": r.offset.cross_check,
                }),
                "verdicts": {v: r.verdicts[v] for v in ALL_VERDICTS},
                "measured_blocks": r.denominator,
                "pct_correct": r.pct_correct,
                "examples": r.examples,
            } for r in results],
            "corpus": {
                "documents_measured": len(measurable),
                "documents_total": len(results),
                "verdicts": {v: totals[v] for v in ALL_VERDICTS},
                "measured_blocks": denom,
                "pct_correct": corpus_pct,
            },
        }, indent=2))
        return 0

    print("SECTION CITATION AUDIT")
    print(f"database: {db}")
    print(f"          (located via {db_source})")
    print(f"mismatch = COARSE_PARENT + WRONG_SECTION + FABRICATED;"
          f" AMBIGUOUS/REFINEMENT/NO_LABEL are excluded, not counted correct.\n")
    print(render_table(results))
    print()

    print("PAGE OFFSETS (printed page + offset = PDF page)")
    for r in results:
        if r.offset and r.offset.value is not None:
            o = r.offset
            print(f"  {r.filename:<46} {o.value:+d}   via {o.method}; "
                  f"{o.votes_for}/{o.votes_total} votes agreed; verified: {o.cross_check}")
        elif r.measurable is False and r.offset:
            print(f"  {r.filename:<46} UNDETERMINED  ({r.offset.cross_check})")
    print()

    unmeasured = [r for r in results if not r.measurable]
    if unmeasured:
        print("NO GROUND TRUTH AVAILABLE (reported, not estimated)")
        for r in unmeasured:
            print(f"  {r.filename:<46} {r.reason}")
        print()

    if args.examples:
        print("SAMPLE MISMATCHES")
        for r in measurable:
            if not r.examples:
                continue
            print(f"  {r.filename}")
            for e in r.examples:
                print(f"    pdf p{e['pdf_page']:<5} {e['verdict']:<14} "
                      f"assigned {e['assigned']!r} / in force {e['in_force']!r}")
        print()

    print("CORPUS TOTAL")
    print(f"  documents measured : {len(measurable)} of {len(results)}"
          f"  ({', '.join(r.filename for r in measurable) or 'none'})")
    for v in ALL_VERDICTS:
        print(f"  {v:<16} : {totals[v]}")
    print(f"  measured blocks  : {denom}")
    print(f"  percent correct  : "
          f"{f'{corpus_pct:.1f}%' if corpus_pct is not None else 'n/a (nothing measurable)'}")
    print()
    print(HOW_TO_READ)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
