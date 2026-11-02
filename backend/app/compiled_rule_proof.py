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

from . import ai_requirements, claims, conditions, field_vocabulary, numparse
from . import standards_converter as sc
from .ai_requirement_tables import quote_on_page
from .compiled_rule_context import _is_scope, context_flags, quote_span
from .compiled_rule_field import (
    _GENERIC_FIELD_WORDS,
    _field_printed,
    _field_words,
    _names_field,
    _without_gloss,
)
from .compiled_rule_pages import (
    Chunk,
    _clause_in_force,
    _clause_labels,
    _core,
    sentences_of,
    whole_sentence,
)
from .compiled_rule_shape import FIGURE_NOT_STORED, figure_is_plain
from .compiled_rule_shape import cue_spans as _cue_spans
from .converter_gates import fold as _fold
from .converter_gates import in_example, quote_unreadable
from .datasheet_ai import unit_in_quote

MIN_QUOTE_CHARS = 8
#: The strength of a rule whose scope may sit outside its own sentence. An approval path can refuse it by this word.
CONTEXT_DEPENDENT = "context_dependent"
#: What may follow a limit and finish the property, not scope it: "6% of the gauge reading", "7 m from any fence",
#: "77 Poise is not exceeded".
_COMPLEMENT = re.compile(r"^\W*(?:of|from|to|per|than|is\s+not\s+exceeded)\b")
#: The openers that scope a rule, whatever else the tail says.
_SCOPE_OPENER = re.compile(r"^\W*(?:at|above|below)\b")
_SCOPE_ANYWHERE = re.compile(
    r"\b(?:in|on|during|under|within|with|without|while|until|once|after|before|except|unless|provided|providing|"
    r"having|given|as\s+long\s+as|in\s+case)\b"
)
_INSIDE_A_CONDITION = re.compile(
    r"\b(?:if|when|whenever|unless|where|while|until|once|as\s+long\s+as|in\s+case|providing|given\s+that|"
    r"provided\s+(?:that|the|all|it))\b|^\W*should\b"
)
#: The verbs that carry an obligation. A limit is what one of these binds; a figure outside its reach only says when.
_MODAL = re.compile(r"\b(?:shall|must|should|may|will)\b")
#: A clause whose first word the model left out: "covers for [sour lines]".
_ENDS_ON_OPENER = re.compile(
    r"\b(?:for|when|if|at|in|during|with|under|while|unless|containing|serving|having)$"
)
#: Words that open a clause saying which things a rule is about.
_CLAUSE_OPENER = re.compile(
    r"(?:that|which|who|whose|as\b|exposed|containing|serving|using|operating|installed|designed|used)\b"
)
_NON_MODAL_VERB = re.compile(r"\b(?:is|are|was|were|be|has|have|had)\b")
#: Words that open a scope between a modal and its figure. Unsure means not bound.
_OPENS_SCOPE = re.compile(
    r"\b(?:at|for|with|without|over|under|above|below|when|whenever|where|if|while|until|once|unless|during|in|on|"
    r"within|having|given|providing|provided|after|before|except|as\s+long\s+as)\b"
)
#: A cue that is also a preposition binds only straight after the verb: "shall be above 5", never "vented above 5".
_WEAK_CUES = frozenset({"above", "over", "below", "under", "exceed", "up to"})
#: What may stand between a modal and an equal figure.
_EQUAL_SPAN = frozenset(["be", "of", "a", "an", "the", "equal", "to", "set", "at"]) - {
    "at"
}
_NO_MORE_THAN_WORDS = 8
#: A figure after these, before the modal, is what the rule is scoped to: "pumps over 5 kW pressure shall ...".
_FIGURE_SCOPE = re.compile(
    r"\b(?:at|for|with|over|above|below|under|having)\b[^,]{0,40}?\d"
)
#: A sentence opening with one of these has its scope in front, comma or not.
_OPENS_WITH_SCOPE = re.compile(
    r"^\W*(?:for|at|with|without|over|having|during|under|above|below|in|on|when|whenever|if|where|while|until|once|"
    r"unless|within|after|before|except|given|providing|provided|as\s+long\s+as)\b"
)
#: Words that deny what follows. Left over once the comparator phrases that hold a negation are read, the direction of
#: the sentence is not the one its comparator word says: "shall not be above" stores no "above".
_NEGATION = re.compile(r"\b(?:not|no|never|none|neither|nor)\b")
_NEGATED_CUES = tuple(
    sorted(
        (
            c
            for cues in sc._CUES.values()
            for c in cues
            if re.search(r"\b(?:not|no)\b", c)
        ),
        key=len,
        reverse=True,
    )
)
#: A clause after a semicolon that offers another figure for the same thing.
_ALTERNATIVE_CLAUSE = re.compile(r"\b(?:or|alternatively|otherwise|whichever)\b")
#: A bracket that only says how a pressure is read, or makes a plural.
_READING_NOTE = re.compile(
    r"^\W*(?:s|es|g|a|ga|abs|absolute|gauge|typ|typical|approx)\W*$"
)
#: A number that names a document or a part of one, in a subject: not a figure the rule is scoped to.
_DOCUMENT_NUMBER = re.compile(
    r"\b(?:std|standard|section|sec|part|paragraph|para|table|figure|fig|clause|form)\.?\s+\d[\w.\-]*"
)
#: A bracket that only gives examples or says the same again.
_GLOSS = re.compile(r"^\W*(?:i\.e\.|e\.g\.|ie\b|eg\b|that\s+is\b)")
#: Two figures for one property. One stored figure would be wrong for the other.
_ALTERNATIVE = re.compile(r"\bwhichever\b|\d[^,;.()]{0,30}\bor\s+(?:\w+\s+)?\d")
_BRACKET = re.compile(r"\(([^)]*)\)")
#: A conversion: one figure, one unit word. "(360 psi)". Anything more in a bracket beside a figure is not one.
_CONVERSION = re.compile(r"^\W*-?\d[\d.,/]*\s*\S{0,10}\W*$")
_LEAD_HOLDS = re.compile(r"\b(?:shall|must|not|never|no|should|may)\b")
_LEADING_PREPOSITION = re.compile(
    r"^(?P<clause>(?:for|during|above|below|at|except|within|after|before|on|with|without|once|until|while|given|"
    r"having|providing|should|as\s+long\s+as|in\s+case)\s+[^,;:.]{3,140}),\s"
)
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


