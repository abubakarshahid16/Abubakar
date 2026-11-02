"""#1584: the proof of one compiled rule. The answer is a claim; these functions decide. Pure, no database, no model.

THE QUOTE must stand on the cited page's stored text and be a WHOLE sentence of it, so nothing before or after it can
hide. A leading or trailing condition of that sentence must be in the rule's `condition`, or the rule is dropped as
`condition_not_captured`: code never writes the condition for the model and never stores a conditional limit bare.

THE VALUE is the pair the sentence binds to its comparator: the number and unit standing together
(`standards_converter.limit_scope`, the converter's own check), and the first number after the comparator's words or
right before them. A number of another thing, a conversion or one end of a range is dropped and counted. Numbers
through `numparse`, units through `datasheet_ai.unit_in_quote`.

`quote_verified` is THE quote check, run over version 1 and version 2 alike.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from . import ai_requirements, claims, conditions, field_vocabulary, numparse
from . import standards_converter as sc
from .ai_requirement_tables import quote_on_page
from .converter_gates import _CLAUSE_HEADING, in_example, quote_unreadable
from .converter_gates import fold as _fold
from .datasheet_ai import unit_in_quote

MIN_QUOTE_CHARS = 8
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
#: The strength of a rule whose scope may sit outside its own sentence. An approval path can refuse it by this word.
CONTEXT_DEPENDENT = "context_dependent"
_CAPTION = re.compile(r"^\s*(?:table|figure|fig\.?|note)\s+\w", re.IGNORECASE)
_SCOPE_WORDS = re.compile(
    r"\b(?:only|for|appl(?:y|ies)\s+to|the\s+following)\b", re.IGNORECASE
)
_REFERS_BACK = re.compile(
    r"^\W*(?:this|these|those|such|they|it|the\s+above|the\s+foregoing|the\s+same)\b",
    re.IGNORECASE,
)
#: A clause number alone on its line; the next line starts in capitals and is the heading's words.
_LONE_NUMBER = re.compile(r"^\s*\d+(?:\.\d+)+\.?\s*$")
#: Field words that name a kind of property, not a thing: the quote need not print them.
_GENERIC_FIELD_WORDS = frozenset(
    {
        "size",
        "type",
        "location",
        "use",
        "value",
        "kind",
        "amount",
        "percent",
        "service",
        "material",
        "requirement",
    }
)
#: Small words a field name may add without saying anything the quote must print.
_FIELD_SMALL_WORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "of",
        "to",
        "in",
        "on",
        "at",
        "by",
        "for",
        "from",
        "with",
        "and",
        "or",
        "that",
        "which",
        "between",
        "above",
        "below",
        "than",
        "per",
        "its",
    ]
)
#: What may follow a limit and finish the property, not scope it: "6% of the gauge reading", "7 m from any fence",
#: "77 Poise is not exceeded".
_COMPLEMENT = re.compile(r"^\W*(?:of|from|to|per|than|is|are|shall|must|be)\b")
#: The openers that scope a rule, whatever else the tail says.
_SCOPE_OPENER = re.compile(r"^\W*(?:at|above|below)\b")
_SCOPE_ANYWHERE = re.compile(
    r"\b(?:in|on|during|under|within|with|without|while|after|before|except|unless|provided)\b"
)
#: A figure after these words is what a condition tests, not what the rule demands: "no cover is needed provided the
#: rail heat is -22 C". "shall be provided with" is a verb and is not here.
_INSIDE_A_CONDITION = re.compile(
    r"\b(?:if|when|whenever|unless|where|provided\s+(?:that|the|all|it))\b"
)
_LEADING_PREPOSITION = re.compile(
    r"^(?P<clause>(?:for|during|above|below|at|except|within|after|before|on|with|without)\s+[^,;:.]{3,140}),\s"
)
_STRIP_PREFIX = re.compile(r"^\W*(?:\d+(?:\.\d+)+\.?\s+|\(?[0-9a-z]{1,3}\)\s+)?")
#: "of" is `comparators_said`'s weak cue; it never binds a figure ("pressure of a 100 mm nozzle").
_BIND_CUES = {**sc._CUES, "=": ("equal", "shall be", "must be", "is", "are", "=")}
#: Words that take the obligation away, and the strength of the rest. "must" is as binding as "shall".
_NOT_A_LIMIT = re.compile(
    r"\bneed\s+not\b|\bdoes\s+not\s+need\s+to\b|\bnot\s+required\s+to\b"
)
_STRENGTHS = (
    ("shall", "shall"),
    ("must", "shall"),
    ("should", "should"),
    ("may", "may"),
)


ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "rules": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "applies_to": {"type": ["string", "null"]},
                    "condition": {"type": ["string", "null"]},
                    "exceptions": {"type": ["string", "null"]},
                    "field": {"type": ["string", "null"]},
                    "comparator": {"type": ["string", "null"]},
                    "limit": {"type": ["string", "number", "null"]},
                    "unit": {"type": ["string", "null"]},
                    "clause": {"type": ["string", "null"]},
                    "page": {"type": ["integer", "null"]},
                    "quote": {"type": ["string", "null"]},
                },
            },
        }
    },
    "required": ["rules"],
}


@dataclass
class Chunk:
    custom_id: str
    text: str
    pages: set[int] = field(default_factory=set)
    #: page -> the clauses in force on it: printed there, or running on from an earlier page.
    clauses: dict[int, set[str]] = field(default_factory=dict)


def quote_verified(quote: object, page_text: str | None) -> bool:
    """THE quote check, for version 1 and version 2 alike: the words stand on the cited page's stored text."""
    words = " ".join(str(quote or "").split())
    return (
        len(words) >= MIN_QUOTE_CHARS
        and bool(page_text)
        and quote_on_page(words, page_text)
    )


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
        title = before and len(before) <= _TITLE_CHARS and line[0].isupper()
        if title or _CLAUSE_HEADING.match(line) or _LONE_NUMBER.match(line):
            blocks.append([])
        blocks[-1].append(line)
        before = line
    return [" ".join(b) for b in blocks if b]


