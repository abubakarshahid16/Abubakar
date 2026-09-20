"""Layer 1 for STANDARDS: the model READS one sentence, Python VERIFIES it.

THE DIVISION OF LABOUR, AND IT IS NOT NEGOTIABLE. The model reads a sentence
and PROPOSES what it thinks the sentence states. It never issues a verdict,
never picks a review code and never decides compliance - those stay in
`comparison.py`, in Python, where they are reproducible. This module's whole
job is to turn a sentence into a proposal and then try very hard to throw that
proposal away.

WHY A MODEL AT ALL, when `requirements_3b.py` parses limits deterministically
and says in its own docstring that a limit depending on a language model is a
limit nobody can reproduce. Because the parser reads SHAPES, and a standard's
prose does not hold still: the same clause vocabulary produced a ceiling out of
an applicability threshold (SAES-D-001 9.2.5, `APPLICABILITY_TRIGGER`) and a
limit out of a margin between two temperatures (SAES-D-001 14.3,
`RELATIVE_LIMIT`). Each of those cost a hand-written rule. The model is better
at reading; it is not trusted to be right, which is what `accept()` is for. A
proposal that survives the gate is reproducible in the only sense that matters:
Python can re-derive every field of it from the sentence, afterwards, without
the model.

THE MODEL IS INJECTED AS A CALLABLE (prompt -> raw text), exactly as
`extraction_llm.py` does on cowork/layer1-llm-extraction. That is why this
module imports no HTTP client and why every test in `test_reader_api.py` runs
against a fake model with no transport and no API key.

ONE SENTENCE PER CALL, NOT ONE PAGE. A page-sized prompt is where the traps
below were born: the model answers about the page and a quote check can only
ask whether the words appear SOMEWHERE on it, so a value lifted from clause 9
can be attached to clause 14 and still pass. Per sentence, the quote check is
exact and rule 1 below means what it says.

SUBJECT IS MANDATORY ON A LIMIT, and this is a MEASURED FACT rather than a
preference. `comparison.match_by_containment` joins a requirement to a
datasheet value THROUGH THE SUBJECT - it is the only join there is. 313 rows
were promoted with `subject` NULL and produced ZERO new matches against a real
datasheet. A reader that returns operator/value/unit and no subject produces
rows that cannot be compared with anything, which is indistinguishable from
producing nothing at all.

WHY THIS MODULE OPENS NO SOCKET, although it is the Claude lane's reader.
`tests/test_socket_containment.py` globs the WHOLE package and fails any
module outside `SOCKET_ALLOWLIST` that constructs an HTTP client; the
allowlist is two files, each its own reviewed outbound lane, and this task may
not edit an existing file to add a third. So the request is built here -
destination, headers, body, timeout, the two egress flags and the key from the
environment - and handed to an INJECTED transport (`call_claude(...,
transport=...)`). When this lane is adopted, its client belongs in a new
`reader_transport.py` added to that allowlist with its reason, and this file
does not change. See `build_request` for what leaves and what checks it first.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from enum import Enum

from .config import model_host_of

# --------------------------------------------------------------- vocabulary

#: What the model may say a sentence IS. Deliberately four words and no more:
#: every extra option is another way for the model to be creative about a
#: question that has a right answer.
#:
#: `trigger` exists because of the trap that motivated this whole file -
#: "equipment generating noise in excess of 85 dB(A) shall submit Form
#: 7305-ENG" is PAPERWORK, not a ceiling. Read as a limit it fails a
#: compliant submittal at 90 dB(A) for exceeding a limit the standard never
#: states.
KINDS = ("limit", "statement", "table", "trigger")

#: The only operators a limit may carry. No "approximately", no "between":
#: a comparator this module cannot verify against the quote is a comparator
#: `comparison.compare` would have to guess at.
OPERATORS = ("<=", ">=", "<", ">", "=")

#: The model's word -> the type this codebase already stores
#: (`requirements_3b.REQUIREMENT_TYPES`, `APPLICABILITY_TRIGGER`). Kept as a
#: table rather than as a second vocabulary: the reader must not be able to
#: invent a requirement type the rest of the system has never seen, and a
#: promotion step can read this instead of writing its own `if`.
KIND_TO_REQUIREMENT_TYPE = {
    "limit": "numeric_limit",
    "statement": "statement",
    "table": "table_value",
    "trigger": "applicability_trigger",
}


class Reason(Enum):
    """Why a proposal was thrown away. A NAMED REASON, ALWAYS.

    A plain `Enum` whose members carry the stored string, and every caller
    uses `.value`: the alternative, a `str` mixin, makes `reason == "..."`
    work by accident and lets a raw member reach JSON, where what gets
    written depends on the Python version.

    Silent discarding is the failure this enum exists to prevent: a caller
    must be able to report "N proposals rejected: 3 quote-not-found, 1
    value-not-in-quote", because "the model found nothing" and "the model
    invented four things and we dropped them" are different facts about a
    standard and only one of them is a reason to go and look at the clause.
    """

    #: The model's answer was not the JSON that was asked for. Call-level, not
    #: per-proposal: nothing was read, so nothing can be named.
    MODEL_MALFORMED = "model_malformed"
    #: Rule 1. The quote does not appear in the sentence, whitespace-folded.
    #: This is the fabrication catch: an imagined rule has no true quote.
    QUOTE_NOT_IN_SENTENCE = "quote_not_in_sentence"
    #: Rule 2. The number is not inside the words the model says it read the
    #: number from.
    VALUE_NOT_IN_QUOTE = "value_not_in_quote"
    #: Rule 3. Same, for the subject.
    SUBJECT_NOT_IN_QUOTE = "subject_not_in_quote"
    #: A limit with no subject - unmatchable by `match_by_containment`, which
    #: is the 313-rows measurement in the module docstring.
    SUBJECT_MISSING = "subject_missing"
    #: A limit with no number is not a limit; `requirements_3b` calls that
    #: shape "a limit nobody recorded" and keeps it as a statement.
    VALUE_MISSING = "value_missing"
    OPERATOR_MISSING = "operator_missing"
    OPERATOR_UNKNOWN = "operator_unknown"
    #: Rule 4. The direction disagrees with the sentence's own words -
    #: "minimum ... 370" read as `= 370`, or "shall not exceed 90" read as
    #: `>= 90`.
    OPERATOR_CONTRADICTS_QUOTE = "operator_contradicts_quote"
    #: The sentence's obligation is to submit, obtain or refer - its number is
    #: a threshold of applicability, so a `limit` proposal about it is refused
    #: whatever else is true of it.
    LIMIT_ON_TRIGGER_SENTENCE = "limit_on_trigger_sentence"
    KIND_UNKNOWN = "kind_unknown"
    #: Rule 5. Two runs of the same sentence did not agree.
    MODEL_UNSTABLE = "model_unstable"


# ------------------------------------------------------------------- prompt

#: THE TRAPS ARE IN THE PROMPT BECAUSE THEY WERE PAID FOR IN THE CORPUS.
#:
#: Each numbered rule below is a defect this project hit in the last 48 hours,
#: stated to the model in the words of the clause that caused it. The gate
#: still checks all of them - a prompt is a request and `accept()` is the
#: enforcement - but asking for the right thing is cheaper than rejecting the
#: wrong thing twice and reporting a sentence as unread.
PROMPT = """You are reading ONE SENTENCE from an engineering standard.