def quote_verified(quote: object, page_text: str | None) -> bool:
    """THE quote check, for version 1 and version 2 alike: the words stand on the cited page's stored text."""
    words = " ".join(str(quote or "").split())
    return (
        len(words) >= MIN_QUOTE_CHARS
        and bool(page_text)
        and quote_on_page(words, page_text)
    )


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
    nearest = _clause_in_force(pages, page, at)
    if _whole_number_heading(clause, pages[page], at, nearest):
        return None
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


def _clause_span(part: str, sentence: str) -> tuple[int, int] | None:
    """Where this part stands as a WHOLE clause of the sentence: at word boundaries, opening at a clause boundary or on a
    word that opens a scope, closing at a clause boundary, with words enough and no obligation of its own. Else None."""
    words = _unhyphen(_fold(part)).strip(" .,;:")
    text = _unhyphen(_fold(sentence))
    if len(words.split()) < 2 or re.search(r"\b(?:shall|must)\b", words):
        return None
    if not re.search(r"[a-z]", words):
        return None
    for found in re.finditer(rf"(?<!\w){re.escape(words)}(?!\w)", text):
        left, right = text[: found.start()].rstrip(), text[found.end() :].lstrip()
        at_end = not right or right[0] in ",;:.)"
        opens = (
            not left
            or left[-1] in ",;:("
            or re.search(r"\b(?:and|or|but)$", left)
            or _OPENS_SCOPE.match(words)
            or _SCOPE_ANYWHERE.match(words)
            or _CLAUSE_OPENER.match(words)
            or (at_end and _ENDS_ON_OPENER.search(left))
        )
        closes = (
            at_end
            or re.match(r"(?:and|or|but)\b", right)
            or (_MODAL.match(right) and _SCOPE_ANYWHERE.match(words))
            or (
                not left
                and re.match(
                    r"(?:the|a|an|all|any|each|these|this|no|they|it)\b", right
                )
            )
        )
        # "covers for [sour lines or wet lines] shall", or a whole subject: all of it, up to the modal, or only a part.
        whole_subject_scope = _MODAL.match(right) and (
            not left or _ENDS_ON_OPENER.search(left) or _CLAUSE_OPENER.match(words)
        )
        if (opens and closes) or whole_subject_scope:
            return found.span()
    return None