def sentences_of(text: str) -> list[str]:
    """The page's sentences, folded."""
    out: list[str] = []
    for block in _blocks_of(text):
        held = ""
        for piece in re.split(r"(?<=[.;])\s+", block):
            held = f"{held} {piece}" if held else piece
            if not held.lower().endswith(_ABBREVIATED):
                out.append(_fold(held))
                held = ""
        if held:
            out.append(_fold(held))
    return out


def _core(sentence: str) -> str:
    return _STRIP_PREFIX.sub("", _fold(sentence)).rstrip(" .;:,")


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


def is_heading_line(line: str, following: str) -> bool:
    """A clause heading: a number and words, or a number alone with a line in capitals after it."""
    return bool(_CLAUSE_HEADING.match(line)) or bool(
        _LONE_NUMBER.match(line) and following.strip()[:1].isupper()
    )


def _headings(text: str) -> list[tuple[int, str, str]]:
    """(where in the folded page, clause number, the heading's words) of each heading on a page. A number alone on its
    line is a heading when the next line starts in capitals; a lone figure before lower-case words is not."""
    lines = text.splitlines()
    out, at = [], 0
    for n, line in enumerate(lines):
        following = lines[n + 1].strip() if n + 1 < len(lines) else ""
        if _CLAUSE_HEADING.match(line):
            out.append((at, line.split()[0].rstrip("."), line))
        elif _LONE_NUMBER.match(line) and following[:1].isupper():
            out.append((at, line.split()[0].rstrip("."), f"{line.strip()} {following}"))
        at += len(_fold(line)) + 1 if line.strip() else 0
    return out


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


def _clause_problem(clause: str, quote: str, page: int, pages) -> str | None:
    """The cited clause is the label nearest before the quote. With no heading to read, it must carry a number and
    be printed before the quote on that page."""
    if clause.lower() in sc.PLACEHOLDER_CLAUSES:
        return "no_clause"
    folded = _fold(pages[page])
    at = max(folded.find(_fold(quote)), 0)
    nearest = _clause_in_force(pages, page, at)
    if nearest is not None:
        return None if clause == nearest else "clause_not_nearest"
    printed = numparse.contains_whole(folded[:at], _fold(clause))
    return None if printed and re.search(r"\d", clause) else "clause_not_nearest"