Say what this sentence states, as JSON only:
{"proposals": [{"kind": ..., "operator": ..., "value": ..., "unit": ...,
                "subject": ..., "quote": ...}]}

kind is exactly one of:
  limit     - a requirement on a quantity that a submitted design must meet
  statement - an obligation with no quantity in it
  table     - the sentence points at a table for the value
  trigger   - the number is a THRESHOLD OF APPLICABILITY: if the number is
              exceeded, some OTHER obligation applies - submit a form, obtain
              approval, follow another standard. The sentence limits nothing.

operator is one of <= >= < > = and is given ONLY when kind is limit.

RULES THAT ARE OFTEN GOT WRONG:
1. "equipment generating noise in excess of 85 dB(A) shall submit Form
   7305-ENG" is a trigger, NOT a limit. The obligation is paperwork. Nothing
   is forbidden from exceeding 85.
2. "the minimum cement content shall be 370 kg/m3" is >= 370, NEVER = 370.
   A minimum is a floor; a design with 400 meets it.
3. "shall not exceed 90 dB(A)" is <= 90. Read the negation.
4. "The allowable concrete bearing stress shall be 8,300 kPa" really is = .
   Do not turn a plain stated value into an inequality.

subject is WHAT THE RULE IS ABOUT, copied from the sentence - "cement
content", "noise level". It is MANDATORY on a limit: without it the value
cannot be matched to anything in a submittal and the whole row is discarded.