def _is_in_sentence(part: str, sentence: str) -> bool:
    words = _unhyphen(_fold(part)).strip(" .,;:")
    return bool(words) and bool(
        re.search(rf"(?<!\w){re.escape(words)}(?!\w)", _unhyphen(_fold(sentence)))
    )


def _parts(text: str) -> list[str]:
    return [p for p in text.split(";") if p.strip()]


def _main_clause(quote: str, *held: str) -> str:
    """The quote with what the rule holds as condition or exception taken out, whole clauses only, so a figure or a
    comparator word in the scope is not read as the limit's. A number joined to its unit by a hyphen stands apart here."""
    body = _unhyphen(_fold(quote))
    for text in held:
        for part in _parts(text):
            span = _clause_span(part, body)
            if span:
                before = _ENDS_ON_OPENER.sub("", body[: span[0]].rstrip())
                body = f"{before} {body[span[1] :]}"
    if (
        "not exceed" in body
    ):  # "shall not exceed X by more than 10%" states one ceiling, not a floor
        body = body.replace("by more than", " ")
    return " ".join(body.split())


def _unhyphen(text: str) -> str:
    return re.sub(r"(?<=\d)-(?=[a-z])", " ", text)


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


def _modal_binds(number, comparator: str, body: str, field: str) -> bool:
    """IS THIS FIGURE WHAT THE OBLIGATION DEMANDS? Between the last modal before it and the figure stands only a comparator
    naming it, or for "=" only the verb. A figure further off says when the rule holds, not what it demands: unsure means
    not bound. A row with no verb at all has no modal to bind it, and goes by its own cue."""
    text = numparse.fold(body).lower()
    modals = [m for m in _MODAL.finditer(text) if m.end() <= number.start]
    if not modals:
        if _MODAL.search(text) or _NON_MODAL_VERB.search(text):
            return False
        return _bound_to_comparator(number, "", comparator, body)
    modal = modals[-1]
    clause_from = modals[-2].end() if len(modals) > 1 else 0
    named = {
        w
        for w in _field_words(field)
        if w not in _GENERIC_FIELD_WORDS and w not in sc.field_naming._QUALIFIERS
    }
    if not named <= _field_words(text[clause_from:]):
        return False
    span = text[modal.end() : number.start]
    between = [
        n for n in numparse.find_numbers(text) if modal.end() <= n.start < number.start
    ]
    if between:
        return False
    if comparator == "=":
        return _equal_binds(
            span, f"{text[: modal.start()]} {text[number.end :]}", field
        )
    for start, stop in sorted(_cue_spans(comparator, span), reverse=True):
        cue, pre, post = span[start:stop], span[:start], span[stop:]
        pre = re.sub(r"\bat\s+an?\s*$", " ", pre)
        if _OPENS_SCOPE.search(post) or len(post.split()) > _NO_MORE_THAN_WORDS:
            continue
        if cue in _WEAK_CUES:
            if set(pre.split()) <= {"be", "not"}:
                return True
            continue
        if not _OPENS_SCOPE.search(pre):
            return True
    # The cue is the field's own, before the modal: "the maximum pressure shall be 200".
    return set(span.split()) <= _EQUAL_SPAN and bool(
        _cue_spans(comparator, text[: modal.start()])
    )


