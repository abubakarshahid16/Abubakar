"""#1584: how a standard's pages are read into sentences, headings and chunks. Pure: no database, no model, no number.

A chunk ends at `CHUNK_CHARS` or `MAX_RULES_PER_CHUNK` requirement words, whichever comes first, so a dense page cannot
outgrow the output room of the request that asks for it. Changing how chunks are cut changes their ids, so it belongs to
a new prompt version.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from functools import lru_cache

from . import numparse
from . import standards_converter as sc
from .converter_gates import _CLAUSE_HEADING
from .converter_gates import fold as _fold

_SHALL = re.compile(r"\b(?:shall|must)\b", re.IGNORECASE)
#: Characters of pages in one request, and of the stable start of the standard before the cache breakpoint.
CHUNK_CHARS = 12_000
HEAD_CHARS = 6_000
#: Rules a chunk may ask for: a chunk also ends here, so a dense page cannot outgrow its output room. Measured: about 200
#: output tokens a rule on the first real compile. The rest of `MAX_OUTPUT_TOKENS` is thinking and long quotes.
MAX_RULES_PER_CHUNK = 25
TOKENS_PER_RULE = 200

#: A line this short that is followed by one starting in capitals is a title or a table row, not a wrapped sentence.
_TITLE_CHARS = 60
#: A period after one of these does not end a sentence.
_ABBREVIATED = (
    "max.",
    "min.",
    "no.",
    "nos.",
    "fig.",
    "approx.",
    "ref.",
    "e.g.",
    "i.e.",
)
#: A clause number alone on its line; the next line starts in capitals and is the heading's words.
_LONE_NUMBER = re.compile(r"^\s*\d+(?:\.\d+)+\.?\s*$")
#: What opens a sentence and is not a word of it: a clause number, a printed label, sub-paragraph marks.
_STRIP_PREFIX = re.compile(
    r"^\W*(?:(?:\d+(?:\.\d+)+\.?\s+|[a-z]{1,6}-(?:[a-z0-9]{1,6}-)*\d+[a-z]?(?:\.\d+)*(?=[\s(])|\(?[0-9a-z]{1,3}\)\s*)\W*)*"
)


#: A hyphen, and any space or line end after it, between two letters.
_WORD_HYPHEN = re.compile(r"(?<=[^\W\d_])-\s*(?=[^\W\d_])")
_LABEL = r"(?:[A-Z0-9]{1,6}-)+\d+[A-Z]?(?:\.\d+)*"
_SUBS = r"(?:\s?\(-?[A-Za-z0-9]{1,3}\))*"
#: A label heads a line only alone, with a title in capitals, or with its sub-paragraph and text: "XY-12 and the rail" is
#: a reference that wrapped. A mark outside plain ASCII may stand before it (a revision glyph).
_LINE_LABEL = re.compile(
    rf"^\s*(?:[^\x00-\x7f]\S*\s+)?(?P<label>{_LABEL})(?![\w-])(?P<subs>{_SUBS})"
    r"(?:\s*$|\s+[A-Z(])"
)
_LINE_SUBS = re.compile(rf"^\s*{_SUBS}")
_ONE_SUB = re.compile(r"\(-?[a-z0-9]{1,3}\)")
_CITED_LABEL = re.compile(rf"(?P<label>{_LABEL})(?P<subs>{_SUBS})")


@dataclass
class Chunk:
    custom_id: str
    text: str
    pages: set[int] = field(default_factory=set)
    #: page -> the clauses in force on it: printed there, or running on from an earlier page.
    clauses: dict[int, set[str]] = field(default_factory=dict)


def _sentence_is_open(words: str) -> bool:
    """Has this run of lines an obligation with no stop after it, or a quotation not closed? Then a short line that a
    capital follows is a wrapped sentence on a narrow page, not a title."""
    tail = re.split(r"[.;:](?:\s|$)", words)[-1]
    return bool(re.search(r"\b(?:shall|must|should|may|will)\b", tail)) or tail.count(
        "\u201c"
    ) > tail.count("\u201d")


def _blocks_of(text: str) -> list[str]:
    """Runs of lines that may hold one sentence: broken at a blank line, a clause heading, and after a short line
    followed by one in capitals. A wrapped line stays with the sentence it belongs to."""
    blocks: list[list[str]] = [[]]
    before = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            blocks.append([])
            before = ""
            continue
        title = (
            before
            and len(before) <= _TITLE_CHARS
            and line[0].isupper()
            and not _sentence_is_open(" ".join(blocks[-1]))
        )
        if (
            title
            or _CLAUSE_HEADING.match(line)
            or _LONE_NUMBER.match(line)
            or _LINE_LABEL.match(line)
            or _LINE_SUBS.match(line)[0].strip()
        ):
            blocks.append([])
        blocks[-1].append(line)
        before = line
    return [" ".join(b) for b in blocks if b]


def sentences_of(text: str) -> list[str]:
    """The page's sentences, folded."""
    out: list[str] = []
    for block in _blocks_of(text):
        held = ""
        for piece in re.split(r"(?<=[.;])\s+|(?<=[.;][\"\u201d\u2019)])\s+", block):
            held = f"{held} {piece}" if held else piece
            if not held.lower().endswith(_ABBREVIATED):
                out.append(_fold(held))
                held = ""
        if held:
            out.append(_fold(held))
    return out