def _written(limit: str, quote: str):
    """The number in the quote that is this limit, however it is printed ("1000", "1,000", "5/8"), or None. A fraction
    is read whole; a plain limit never takes its value from one end of a fraction."""
    wanted = numparse.as_limit(limit)
    if wanted is None:
        return None
    text = numparse.fold(quote)
    fractions = numparse.find_fractions(text)
    found = next((n for n in fractions if n.value == wanted), None)
    if found is not None:
        return found
    inside = [(f.start, f.end) for f in fractions]
    return next(
        (
            n
            for n in numparse.find_numbers(text)
            if n.value == wanted and not any(a <= n.start < b for a, b in inside)
        ),
        None,
    )


def _main_clause(quote: str, *parts: str) -> str:
    """The quote with what the rule already holds as condition or exception taken out, so a figure or a comparator word
    in the scope is not read as the limit's. A number joined to its unit by a hyphen stands apart from it here."""
    body = _unhyphen(_fold(quote))
    for part in parts:
        for piece in part.split(";"):
            words = _unhyphen(_fold(piece)).rstrip(" .,")
            if words:
                body = body.replace(words, " ")
    if (
        "not exceed" in body
    ):  # "shall not exceed X by more than 10%" states one ceiling, not a floor
        body = body.replace("by more than", " ")
    return " ".join(body.split())


def _unhyphen(text: str) -> str:
    return re.sub(r"(?<=\d)-(?=[a-z])", " ", text)


def _cue_spans(comparator: str, text: str) -> list[tuple[int, int]]:
    spans = []
    for cue in _BIND_CUES.get(comparator, ()):
        word = cue[0].isalpha()
        pattern = rf"(?<![a-z]){re.escape(cue)}(?![a-z])" if word else re.escape(cue)
        spans += [m.span() for m in re.finditer(pattern, text)]
    return spans


def _bound_to_comparator(number, unit: str, comparator: str, quote: str) -> bool:
    """Is this the figure the comparator's words bind: the first number after them, or right before them?"""
    text = numparse.fold(quote).lower()
    numbers = numparse.find_numbers(text)
    tail = (
        re.match(rf"\s*{re.escape(unit.lower())}", text[number.end :]) if unit else None
    )
    end = number.end + (tail.end() if tail else 0)
    for start, stop in _cue_spans(comparator, text):
        between = [n for n in numbers if stop <= n.start < number.start]
        if stop <= number.start and not between:
            return True
        if start >= end and not re.search(r"\w", text[end:start]):
            return True
    return False


def _is_range(number, unit: str, quote: str) -> bool:
    """One end of a range: another number straight after this one, or straight before it, joined by a range word."""
    text = numparse.fold(quote).lower()
    after = text[number.end :]
    if unit:
        after = re.sub(rf"^\s*{re.escape(unit.lower())}", "", after)
    joined = rf"\s*(?:to|and|through|[{re.escape(numparse.DASH_LIKE)}])\s*"
    before = text[: number.start]
    return bool(
        re.match(joined + r"\.?\d", after)
        or re.search(r"[\d.]\s*" + joined + r"$", before)
    )


def _unit_left_out(number, quote: str) -> bool:
    """A recognised unit right after the number in the quote, and the answer gave no unit."""
    after = numparse.fold(quote)[number.end :].split()
    return bool(after and claims.unit_dimension(after[0].strip(",.;:()")))


def _comparator_said(body: str, comparator: str, field: str) -> bool:
    """The clause's words say this comparator. "the maximum load is less than" says two, and the first names
    the property: so when they disagree, the words outside the field's own decide. A field holding the only cue
    ("a maximum thickness of 77") is answered by the first test."""
    if sc._comparator_says(body, comparator):
        return True
    rest = body.replace(_fold(field), " ")
    return rest != body and sc._comparator_says(rest, comparator)