def _equal_binds(span: str, around: str, field: str) -> bool:
    """Only the verb stands between modal and figure ("shall be of 2 inch"), and the field is named outside that span."""
    if not set(span.split()) <= _EQUAL_SPAN:
        return False
    named = {w for w in _field_words(field) if w not in _GENERIC_FIELD_WORDS}
    return named <= _field_words(around)


def is_negated(body: str, number) -> bool:
    """Is a negation still standing before the figure, once the comparator phrases that hold one are out?"""
    text = numparse.fold(body).lower()[: number.start]
    for cue in _NEGATED_CUES:
        text = text.replace(cue, " ")
    return bool(_NEGATION.search(text))


def alternative_follows(quote: str, page: str) -> bool:
    """Does the next semicolon clause on the page offer another figure? The quote stops at the semicolon; the sentence
    goes on. A clause with its own modal is a rule of its own."""
    folded, q = _fold(page), _fold(quote).rstrip(" ;")
    at = folded.find(q)
    if at < 0:
        return False
    rest = folded[at + len(q) :].lstrip()
    if not rest.startswith(";"):
        return False
    clause = re.split(r"[.;](?:\s|$)", rest[1:], maxsplit=1)[0]
    return (
        bool(re.search(r"\d", clause))
        and not _MODAL.search(clause)
        and (
            bool(_ALTERNATIVE_CLAUSE.search(clause))
            or bool(numparse.find_numbers(clause))
        )
    )


def has_alternative(sentence: str) -> bool:
    """Two figures for one property, written out or in brackets. Enforced here: the prompt only asks."""
    text = numparse.fold(sentence).lower()
    if _ALTERNATIVE.search(text):
        return True
    return any(
        re.search(r"\d", inner) and not _CONVERSION.match(inner)
        for inner in _BRACKET.findall(text)
    )


def _unit_left_out(number, quote: str) -> bool:
    """A recognised unit right after the number in the quote, and the answer gave no unit."""
    after = numparse.fold(quote)[number.end :].split()
    return bool(after and claims.unit_dimension(after[0].strip(",.;:()")))


def _comparator_said(body: str, comparator: str, field: str) -> bool:
    """The clause's words say this comparator and nothing against it. "the maximum load shall be less than" says two, and
    the first names the property: so the words outside the field's decide, unless the field's own word points the other
    way. "=" never passes on that road: "the maximum pressure shall be 200" says a maximum."""
    if sc._comparator_says(body, comparator):
        return True
    if comparator == "=":
        return False
    words = _fold(field)
    rest = body.replace(words, " ")
    if rest == body or not sc._comparator_says(rest, comparator):
        return False
    against = {"<": ">=", "<=": ">=", ">": "<=", ">=": "<="}[comparator]
    return against not in sc.comparators_said(words)


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
    if is_negated(body, number):
        return "comparator_negated"
    if _is_range(number, unit, body) or (in_whole and _is_range(in_whole, unit, whole)):
        return "range_not_single"
    if sc.limit_scope(body, body, number.raw, unit) is None:
        return "number_and_unit_apart"
    if not _modal_binds(number, comparator, body, field):
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


def _tail_read_as_property(limit: str, unit: str, body: str, field: str) -> bool:
    """Words kept after the limit as part of the property, which the field does not name: they may be a scope. Flagged."""
    number = _written(limit, body) if limit else None
    if number is None:
        return False
    tail = sc.limit_scope(body, body, number.raw, unit)
    if not tail or re.match(r"^\W*is\s+not\s+exceeded\b", tail):
        return False
    return not _field_words(tail) <= _field_words(field)