quote is the EXACT words of the sentence you read the value, the subject and
the direction from, copied character for character. Every one of them must be
inside the quote. Never write a quote that is not in the sentence.

Answer with JSON and nothing else.

SENTENCE:
"""


def build_prompt(sentence: str) -> str:
    """The prompt for one sentence. A function, not a format string at the
    call site, so the sentence is appended in exactly one place."""
    return PROMPT + sentence.strip()


# -------------------------------------------------------- text, folded

def _fold(text: str) -> str:
    """Whitespace-insensitive, case-insensitive form.

    A clause arrives from `chunker` broken across lines and hyphenated by the
    PDF; the model answers in one line. Folding is what lets rule 1 be exact
    about the WORDS without being exact about the typesetting.
    """
    return re.sub(r"\s+", " ", str(text)).strip().lower()


#: A thousands separator INSIDE a number: the 8,300 of "shall be 8,300 kPa".
#: The bare-equality worked case is written that way in the standard and the
#: model habitually answers "8300", so without this rule 2 rejects a true
#: reading of a real clause.
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")

#: Any number in a piece of text, comma-separators already removed.
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def _fold_numbers(text: str) -> str:
    return _THOUSANDS.sub("", _fold(text))


def _contains(haystack: str, needle: str) -> bool:
    """Whole-word containment on already-folded text.

    WHOLE WORDS, for `match_by_containment`'s reason: "design pressure" must
    not be found inside "redesign pressure". The lookarounds are used instead
    of `\\b` because a subject or a unit can end in a bracket - "noise level
    dB(A)" - where `\\b` asks about the wrong character.
    """
    if not needle:
        return False
    return re.search(r"(?<!\w)" + re.escape(needle) + r"(?!\w)", haystack) is not None


def _value_in_quote(value, quote: str) -> bool:
    """Rule 2, tolerant of printing and of nothing else.

    Two spellings of the same number are the same number: "8,300" in the
    standard and "8300" from the model. A DIFFERENT number is a different
    number, and that is the case this rule exists to catch - the model that
    quoted a 23.55 row and reported 99.9.
    """
    quote_folded = _fold_numbers(quote)
    value_folded = _fold_numbers(value)
    if _contains(quote_folded, value_folded):
        return True
    # Numeric equality as a last resort, so "370.0" against "370" is not read
    # as an invention. Only for values that are a bare number: a comparison
    # this module cannot do arithmetic on stays a string comparison.
    try:
        wanted = float(value_folded)
    except ValueError:
        return False
    return any(float(found) == wanted for found in _NUMBER.findall(quote_folded))


# ------------------------------------------------------- direction and shape

def _phrases(*spellings: str) -> re.Pattern:
    """One pattern from literal phrases, spaces made whitespace-tolerant."""
    return re.compile("|".join(
        re.escape(p).replace(r"\ ", r"\s+").replace(" ", r"\s+")
        for p in spellings))


#: WORDS THAT MEAN "AT MOST". The negated spellings come first and absorb the
#: negation, on `requirements_3b._OPERATOR`'s precedent: "shall not be less
#: than 45 m" was once read as `< 45` by a pattern that saw the bare "less
#: than" and missed the "not" four characters earlier. A flipped comparator is
#: a compliant design reported non-compliant.
_CEILING = _phrases(
    "shall not exceed", "must not exceed", "may not exceed", "not to exceed",
    "not be exceeded", "not exceed", "not be more than", "not more than",
    "no more than", "not be greater than", "not greater than",
    "no greater than", "not be higher than", "not higher than",
    "not be in excess of", "at most", "maximum", "max.",
)

#: WORDS THAT MEAN "AT LEAST", including the trap this file was asked for:
#: "the minimum cement content shall be 370 kg/m3" is `>= 370`. Stored as
#: equality it fails every compliant submittal that exceeds the minimum, which
#: is most of them.
_FLOOR = _phrases(
    "shall not be less than", "must not be less than", "not be less than",
    "not less than", "no less than", "not be lower than", "not lower than",
    "not fall below", "not be smaller than", "at least", "minimum", "min.",
)

#: A SENTENCE WHOSE OBLIGATION IS PAPERWORK OR A CROSS-REFERENCE.
#:
#: Two worked cases, both real. "equipment generating noise in excess of 85
#: dB(A) shall submit Form 7305-ENG" - the 85 governs who files a form.
#: SAES-D-001 9.2.5, "temperatures greater than 260 C shall be in accordance
#: with PIP VEFV1100" - the 260 says which document applies; read as `> 260`
#: it reported a contractor NON_COMPLIANT for NOT exceeding 260 C.
#:
#: The pattern asks about the OBLIGATION, never about the threshold words:
#: "in excess of" and "greater than" appear in both kinds of sentence, which
#: is exactly why they cannot be the test.
_TRIGGER_OBLIGATION = re.compile(
    r"(?:shall|must|is\s+to|are\s+to|will)\s+(?:be\s+)?"
    r"(?:submit|submitted|obtain|obtained|provide\s+notification|notify|"
    r"register|apply\s+for|request\s+approval|be\s+approved\s+by|"
    r"be\s+referred|refer|comply\s+with\s+the\s+requirements\s+of|"
    r"in\s+accordance\s+with|per)\b"
    r"|\bform\s+\d"
)


def direction_of_quote(quote: str) -> str | None:
    """`"<="`, `">="`, or None when the words state no direction.

    ONLY THE DIRECTION, never the strictness. "not exceed" is `<=` and "less
    than" is `<`, but both are ceilings, and a gate that insisted on the
    strict form would reject true readings over a distinction no submittal
    outcome turns on. Direction is the one that flips a verdict.

    A sentence carrying BOTH families of words - "the minimum cover shall not
    exceed" - is ambiguous to a phrase test, so this returns None and rule 4
    simply does not fire. The other four rules still do. Guessing here would
    be the module deciding what a clause means, which is the one thing it is
    not allowed to do.
    """
    folded = _fold(quote)
    ceiling = _CEILING.search(folded) is not None
    floor = _FLOOR.search(folded) is not None
    if ceiling == floor:
        return None
    return "<=" if ceiling else ">="


def looks_like_a_trigger(sentence: str) -> bool:
    """Is the sentence's obligation paperwork or a cross-reference."""
    return _TRIGGER_OBLIGATION.search(_fold(sentence)) is not None