def _limit_problem(limit, unit, comparator, body, sentence, field) -> str | None:
    """Why this limit is not the one the sentence states, or None. `body` is the quote outside its condition."""
    if any(w in sentence for w in sc.DEFAULT_WORDS):
        return "default_not_limit"
    # "100 mm" or "316L" would skip every binding check below.
    if numparse.as_limit(limit) is None:
        return "limit_not_a_bare_number"
    number = _written(limit, body)
    if number is None:
        return "limit_not_in_quote"
    if unit and not unit_in_quote(unit, body):
        return "unit_not_in_quote"
    if not unit and _unit_left_out(number, body):
        return "unit_left_out"
    if comparator not in sc.COMPARATORS or not _comparator_said(
        body, comparator, field
    ):
        return "comparator_not_in_quote"
    whole = _unhyphen(
        sentence
    )  # a range is read on the whole sentence: scope taken out must not hide its other end
    in_whole = _written(limit, whole)
    if _INSIDE_A_CONDITION.search(numparse.fold(body).lower()[: number.start]):
        return "limit_inside_a_condition"
    if _is_range(number, unit, body) or (in_whole and _is_range(in_whole, unit, whole)):
        return "range_not_single"
    if sc.limit_scope(body, body, number.raw, unit) is None:
        return "number_and_unit_apart"
    if not _bound_to_comparator(number, unit, comparator, body):
        return "limit_not_bound"
    return None


def _finishes_the_property(tail: str, field: str) -> bool:
    """Do these words after a limit finish what is measured, rather than say when it holds? Never when they read as a
    scope. Conditions are never lost for this: any doubt leaves them a condition."""
    if _is_scope(tail) or _SCOPE_OPENER.match(tail) or _SCOPE_ANYWHERE.search(tail):
        return False
    words = re.sub(r"\([^)]*\)", " ", tail)
    return bool(_COMPLEMENT.match(tail)) or _field_words(words) <= _field_words(field)


def _leading_scope(sentence: str) -> str | None:
    found = conditions._LEADING_CONDITION.match(sentence) or _LEADING_PREPOSITION.match(
        sentence
    )
    return _unhyphen(_fold(found.group("clause"))) if found else None


def _trailing_scope(limit: str, unit: str, body: str, field: str) -> str | None:
    """What the main clause still says after its limit, once captured scope is out of it, unless it finishes the property."""
    number = _written(limit, body) if limit else None
    if number is None:
        return None
    tail = sc.limit_scope(body, body, number.raw, unit)
    if not tail or _finishes_the_property(tail, field):
        return None
    return tail


def _condition_captured(
    condition: str, sentence: str, limit, unit, body, field
) -> bool:
    """Every scope of the sentence is held by the rule. The trailing one is read off the main clause, so what is held
    has left it already; what is still there is lost."""
    if _trailing_scope(limit, unit, body, field):
        return False
    said = _unhyphen(_fold(condition))
    leading = _leading_scope(sentence)
    if said:
        return not leading or leading in said
    return not leading and not ai_requirements._is_conditional(sentence)


def quote_span(quote: str, text: str) -> tuple[int | None, int | None]:
    """Where the quote stands in the stored page: its words, any white space between, any case."""
    pattern = r"\s+".join(re.escape(word) for word in quote.split())
    found = re.search(pattern, text, re.IGNORECASE)
    return found.span() if found else (None, None)


def _lead_in(pages: dict[int, str], page: int, quote: str) -> str:
    """The start of a sentence the page before left open, when this quote begins in lower case: "" when it did not."""
    earlier = [p for p in pages if p < page]
    if not quote[:1].islower() or not earlier:
        return ""
    before = sentences_of(pages[max(earlier)])
    if not before or before[-1].rstrip()[-1:] in (".", ";", ":", "!", "?"):
        return ""
    return before[-1]


def _condition_on_page(condition: str, text: str) -> bool:
    """Each part (two conditions are written "a; b") stands on the page."""
    folded = _fold(text)
    return all(_fold(part) in folded for part in condition.split(";") if part.strip())