def _is_acronym_of(token: str, before: str) -> bool:
    """ "mandatory safety rules (msrs)": a bracket that only abbreviates the words before it."""
    text = token.strip()
    for letters in {text, text.rstrip("s")}:
        words = re.findall(r"[a-z]+", before)[-len(letters) :] if letters else []
        if (
            len(letters) >= 2
            and letters.isalpha()
            and "".join(w[0] for w in words) == letters
        ):
            return True
    return False


def _bracketed_scope(
    sentence: str, head: str, has_limit: bool, field: str
) -> list[str]:
    """A scope in brackets: `limit_scope` passes over them. Any words in brackets before the modal, or anywhere in a rule
    with a figure, unless they only say how a value is read or are the field's own. After the modal of a sentence with no
    figure, only what reads as a scope ("made of Alloy 9 (UNS N1)" names the thing)."""
    out = []
    folded = _fold(sentence)
    for found in _BRACKET.finditer(folded):
        inner = found.group(1)
        if _CONVERSION.match(inner) or _READING_NOTE.match(inner):
            continue
        if _GLOSS.match(inner) or _is_acronym_of(inner, folded[: found.start()]):
            continue
        reads_as_scope = _is_scope(inner) or _SCOPE_ANYWHERE.search(inner)
        near = has_limit or _fold(f"({inner})") in _fold(head)
        if reads_as_scope or (near and not _field_words(inner) <= _field_words(field)):
            out.append(_unhyphen(_fold(inner)))
    return out


def _condition_captured(
    condition: str, sentence: str, limit, unit, body, field
) -> bool:
    """Every scope of the sentence is held by the rule. What is held has left `body`, so a scope still there is lost: after
    the limit, in the subject (a figure, a proviso), or anywhere `_is_conditional` can read one."""
    if _trailing_scope(limit, unit, body, field):
        return False
    said = _unhyphen(_fold(condition))
    plain = _core(body)
    parts = _MODAL.split(plain)
    head = " ".join(parts[:-1]) if len(parts) > 1 else parts[0]
    if _FIGURE_SCOPE.search(head) or _INSIDE_A_CONDITION.search(head):
        return False
    if len(parts) > 1 and re.search(r"(?<![\w.\-])\d", _DOCUMENT_NUMBER.sub(" ", head)):
        return False
    held_brackets = _bracketed_scope(sentence, head, bool(limit), field)
    if any(part not in said for part in held_brackets):
        return False
    if ai_requirements._is_conditional(plain):
        return False
    leading = _leading_scope(sentence)
    held = [_unhyphen(_fold(x)).strip(" ,") for x in _parts(condition)]
    if leading:
        return leading in said or any(leading.startswith(x) for x in held)
    if not _OPENS_WITH_SCOPE.match(sentence):
        return True
    start = _unhyphen(
        _fold(sentence)
    )  # an exception held from elsewhere says nothing about the scope in front
    return any(start.startswith(x) for x in held)


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


def _applies_to_on_page(applies_to: str, text: str) -> bool:
    wanted = set(field_vocabulary._tokens(applies_to))
    return bool(wanted) and wanted <= set(field_vocabulary._tokens(text))


def _scope_problem(condition: str, exception: str, whole_text: str) -> str | None:
    """A condition must be a whole clause of the sentence. An exception may stand elsewhere, but not as part of a clause."""
    if any(not _clause_span(part, whole_text) for part in _parts(condition)):
        return "condition_not_a_clause"
    if any(
        _is_in_sentence(part, whole_text) and not _clause_span(part, whole_text)
        for part in _parts(exception)
    ):
        return "condition_not_a_clause"
    return None