# -------------------------------------------------------------------- parse

def parse_response(raw: str) -> tuple[list[dict], str | None]:
    """Strict parse. Anything malformed yields no proposals AND A REASON.

    A reason, never a guess: `extraction_llm.parse_response`'s rule, kept,
    because the alternative - repairing half-JSON - is the module inventing
    content and calling it the model's.
    """
    try:
        body = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return [], Reason.MODEL_MALFORMED.value
    # A single proposal answered as a bare object is common enough to accept
    # deliberately rather than to lose as malformed: one sentence usually has
    # one rule in it, and the model writes what the sentence looks like.
    if isinstance(body, dict) and "proposals" not in body and "kind" in body:
        body = {"proposals": [body]}
    proposals = body.get("proposals") if isinstance(body, dict) else None
    if not isinstance(proposals, list):
        return [], Reason.MODEL_MALFORMED.value
    out = []
    for p in proposals:
        if not isinstance(p, dict) or not p.get("quote"):
            # No quote is not a rejection with a reason - there is nothing to
            # report. An entry with no quote names no words in the standard,
            # so there is no proposal here to keep or to count.
            continue
        out.append({
            "kind": str(p.get("kind") or "").strip().lower(),
            "operator": (str(p["operator"]).strip()
                         if p.get("operator") not in (None, "") else None),
            "value": p.get("value"),
            "unit": p.get("unit"),
            "subject": (str(p["subject"]).strip()
                        if p.get("subject") not in (None, "") else None),
            "quote": str(p["quote"]),
        })
    return out, None