def strength_of(sentence: str) -> str:
    for word, strength in _STRENGTHS:
        if re.search(rf"\b{word}\b", sentence):
            return strength
    return "stated"


def _quote_problem(answer: dict, chunk: Chunk, pages: dict[int, str]) -> str | None:
    """Why a proposal's page, quote or clause is not proven, or None."""
    page = answer.get("page")
    if isinstance(page, bool) or not isinstance(page, int) or page not in chunk.pages:
        return "page_not_sent"
    text = pages.get(page, "")
    quote = " ".join(str(answer.get("quote") or "").split())
    if not quote_verified(quote, text):
        return "quote_not_on_page"
    if quote_unreadable(quote, quote):
        return "quote_unreadable"
    if in_example(
        {"requirement_text": quote, "source_text": quote, "chunk_text": text}
    ):
        return "example_not_requirement"
    return _clause_problem(str(answer.get("clause") or "").strip(), quote, page, pages)


def _stem(word: str) -> str:
    if len(word) > 4 and word.endswith("ed"):
        return word[:-1]
    return word[:-1] if len(word) > 3 and word.endswith("s") else word


def _field_words(words: str) -> set[str]:
    return {
        _stem(w) for w in field_vocabulary._tokens(words) if len(w) > 1
    } - _FIELD_SMALL_WORDS


def _names_field(quote: str, name: str) -> bool:
    """Every word of the field that says WHICH thing is printed in the quote, plurals aside. A generic word (size, type)
    and a qualifier (maximum) need not be; a field of nothing else must still be printed."""
    words = _field_words(name)
    named = {
        w
        for w in words
        if w not in _GENERIC_FIELD_WORDS and w not in sc.field_naming._QUALIFIERS
    }
    return (named or words) <= _field_words(quote) and bool(words)


def _without_gloss(name: str) -> str:
    """A field's bracketed gloss is the model's own note, not words to store. "valve(s)" has no space and stays."""
    return " ".join(re.sub(r"\s\([^)]*\)", " ", name).split()) or name


def _applies_to_on_page(applies_to: str, text: str) -> bool:
    wanted = set(field_vocabulary._tokens(applies_to))
    return bool(wanted) and wanted <= set(field_vocabulary._tokens(text))


def _is_scope(words: str) -> bool:
    return bool(_SCOPE_WORDS.search(words)) or ai_requirements._is_conditional(words)


def _context_lines(pages: dict[int, str], page: int, start: int) -> tuple[str, str]:
    """(nearest heading above, nearest caption above): this page, then back over earlier pages for the heading."""
    before = pages[page][:start]
    here = _headings(before)
    heading = here[-1][2] if here else ""
    caption = next((x for x in reversed(before.splitlines()) if _CAPTION.match(x)), "")
    for earlier in sorted((p for p in pages if p < page), reverse=True):
        if heading:
            break
        found = _headings(pages[earlier])
        heading = found[-1][2] if found else ""
    return heading, caption


def _adjacent_scope(sentence: str, text: str) -> bool:
    """A scope in the sentence before, when it states no figure of its own, or a reference back in the one after."""
    found = sentences_of(text)
    cores = [_core(s) for s in found]
    if sentence not in cores:
        return False
    at = cores.index(sentence)
    before = found[at - 1] if at else ""
    after = found[at + 1] if at + 1 < len(found) else ""
    if before and _is_scope(before) and not numparse.find_numbers(before):
        return True
    return bool(after and _REFERS_BACK.match(after) and _is_scope(after))


def is_table_row(answer: object, tables) -> bool:
    """Does the table reader's record hold this proposal's quote? Only where a record exists."""
    if not isinstance(answer, dict) or not tables:
        return False
    return _core(str(answer.get("quote") or "")) in {
        _core(words) for words in tables.get(answer.get("page"), ())
    }