def _kept_rule(answer, facts: dict, flags: list[str], stated: str, text: str) -> dict:
    """The stored row of a proven rule."""
    quote, limit, unit = facts["quote"], facts["limit"], facts["unit"]
    start, end = quote_span(quote, text)
    return {
        "applies_to": facts["applies_to"],
        "applies_to_verified": _applies_to_on_page(facts["applies_to"], text),
        "condition_text": _fold(facts["condition"]) or None,
        "exception_text": _fold(facts["exception"]) or None,
        "field": facts["name"],
        "field_printed": _field_printed(quote, facts["name"], bool(limit)),
        "comparator": facts["comparator"] or None,
        "limit_text": limit or None,
        "limit_value": numparse.as_limit(limit) if limit else None,
        "unit": unit or None,
        "unit_dimension": claims.unit_dimension(unit) if unit else None,
        "strength": CONTEXT_DEPENDENT if flags else stated,
        "sentence_strength": stated,
        "context_flag": ",".join(flags) or None,
        "clause": str(answer.get("clause")).strip(),
        "page": answer["page"],
        "quote": quote,
        "quote_sha256": hashlib.sha256(quote.encode("utf-8")).hexdigest(),
        "quote_start": start,
        "quote_end": end,
    }


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
    glossed = " ".join(str(answer.get("field") or "").split())
    if not glossed:
        return None, "no_field"
    name = _without_gloss(glossed)
    limit = "" if answer.get("limit") is None else str(answer.get("limit")).strip()
    if not _names_field(quote, name, numeric=answer.get("limit") is not None):
        return None, "field_not_in_quote"
    lead_in = _lead_in(pages, page, quote)
    readable = f"{lead_in}\n{text}" if lead_in else text
    condition = " ".join(str(answer.get("condition") or "").split())
    if condition and not _condition_on_page(condition, readable):
        return None, "condition_not_on_page"
    exception = " ".join(str(answer.get("exceptions") or "").split())
    exception_lost = bool(exception) and not _condition_on_page(exception, readable)
    if exception_lost and limit:
        return None, "exception_not_on_page"
    if exception_lost:  # a sentence with no figure stands, flagged: the reworded text is not stored as read
        exception = ""
    unit = str(answer.get("unit") or "").strip()
    comparator = str(answer.get("comparator") or "").strip()
    sentence = whole_sentence(quote, text)
    if sentence is None:
        return None, "condition_not_captured"
    if lead_in and _LEAD_HOLDS.search(lead_in):
        return None, "lead_in_holds_the_obligation"
    if limit and (has_alternative(sentence) or alternative_follows(quote, text)):
        return None, "alternative_not_one_figure"
    whole = f"{lead_in} {sentence}" if lead_in else sentence
    scope = _scope_problem(condition, exception, whole)
    if scope:
        return None, scope
    if _NOT_A_LIMIT.search(sentence):
        return None, "need_not_is_not_a_limit"
    body = _main_clause(quote, condition, exception)
    if limit:
        reason = _limit_problem(limit, unit, comparator, body, sentence, name)
        if reason:
            return None, reason
    else:  # no figure: a comparator or a unit compares nothing, so the rule is its sentence
        comparator, unit = "", ""
    held = "; ".join(p for p in (condition, exception) if p)
    if not _condition_captured(held, whole, limit, unit, body, glossed):
        return None, "condition_not_captured"
    stated = strength_of(sentence)
    flags = context_flags(answer, sentence, stated, pages, tables)
    if lead_in:
        flags.append("crosses_page")
    if exception_lost:
        flags.append("exception_reworded")
    if limit and _tail_read_as_property(limit, unit, body, glossed):
        flags.append("tail_after_limit")
    if (
        limit
        and (
            flags
            or not figure_is_plain(
                whole, body, limit, unit, comparator, name, quote, text
            )
        )
    ):  # the sentence stays for the engineer; a figure from a shape code does not understand is not stored
        flags.append(FIGURE_NOT_STORED)
        limit, unit, comparator = "", "", ""
    facts = {
        "quote": quote,
        "limit": limit,
        "unit": unit,
        "applies_to": applies_to,
        "condition": condition,
        "exception": exception,
        "name": name,
        "comparator": comparator,
    }
    return _kept_rule(answer, facts, flags, stated, text), None