# --------------------------------------------------------------- the gate

def accept(proposals: list[dict], sentence: str) -> dict:
    """THE GATE. A proposal is kept only when ALL of these hold:

      1. the quote appears in the sentence, whitespace-folded
      2. the value appears inside the quote
      3. the subject appears inside the quote
      4. the operator's direction agrees with the quote's own words
      5. (in `read_sentence`) two runs of the sentence agreed

    Rules 1-3 are one idea in three places: EVERY FIELD MUST BE RE-DERIVABLE
    FROM THE SENTENCE BY SOMETHING THAT CANNOT IMAGINE. A fabricated rule has
    no true quote to give, and a real quote with a substituted number fails
    rule 2. Rule 4 is the flipped-comparator defect, which is worse than a
    missed rule because it produces a confident wrong verdict against a
    contractor.

    Returns `{"accepted": [...], "rejected": [...], "counts": {reason: n}}`.
    Every rejected proposal carries `reason`, so the caller can say what was
    dropped and why instead of reporting a quiet zero.
    """
    folded_sentence = _fold(sentence)
    trigger_shaped = looks_like_a_trigger(sentence)
    accepted: list[dict] = []
    rejected: list[dict] = []

    def drop(proposal: dict, reason: Reason) -> None:
        rejected.append({**proposal, "reason": reason.value})

    for p in proposals:
        if p["kind"] not in KINDS:
            drop(p, Reason.KIND_UNKNOWN)
            continue
        quote = _fold(p["quote"])
        if not quote or not _contains(folded_sentence, quote):
            drop(p, Reason.QUOTE_NOT_IN_SENTENCE)
            continue
        if p["kind"] != "limit":
            # A statement, a table pointer or a trigger carries no verdict
            # arithmetic, so it needs no operator. Its value and subject are
            # still checked when given: an invented number on a trigger would
            # be promoted into the corpus as a threshold.
            if p.get("value") not in (None, "") and not _value_in_quote(p["value"], quote):
                drop(p, Reason.VALUE_NOT_IN_QUOTE)
                continue
            if p.get("subject") and not _contains(quote, _fold(p["subject"])):
                drop(p, Reason.SUBJECT_NOT_IN_QUOTE)
                continue
            accepted.append(p)
            continue
        if trigger_shaped:
            # THE FORM 7305-ENG CASE. The sentence's obligation is to submit
            # or to go and read another document; its number is a threshold of
            # applicability. Read as a ceiling it fails a compliant submittal,
            # so a `limit` here is refused on the sentence's shape alone -
            # before its value is even looked at.
            drop(p, Reason.LIMIT_ON_TRIGGER_SENTENCE)
            continue
        if p.get("value") in (None, ""):
            drop(p, Reason.VALUE_MISSING)
            continue
        if not p.get("operator"):
            drop(p, Reason.OPERATOR_MISSING)
            continue
        if p["operator"] not in OPERATORS:
            drop(p, Reason.OPERATOR_UNKNOWN)
            continue
        if not p.get("subject"):
            # 313 rows promoted with subject NULL matched NOTHING on a real
            # datasheet. A limit without a subject is not a weaker row, it is
            # an unusable one.
            drop(p, Reason.SUBJECT_MISSING)
            continue
        if not _value_in_quote(p["value"], quote):
            drop(p, Reason.VALUE_NOT_IN_QUOTE)
            continue
        if not _contains(quote, _fold(p["subject"])):
            drop(p, Reason.SUBJECT_NOT_IN_QUOTE)
            continue
        stated = direction_of_quote(quote)
        if stated is not None and _direction(p["operator"]) != stated:
            drop(p, Reason.OPERATOR_CONTRADICTS_QUOTE)
            continue
        accepted.append(p)
    return {"accepted": accepted, "rejected": rejected,
            "counts": rejection_counts(rejected)}