def _core(sentence: str) -> str:
    return _STRIP_PREFIX.sub("", _fold(sentence)).rstrip(' .;:,"\u201d\u2019')


def core_of(sentence: str) -> str:
    return _core(sentence)


def shall_sentences(pages: dict[int, str]) -> set[str]:
    """Every sentence with shall or must on these pages, as a quote of it would be compared."""
    return {
        _core(s)
        for text in pages.values()
        for s in sentences_of(text)
        if re.search(r"\b(?:shall|must)\b", s)
    }


def whole_sentence(quote: str, page: str) -> str | None:
    """The sentence when the quote is all of it (a clause number and final stop aside), else None."""
    wanted = _core(quote)
    for sentence in sentences_of(page):
        if _core(sentence) == wanted:
            return wanted
    return None


def is_heading_line(line: str, following: str, last: str = "") -> bool:
    """A clause heading: a number and words, or a number alone with a line in capitals after it, and in sequence with the
    clause before it. A lone decimal from a table fails the last test."""
    if _CLAUSE_HEADING.match(line):
        return True
    if not (_LONE_NUMBER.match(line) and following.strip()[:1].isupper()):
        return False
    if not last:
        return True
    major, before = line.split()[0].split(".")[0], last.split(".")[0]
    return (
        major.isdigit()
        and before.isdigit()
        and int(before) <= int(major) <= int(before) + 1
    )


def _headings(text: str) -> list[tuple[int, str, str]]:
    """(where in the folded page, clause number, the heading's words) of each heading on a page. A number alone on its
    line is a heading when the next line starts in capitals; a lone figure before lower-case words is not."""
    lines = text.splitlines()
    out, at, last = [], 0, ""
    for n, line in enumerate(lines):
        following = lines[n + 1].strip() if n + 1 < len(lines) else ""
        if is_heading_line(line, following, last):
            last = line.split()[0].rstrip(".")
            words = (
                line if _CLAUSE_HEADING.match(line) else f"{line.strip()} {following}"
            )
            out.append((at, last, words))
        at += len(_fold(line)) + 1 if line.strip() else 0
    return out


@lru_cache(maxsize=4096)  # the same page is read for thousands of proposals
def join_hyphens(text: str) -> str:
    """A word broken by a hyphen at a line end reads as one word: the page's "ves-\nsel", a copy's "ves-sel" and "vessel"
    all read "vessel". Only between two letters, so a figure ("5-7", "2-inch") never changes: exact on words and digits,
    no fuzzy match. For proof only; what is stored is the model's own quote."""
    return _WORD_HYPHEN.sub("", text.replace("\u00ad", ""))


@lru_cache(maxsize=4096)
def _label_marks(text: str) -> tuple[tuple[int, str, str], ...]:
    """(where in the folded page, "label" or a sub-paragraph's kind, its words): what stands at the start of each line."""
    out, at = [], 0
    for line in text.splitlines():
        found = _LINE_LABEL.match(line)
        if found:
            out.append((at, "label", found["label"]))
        subs = found["subs"] if found else _LINE_SUBS.match(line)[0]
        out += [(at, _sub_kind(s), s) for s in _ONE_SUB.findall(subs.casefold())]
        at += len(_fold(line)) + 1 if line.strip() else 0
    return tuple(out)


def _sub_kind(sub: str) -> str:
    inner = sub.strip("()")
    if inner.startswith("-"):
        return "dash"
    return "digit" if inner.isdigit() else "letter"


def label_in_force(
    clause: str, pages: dict[int, str], page: int, at: int
) -> bool | None:
    """Is a printed label with letters and a number, "XY-12" or "3-4", with any sub-paragraphs, "XY-12(a)(1)(-b)", the one
    in force at `at`? Its label is the nearest one starting a line before the quote, running back over earlier pages, and
    each sub-paragraph cited is the nearest of its kind after that label. None: not such a label ("4.2.1")."""
    cited = _CITED_LABEL.fullmatch(clause)
    if not cited:
        return None
    wanted = [(_sub_kind(s), s) for s in _ONE_SUB.findall(cited["subs"].casefold())]
    nearest: dict[str, str] = {}
    for number in sorted((p for p in pages if p <= page), reverse=True):
        marks = _label_marks(pages[number])
        for where, kind, words in reversed(marks):
            if number == page and where > at:
                continue
            if kind == "label":
                return words == cited["label"] and all(
                    nearest.get(k) == s for k, s in wanted
                )
            nearest.setdefault(kind, words)
    return False


def _clause_labels(text: str) -> list[tuple[int, str]]:
    return [(where, clause) for where, clause, _words in _headings(text)]