def context_flags(
    answer: dict, sentence: str, strength: str, pages, tables
) -> list[str]:
    """Why this rule may not stand alone, as far as these word tests can see. NO FLAG DOES NOT MEAN A RULE STANDS
    ALONE: scope named as a plain noun phrase in a heading, a parent heading, a previous sentence holding a number,
    an exception in the next sentence and a lead-in on the prior page all stay unflagged."""
    page, text = answer["page"], pages[answer["page"]]
    flags = []
    if is_table_row(answer, tables):
        flags.append("table_row")
    if strength == "stated":
        flags.append("row_like")
    if _REFERS_BACK.match(sentence):
        flags.append("refers_back")
    start = quote_span(" ".join(str(answer["quote"]).split()), text)[0] or 0
    heading, caption = _context_lines(pages, page, start)
    if heading and _is_scope(heading):
        flags.append("heading_scope")
    if caption and _is_scope(caption):
        flags.append("caption_scope")
    if _adjacent_scope(sentence, text):
        flags.append("adjacent_scope")
    return flags


def verify(
    answer: object, chunk: Chunk, pages: dict[int, str], tables=None
) -> tuple[dict | None, str | None]:
    """(rule, None) or (None, reason), for ONE proposal. Code decides; the answer is a claim."""
    if not isinstance(answer, dict):
        return None, "not_an_object"
    problem = _quote_problem(answer, chunk, pages)
    if problem:
        return None, problem
    page, text = answer["page"], pages[answer["page"]]
    quote = " ".join(str(answer.get("quote") or "").split())
    applies_to = " ".join(str(answer.get("applies_to") or "").split())
    if not applies_to:
        return None, "no_applies_to"
    name = " ".join(str(answer.get("field") or "").split())
    if not name:
        return None, "no_field"
    if not _names_field(quote, _without_gloss(name)):
        return None, "field_not_in_quote"
    name = _without_gloss(name)
    lead_in = _lead_in(pages, page, quote)
    readable = f"{lead_in}\n{text}" if lead_in else text
    condition = " ".join(str(answer.get("condition") or "").split())
    if condition and not _condition_on_page(condition, readable):
        return None, "condition_not_on_page"
    exception = " ".join(str(answer.get("exceptions") or "").split())
    if exception and not _condition_on_page(exception, readable):
        return None, "exception_not_on_page"
    limit = "" if answer.get("limit") is None else str(answer.get("limit")).strip()
    unit = str(answer.get("unit") or "").strip()
    comparator = str(answer.get("comparator") or "").strip()
    sentence = whole_sentence(quote, text)
    if sentence is None:
        return None, "condition_not_captured"
    if _NOT_A_LIMIT.search(sentence):
        return None, "need_not_is_not_a_limit"
    body = _main_clause(quote, condition, exception)
    if limit:
        reason = _limit_problem(limit, unit, comparator, body, sentence, name)
        if reason:
            return None, reason
    elif comparator or unit:
        return None, "comparator_without_limit"
    whole = f"{lead_in} {sentence}" if lead_in else sentence
    held = "; ".join(p for p in (condition, exception) if p)
    if not _condition_captured(held, whole, limit, unit, body, name):
        return None, "condition_not_captured"
    start, end = quote_span(quote, text)
    stated = strength_of(sentence)
    flags = context_flags(answer, sentence, stated, pages, tables)
    if lead_in:
        flags.append("crosses_page")
    return (
        {
            "applies_to": applies_to,
            "applies_to_verified": _applies_to_on_page(applies_to, text),
            "condition_text": _fold(condition) or None,
            "exception_text": _fold(exception) or None,
            "field": name,
            "comparator": comparator or None,
            "limit_text": limit or None,
            "limit_value": numparse.as_limit(limit) if limit else None,
            "unit": unit or None,
            "unit_dimension": claims.unit_dimension(unit) if unit else None,
            "strength": CONTEXT_DEPENDENT if flags else stated,
            "sentence_strength": stated,
            "context_flag": ",".join(flags) or None,
            "clause": str(answer.get("clause")).strip(),
            "page": page,
            "quote": quote,
            "quote_sha256": hashlib.sha256(quote.encode("utf-8")).hexdigest(),
            "quote_start": start,
            "quote_end": end,
        },
        None,
    )