def _direction(operator: str) -> str | None:
    """The side of the number a comparator allows. `=` allows neither, which
    is why "minimum ... shall be 370" reported as `=` is a contradiction and
    not merely a loss of precision."""
    if operator in ("<=", "<"):
        return "<="
    if operator in (">=", ">"):
        return ">="
    return None


def rejection_counts(rejected: list[dict]) -> dict:
    """`{reason: n}`, for the sentence a caller has to be able to write:
    "12 proposals rejected: 3 quote-not-in-sentence, 1 value-not-in-quote"."""
    counts: dict = {}
    for r in rejected:
        counts[r["reason"]] = counts.get(r["reason"], 0) + 1
    return counts


# ------------------------------------------------------------ the two runs

def _identity(p: dict) -> tuple:
    """What two runs must agree ON.

    The FIELDS THAT CHANGE A VERDICT, folded: kind, direction, number,
    unit, subject. Not the quote - two runs quoting the same rule with
    different amounts of surrounding text agree about the standard, and
    dropping that pair would discard true readings for a difference no
    comparison can see.
    """
    value = p.get("value")
    return (
        p.get("kind"),
        p.get("operator"),
        _fold_numbers(value) if value not in (None, "") else "",
        _fold(p.get("unit") or ""),
        _fold(p.get("subject") or ""),
    )


def read_sentence(sentence: str, model_call, second_call=None) -> dict:
    """One sentence through the model TWICE and then through the gate.

    RULE 5, AND IT IS NOT OPTIONAL. `second_call` defaults to calling the same
    model again rather than to skipping the check: a proposal only one run
    produced is a proposal the sentence does not compel, and the matcher tier
    already learned this - `settings.match_seed` is pinned precisely so that
    "asked twice, answered twice the same" means something. Determinism is
    the caller's to arrange (temperature 0, a fixed seed); this is what checks
    that the arrangement held.

    Returns the `accept()` shape, plus `error` when the model's answer was not
    JSON. An unstable proposal is REPORTED, with `model_unstable`, never
    dropped quietly.
    """
    first, err = parse_response(model_call(build_prompt(sentence)))
    if err:
        return {"accepted": [], "rejected": [], "counts": {}, "error": err}
    again = second_call if second_call is not None else model_call
    second, err2 = parse_response(again(build_prompt(sentence)))
    if err2:
        return {"accepted": [], "rejected": [], "counts": {}, "error": err2}
    seen = {_identity(p) for p in second}
    stable = [p for p in first if _identity(p) in seen]
    unstable = [{**p, "reason": Reason.MODEL_UNSTABLE.value}
                for p in first if _identity(p) not in seen]
    gate = accept(stable, sentence)
    gate["rejected"].extend(unstable)
    gate["counts"] = rejection_counts(gate["rejected"])
    return gate


def read_sentences(sentences, model_call, second_call=None) -> dict:
    """Every sentence, with the per-sentence results kept together.

    Each accepted and rejected proposal carries `sentence`, because a reason
    without the clause it belongs to cannot be acted on: "3 quote-not-in-
    sentence" tells a reviewer nothing until it says WHICH clauses.
    """
    accepted: list[dict] = []
    rejected: list[dict] = []
    errors: list[dict] = []
    for sentence in sentences:
        out = read_sentence(sentence, model_call, second_call)
        if out.get("error"):
            errors.append({"sentence": sentence, "error": out["error"]})
            continue
        accepted.extend({**p, "sentence": sentence} for p in out["accepted"])
        rejected.extend({**p, "sentence": sentence} for p in out["rejected"])
    return {"accepted": accepted, "rejected": rejected,
            "counts": rejection_counts(rejected), "errors": errors}