def _clause_in_force(pages: dict[int, str], page: int, at: int) -> str | None:
    """The nearest clause heading before position `at` of `page`, running back over earlier pages."""
    here = [c for where, c in _clause_labels(pages[page]) if where <= at]
    if here:
        return here[-1]
    for earlier in sorted((p for p in pages if p < page), reverse=True):
        labels = _clause_labels(pages[earlier])
        if labels:
            return labels[-1][1]
    return None


def _whole_number_heading(clause: str, text: str, at: int, nearest: str | None) -> bool:
    """A section number alone ("10", then its title) as the heading over the quote: on the page, before the quote, after
    any numbered clause there, and in sequence with the clause in force. Read here, not in chunk labels."""
    if not clause.isdigit():
        return False
    if nearest is not None and int(nearest.split(".")[0]) > int(clause):
        return False
    pattern = rf"^\s*{clause}\.?(?:\s+[A-Za-z].*)?\s*$"
    where = 0
    found = -1
    for line in text.splitlines():
        if re.match(pattern, line):
            found = where
        where += len(_fold(line)) + 1 if line.strip() else 0
    if found < 0 or found > at:
        return False
    return all(
        place < found for place, _clause in _clause_labels(text[: _raw_at(text, at)])
    )


def _raw_at(text: str, at: int) -> int:
    """The place in the raw page of a place in the folded page, near enough to cut its headings off."""
    seen = 0
    for n, line in enumerate(text.splitlines(keepends=True)):
        seen += len(_fold(line)) + 1 if line.strip() else 0
        if seen > at:
            return sum(len(x) for x in text.splitlines(keepends=True)[: n + 1])
    return len(text)


def _clause_problem(clause: str, quote: str, page: int, pages) -> str | None:
    """The cited clause is the label nearest before the quote. With no heading to read, it must carry a number and
    be printed before the quote on that page."""
    if clause.lower() in sc.PLACEHOLDER_CLAUSES:
        return "no_clause"
    folded = _fold(pages[page])
    at = max(folded.find(_fold(quote)), 0)
    labelled = label_in_force(clause, pages, page, at)
    if labelled is not None:
        return None if labelled else "clause_not_nearest"
    nearest = _clause_in_force(pages, page, at)
    if _whole_number_heading(clause, pages[page], at, nearest):
        return None
    if nearest is not None:
        return None if clause == nearest else "clause_not_nearest"
    printed = numparse.contains_whole(folded[:at], _fold(clause))
    return None if printed and re.search(r"\d", clause) else "clause_not_nearest"


def _blocks(pages: dict[int, str]) -> list[tuple[int, str, str]]:
    """(page, clause, text): each page cut at its clause headings; a clause keeps its number across a page."""
    out: list[tuple[int, str, str]] = []
    clause = ""
    for page, text in sorted(pages.items()):
        lines: list[str] = []
        rows = text.splitlines()
        for n, line in enumerate(rows):
            following = rows[n + 1] if n + 1 < len(rows) else ""
            if is_heading_line(line, following, clause):
                if lines:
                    out.append((page, clause, "\n".join(lines)))
                clause, lines = line.split()[0].rstrip("."), []
            lines.append(line)
        if lines:
            out.append((page, clause, "\n".join(lines)))
    return out


def shall_count(text: str) -> int:
    """How many rules this text asks for: one per shall or must."""
    return len(_SHALL.findall(text))


def _pieces(text: str) -> list[str]:
    """A block over the chunk size or the rule count, cut at line ends. No text is lost; one line never splits."""
    out, now, size, rules = [], [], 0, 0
    for line in text.splitlines():
        more = shall_count(line)
        if now and (
            size + len(line) + 1 > CHUNK_CHARS or rules + more > MAX_RULES_PER_CHUNK
        ):
            out.append("\n".join(now))
            now, size, rules = [], 0, 0
        now.append(line)
        size += len(line) + 1
        rules += more
    return [*out, "\n".join(now)] if now else out


def chunks_of(pages: dict[int, str]) -> list[Chunk]:
    """Consecutive clause blocks up to `CHUNK_CHARS`, each labelled with its page and clause, ids stable for a text."""
    parts: list[tuple[int, str, str]] = []
    for page, clause, text in _blocks(pages):
        parts += [(page, clause, piece) for piece in _pieces(text)]
    groups: list[list[tuple[int, str, str]]] = []
    size = rules = 0
    for part in parts:
        more = shall_count(part[2])
        if (
            not groups
            or size + len(part[2]) > CHUNK_CHARS
            or rules + more > MAX_RULES_PER_CHUNK
        ):
            groups.append([])
            size = rules = 0
        groups[-1].append(part)
        size += len(part[2])
        rules += more
    out = []
    for n, group in enumerate(groups):
        text = "\n".join(f"[page {p} | clause {c or 'none'}]\n{t}" for p, c, t in group)
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
        chunk = Chunk(f"c{n:05d}-{digest}", text)
        for page, clause, _text in group:
            chunk.pages.add(page)
            chunk.clauses.setdefault(page, set())
            if clause:
                chunk.clauses[page].add(clause)
        out.append(chunk)
    return out