def requirement_type_of(proposal: dict) -> str | None:
    """The stored requirement type for an ACCEPTED proposal, or None.

    A table lookup and nothing else. The reader may not invent a type the
    schema has never seen (`schemas.RequirementType`), and it may not decide
    anything else about the row either.
    """
    return KIND_TO_REQUIREMENT_TYPE.get(proposal.get("kind"))


# ------------------------------------------------------- the outbound lane

class ReaderRefused(RuntimeError):
    """The request was not built. Never a fallback, never a silent no-op:
    `market_transport`'s rule, for the same reason - a caller that believes it
    asked the model and got nothing back reads a configuration mistake as a
    standard with no requirements in it."""


#: THE KEY IS READ FROM THE ENVIRONMENT AND FROM NOWHERE ELSE. No default, no
#: file, nothing in the repository: `.gitleaks.toml` exists because a key in a
#: source tree is a key that has been published.
API_KEY_ENV = "ANTHROPIC_API_KEY"

DEFAULT_BASE_URL = "https://api.anthropic.com"
MESSAGES_PATH = "/v1/messages"
#: Pinned, not "latest". An API version that moves on its own changes the
#: response shape under a deployment nobody touched.
ANTHROPIC_VERSION = "2023-06-01"


def _flag(env, name: str) -> bool:
    return str(env.get(name, "")).strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class ReaderSettings:
    """This lane's settings, READ FROM THE ENVIRONMENT, OFF BY DEFAULT.

    WHY THEY ARE NOT IN `config.Settings`: this task may add files and may not
    edit one, and `config.py` is an existing file. They belong there when the
    lane is adopted - the names are chosen to move across unchanged, and
    `Settings` already ignores unknown environment keys, so adding them later
    breaks nothing that is deployed now.

    TWO FLAGS, ON THE `market_live_enabled` / `market_allow_public_egress`
    PRECEDENT. One says "the feature is built and switched on", the other says
    "this deployment permits document text to leave this machine". Both must
    be true before a request is built, so opening this lane cannot be one
    careless edit - and it matters more here than for the market lane, because
    what leaves is CLAUSE TEXT FROM THE CLIENT'S STANDARDS, not an approved
    search phrase. A fresh install calls nothing.
    """

    enabled: bool = False
    allow_public_egress: bool = False
    base_url: str = DEFAULT_BASE_URL
    #: The one destination. Checked with a real URL parser
    #: (`config.model_host_of`), never a string split - `evil.test?@api.
    #: anthropic.com/` has the authority `evil.test` and a hand-parser reads
    #: the other one.
    allowed_hosts: tuple = ("api.anthropic.com",)
    model: str = "claude-sonnet-4-5"
    #: One sentence in, one small JSON object out. A large budget here buys
    #: nothing and pays for a model that decided to explain itself.
    max_tokens: int = 512
    #: Determinism is rule 5's precondition, so temperature is fixed at the
    #: request and is not a setting anyone can raise.
    timeout_seconds: float = 30.0
    extra_headers: dict = field(default_factory=dict)

    @classmethod
    def from_env(cls, env=None) -> ReaderSettings:
        env = os.environ if env is None else env
        return cls(
            enabled=_flag(env, "STANDARDS_READER_ENABLED"),
            allow_public_egress=_flag(env, "STANDARDS_READER_ALLOW_PUBLIC_EGRESS"),
            base_url=env.get("STANDARDS_READER_BASE_URL") or DEFAULT_BASE_URL,
            model=env.get("STANDARDS_READER_MODEL") or cls.model,
            timeout_seconds=float(env.get("STANDARDS_READER_TIMEOUT_SECONDS") or 30.0),
        )


def build_request(prompt: str, *, cfg: ReaderSettings | None = None, env=None) -> dict:
    """The whole outbound request, built and CHECKED, but not sent.

    Returns `{"url", "headers", "body", "timeout"}`. Raises `ReaderRefused`
    unless every one of these holds: the feature is on, this deployment
    permits egress, the destination is https and its host - parsed, not split
    - is in `allowed_hosts`, and a key is present in the environment.

    `temperature` is 0 and is not configurable: two runs of a sentence must be
    able to agree (rule 5), and a sampler nobody pinned makes that check a
    coin toss tossed twice - the lesson `settings.match_seed` was written for.
    """
    cfg = ReaderSettings.from_env(env) if cfg is None else cfg
    env = os.environ if env is None else env
    if not cfg.enabled:
        raise ReaderRefused(
            "the standards reader is switched off (STANDARDS_READER_ENABLED)")
    if not cfg.allow_public_egress:
        raise ReaderRefused(
            "this deployment does not permit standards text to leave the "
            "machine (STANDARDS_READER_ALLOW_PUBLIC_EGRESS)")
    if not cfg.base_url.startswith("https://"):
        raise ReaderRefused(f"reader base URL is not https: {cfg.base_url!r}")
    host = model_host_of(cfg.base_url)
    if host not in cfg.allowed_hosts:
        raise ReaderRefused(
            f"reader host {host!r} is not in allowed_hosts {cfg.allowed_hosts!r}")
    api_key = str(env.get(API_KEY_ENV) or "").strip()
    if not api_key:
        raise ReaderRefused(f"no API key in the environment ({API_KEY_ENV})")
    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
        **cfg.extra_headers,
    }
    body = {
        "model": cfg.model,
        "max_tokens": cfg.max_tokens,
        "temperature": 0,
        "messages": [{"role": "user", "content": prompt}],
    }
    return {"url": cfg.base_url.rstrip("/") + MESSAGES_PATH,
            "headers": headers, "body": body, "timeout": cfg.timeout_seconds}


def response_text(payload) -> str:
    """The model's text out of a Messages response.

    Returns "" for any shape that carries none, which `parse_response` then
    reports as `model_malformed`: an empty answer and an unparseable one are
    both "the model said nothing usable", and neither may become a proposal.
    """
    blocks = (payload or {}).get("content") if isinstance(payload, dict) else None
    if not isinstance(blocks, list):
        return ""
    return "".join(
        str(b.get("text") or "") for b in blocks
        if isinstance(b, dict) and b.get("type") == "text")


def call_claude(prompt: str, *, transport, cfg: ReaderSettings | None = None, env=None) -> str:
    """One Messages call through an INJECTED transport.

    `transport(url, headers=..., body=..., timeout=...) -> dict`. The socket
    is the caller's because no module outside `SOCKET_ALLOWLIST` may hold an
    HTTP client (see the module docstring); this function owns everything
    else, so the destination check and the two egress flags cannot be skipped
    by whoever writes that client.
    """
    request = build_request(prompt, cfg=cfg, env=env)
    payload = transport(request["url"], headers=request["headers"],
                        body=request["body"], timeout=request["timeout"])
    return response_text(payload)


def model_call_via(transport, *, cfg: ReaderSettings | None = None, env=None):
    """A `model_call` for `read_sentence`, closed over a real transport.

    This is the seam `extraction_llm.py` established and the reason both
    modules test without a network: everything above this line takes a
    callable, and only this line knows there is an API at all.
    """
    def model_call(prompt: str) -> str:
        return call_claude(prompt, transport=transport, cfg=cfg, env=env)
    return model_call


__all__ = [
    "API_KEY_ENV",
    "KINDS",
    "KIND_TO_REQUIREMENT_TYPE",
    "OPERATORS",
    "PROMPT",
    "ReaderRefused",
    "ReaderSettings",
    "Reason",
    "accept",
    "build_prompt",
    "build_request",
    "call_claude",
    "direction_of_quote",
    "looks_like_a_trigger",
    "model_call_via",
    "parse_response",
    "read_sentence",
    "read_sentences",
    "rejection_counts",
    "requirement_type_of",
    "response_text",
]
