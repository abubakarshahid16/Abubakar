"""ONLINE SEARCH FOR RULE BOOKS WE DO NOT HOLD (owner decision, 17 Nov 2026, #1584 comment 6927034366, pending his confirmation
there: online search approved for standards we do not hold, switched off for now, and no client document goes outside without
approval).

WHAT IT DOES. After an AI review ends, for each rule book the review listed as not held (`agent_review_missing_book`), it asks Claude,
with Anthropic's server-side web search tool, for the PUBLIC catalogue entry of that standard: its full title, its latest edition and
year, its publisher and one page on the publisher's own site. The answer is SHOWN, never used: it is a line on the page and a column on
the one CRS file's sheet "Rule books not held", headed "Found online (not verified, book not held)". It is never a rule quote, never a
clause, never a verdict input, never a point, and the review's counts do not change.

WHAT LEAVES THE MACHINE. Only the public name of a standard, rebuilt by code from a closed set of word shapes (`clean_name`: a
publisher family such as API or ISO first, then designation numbers, part and section words, roman numerals, years and edition
words); a name with any other word, a tag or a document number is refused and nothing is sent for it. Never document text, never a
file name, never a page, never the paper's name. The request carries a fixed system sentence, "Standard: <name>", and the web search
tool limited to the publishers' own sites (`PUBLISHER_DOMAINS`).

THE NAMES COME FROM THE PAPER (review R-1853, finding 1), so they go only where the paper itself already went:
  * the search runs only when this run's AI reviewer had at least one Claude call ANSWERED (`paper_went_to_claude`: a settled,
    not refused, not cached ledger line of the run under the reviewer's step). A run kept on this computer, refused, halted or on
    the local model searches nothing;
  * every request is declared as carrying THE PAPER (`claude_approved.carrying([paper])` inside `reviewing(run)`), so the block
    list, the contract check and the approved list are asked again at send time, as for the paper's own calls. A paper refused now
    (blocked after the plan, a contract at send time, not approved) sends nothing.
The pre-start plan says it (`plan_note`, in `GET /api/reviews/plan` under `documents.web_search`).

THE LANE. The existing Claude lane only: `agent_claude._request` (the provider switch, both egress flags, https, the allowed host, the
key) and `agent_claude._send_once` (`claude_spend.metered`: reserve, send through `reader_transport`, settle). No new company, no new
key, no new socket module. The one cache door (`claude_spend.answer_on_file`) is asked first: a readable answer stored for the same
request is used at USD 0 with nothing sent, and only a readable answer is kept (`claude_spend.keep_answer`).

MONEY. One request per missing book, at most `MAX_PER_RUN` a run, at most `settings.standards_web_search_usd_per_run` a run and at
most `TIME_LIMIT_SECONDS` of wall time a run. The web search tool has its own price per search, and its results come back as input
tokens that the prompt does not show, so `claude_spend.metered`'s worst case (the prompt and `max_tokens`) is not enough: before each
request a second reservation under the same step holds the rest (`extra_worst_usd`, its formula there). It is settled to the searches
the answer reports, released when the API provably did no work, and charged at its worst case on any other path, never left open.
So the run, step, day and month caps in `claude_spend` hold; the run's spend record (`claude_spend_report.record_run`) and its `usd`
include the search, its part stated in the CRS file (`standards_web_search_money`, which also closes holds a process that ended
left open). A 4xx costs nothing.

OFF (`settings.standards_web_search_enabled`, default False): nothing is asked, nothing is created, the page, the plan and the CRS
file are byte for byte as before. No document text, no answer text and no key is logged; the log says counts and outcomes only.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import time
import unicodedata
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from . import agent_claude, claude_spend
from . import standards_web_search_money as money
from .config import settings
from .db import connect

log = logging.getLogger(__name__)

STEP = "standards_web_search"
#: A cheap model for a cheap look-up (owner, 16 Nov: cheap models for cheap work). It takes the basic web search tool.
MODEL = "claude-haiku-5-5"
TOOL_TYPE = "web_search_20250305"
TOOL_NAME = "web_search"
MAX_USES = 2
MAX_TOKENS = 1024
MAX_PER_RUN = 12
NAME_LIMIT = 60
#: The wall time one run may spend searching (review R-1853, finding 6), and the wait for one answer within it.
TIME_LIMIT_SECONDS = 180.0
REQUEST_TIMEOUT_SECONDS = 60.0
#: Anthropic's list price of the web search tool, USD 10 per 1,000 searches: an ESTIMATE, the invoice is the truth. Reserved at
#: twice that, so a price change cannot break a cap; settled at the list price.
USD_PER_SEARCH = 0.01
USD_PER_SEARCH_WORST = 0.02
#: The input tokens one search's results may add, generously.
SEARCH_RESULT_TOKENS_WORST = 50_000
TABLE = "standards_web_search"
COLUMN = "Found online (not verified, book not held)"
NOT_VERIFIED = "found online, not verified; the book is not held"
#: The row of the CRS file's "How it was reviewed" that states the search's cost apart from the AI review's (finding 6).
COST_ROW = "Online search for rule books not held: cost (USD, not in the AI review's cost)"  # fmt: skip

#: Publisher families whose standards are public and sold by their publisher; the first word of a name that may leave.
FAMILIES = frozenset(
    {"API", "ASME", "ISO", "NACE", "AMPP", "ASTM", "IEC", "EN", "BS", "ANSI", "MSS", "AWS", "NFPA", "IEEE"}
)  # fmt: skip
#: Part, section, division and kind words a standard's public name may carry.
QUALIFIERS = frozenset(
    {"PART", "SECTION", "SEC", "DIVISION", "DIV", "STD", "RP", "SPEC", "MR", "TM", "SP", "BPVC", "PTC", "TR", "TS"}
)  # fmt: skip
#: Edition words.
EDITION_WORDS = frozenset({"EDITION", "ED"})
#: The two-letter prefixes a designation may carry (NACE MR0175, NACE TM0177, NACE SP0472, API RP 520 written RP520).
DESIGNATION_PREFIXES = ("MR", "TM", "SP", "RP", "TR", "TS")
#: The shapes of a designation: numbers with dots and dashes (610, 15156-3, 1.1, 16.5, 520-I, 9001-2015); one letter and numbers
#: (B31.3, A105, B16.5-2017); an allowed two-letter prefix and numbers (MR0175); an ordinal (7th). A token with three or more
#: letters mixed with digits (a tag, a document number: ZQ4821-ABC-I-07, QXV4821, ZQ4821.07) matches none.
_NUMBERS = r"[0-9]{1,6}(?:\.[0-9]{1,3}){0,3}(?:-(?:[0-9]{1,4}|[IVX]{1,4}))?[A-Z]?"
_DESIGNATION = re.compile(
    rf"(?:{_NUMBERS}|[A-Z]{_NUMBERS}|(?:{'|'.join(DESIGNATION_PREFIXES)})[0-9]{{2,6}}(?:-[0-9]{{1,4}})?|[0-9]{{1,2}}(?:ST|ND|RD|TH))"
)
_ROMAN = re.compile(r"(?=[IVX])X?(IX|IV|V?I{0,3})")
#: The publishers' own sites: the search is limited to them and a URL is kept only on one of them (or a sub-domain).
PUBLISHER_DOMAINS = (
    "api.org", "asme.org", "iso.org", "ampp.org", "nace.org", "astm.org", "iec.ch", "ieee.org", "nfpa.org", "aws.org",
    "msshq.org", "ansi.org", "bsigroup.com", "cen.eu",
)  # fmt: skip

SYSTEM = (
    "You look up the public catalogue entry of one engineering standard on its publisher's own website. Use the web search tool at "
    "most twice. Reply with ONE JSON object and no other text: "
    '{"title": string or null, "latest_edition": string or null, "year": integer or null, "publisher": string or null, '
    '"url": string or null}. The url is one page on the publisher\'s own site. Use null for anything you did not find there. '
    "Do not guess."
)

FOUND, NOTHING, INCOMPLETE, NOT_SEARCHED, FAILED = (
    "found",
    "nothing found",
    "search incomplete",
    "not searched",
    "search failed",
)
NOT_PUBLIC = "not on the app's own list of public standards, so it was not sent"
SEARCHED_ONCE = "searched once already in this review under the same name"
CAP_WORDS = "the USD limit for online search in this review was reached"
COUNT_WORDS = f"at most {MAX_PER_RUN} rule books are searched in one review"
TIME_WORDS = (
    f"search stopped: time limit ({int(TIME_LIMIT_SECONDS // 60)} minutes a review)"
)
NOT_SENT_WORDS = (
    "this review sent nothing to Claude, so no name taken from the paper is sent either"
)
UNREADABLE_WORDS = "the answer could not be read"
#: Names the reading of the answer, so a change to it misses the answers stored before (`claude_spend.answer_on_file`).
ANSWER_VERSION = "standards-web-search-answer-1"
STORED_WORDS = "from the stored answer of an earlier search: nothing sent, USD 0"
#: A stored answer older than this is not used ("latest edition" changes with time): the name is searched again, paid, capped.
MAX_STORED_AGE_DAYS = 90
PLAN_WORDS = (
    "After the AI review, the public names of rule books this paper cites that the library does not hold may be sent to "
    "Claude's web search (the name only, never document text; at most {n} names and USD {usd:.2f}). What it finds is shown as "
    "not verified, never used."
)


def enabled() -> bool:
    return bool(settings.standards_web_search_enabled)


def plan_note(ai_review_on_claude: bool) -> str | None:
    """The pre-start plan's sentence (rule 1: the screen lists what will be sent), or None: the switch off, or no Claude AI review."""
    if not (enabled() and ai_review_on_claude):
        return None
    return PLAN_WORDS.format(
        n=MAX_PER_RUN, usd=float(settings.standards_web_search_usd_per_run)
    )


# ------------------------------------------------------------------------------------------------ what may leave


def _word(token: str) -> str | None:
    """One word of a name after the family, upper case, or None when it is not an allowed shape."""
    upper = token.upper()
    if upper in FAMILIES or upper in QUALIFIERS or upper in EDITION_WORDS:
        return upper
    if _ROMAN.fullmatch(upper) or (len(upper) == 1 and upper.isalpha()):
        return upper
    return upper if _DESIGNATION.fullmatch(upper) else None


_YEAR_OR_ORDINAL = re.compile(r"(?:19|20)[0-9]{2}|[0-9]{1,2}(?:ST|ND|RD|TH)")


def _designations_in_place(words: list[str]) -> bool:
    """Review R2-1856: after a family word only its first designation may have any shape; a later one is a year or ordinal or
    follows a part/section/kind word, as must a lone letter ("API 610 P101A" refused; "API RP 520 Part I" passes)."""
    seen, prev = False, ""
    for w in words:
        if w in FAMILIES:
            seen, prev = False, w
            continue
        letter = len(w) == 1 and w.isalpha() and not _ROMAN.fullmatch(w)
        designation = (
            bool(_DESIGNATION.fullmatch(w))
            and w not in QUALIFIERS
            and w not in EDITION_WORDS
        )
        after_qualifier = prev in QUALIFIERS
        if letter and not after_qualifier:
            return False
        if designation:
            if seen and not (after_qualifier or _YEAR_OR_ORDINAL.fullmatch(w)):
                return False
            seen = True
        prev = w
    return True


def clean_name(raw) -> str | None:
    """The public name of a standard as code rebuilds it, or None when it is not one (nothing is sent for it).

    No fold: punctuation becomes a space, any dash a hyphen; a letter or digit outside plain ASCII (a look-alike, a full-width
    form) is refused, never guessed. The first word must be a publisher family; every other word a family, a part, section or
    kind word, an edition word, a roman numeral, one letter or a designation (`_DESIGNATION`). So no sentence, tag or document
    number of a paper can ride along: "API 610 as per the datasheet" and "API 610 ZQ4821-ABC-I-07" are refused,
    "NACE MR0175/ISO 15156-3" leaves as "NACE MR0175 ISO 15156-3"."""
    out = []
    for ch in str(raw or ""):
        if ch.isascii() and (ch.isalnum() or ch in ".-"):
            out.append(ch)
        elif (
            unicodedata.category(ch) == "Pd"
        ):  # any dash (a non-breaking hyphen, an en dash) is a hyphen
            out.append("-")
        elif ch.isalnum():
            return None
        else:
            out.append(" ")
    tokens = [w.strip(".-") for w in "".join(out).split()]
    tokens = [w for w in tokens if w]
    if not tokens or len(tokens) > 8 or tokens[0].upper() not in FAMILIES:
        return None
    words = [_word(t) for t in tokens]
    if any(w is None for w in words) or not _designations_in_place(words):
        return None
    name = " ".join(w for w in words if w)
    if len(name) > NAME_LIMIT or not any(c.isdigit() for c in name):
        return None
    return name


#: The app's own tables of public standards (review R3-1856 rethink): what leaves is ALWAYS a name from them, never a paper's text.
KNOWN_NAME_TABLES = (
    "governing_standards.json",
    "kind_books.json",
    "public_standards.json",
)


@lru_cache(maxsize=1)
def known_names() -> tuple[str, ...]:
    """The public standard names the app's own reference tables hold (first word a publisher family), as written there."""
    from . import standard_ids

    out: set[str] = set()

    def walk(x) -> None:
        if isinstance(x, str):
            words = x.split()
            if (
                words
                and words[0].upper() in FAMILIES
                and len(x) <= NAME_LIMIT
                and standard_ids.parse(x)
            ):
                out.add(x.strip())
        elif isinstance(x, list):
            for item in x:
                walk(item)
        elif isinstance(x, dict):
            for k, v in x.items():
                walk(k)
                walk(v)

    for table in KNOWN_NAME_TABLES:
        walk(
            json.loads(
                (Path(__file__).parent / "reference" / table).read_text(
                    encoding="utf-8"
                )
            )
        )
    return tuple(sorted(out))


def known_public_name(raw) -> str | None:
    """The name that may leave for a cited book: the matching entry of `known_names` (the entry is sent, never the paper's text)."""
    from . import standard_ids

    cleaned = clean_name(raw)
    if not cleaned:
        return None
    flat = standard_ids.flat_key(cleaned)
    exact = [k for k in known_names() if standard_ids.flat_key(k) == flat]
    if exact:  # review R4-1856: the cited book itself when the list holds it, never a relative of it
        return exact[0]
    cited = standard_ids.parse(cleaned)
    same = [k for k in known_names() if standard_ids.same_standard(cleaned, k)]
    same_key = [
        k
        for k in same
        if cited and (p := standard_ids.parse(k)) and p.key() == cited.key()
    ]
    return (same_key or same or [None])[0]


def tool() -> dict:
    return {
        "type": TOOL_TYPE,
        "name": TOOL_NAME,
        "max_uses": MAX_USES,
        "allowed_domains": list(PUBLISHER_DOMAINS),
    }


def body_parts(name: str) -> dict:
    """Everything the request carries besides the model and `max_tokens`: the fixed system sentence, the name, the tool."""
    return {
        "system": [{"type": "text", "text": SYSTEM}],
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": f"Standard: {name}"}]}
        ],
        "tools": [tool()],
    }


def _out_cap() -> int:
    return claude_spend.output_cap(MODEL, MAX_TOKENS)


def _prompt_tokens(parts: dict) -> int:
    """The prompt as `claude_spend.metered` counts it (messages and system, ~3 characters a token)."""
    return (
        len(json.dumps([parts["messages"], parts["system"]], ensure_ascii=False)) // 3
        + 1
    )


def extra_worst_usd(parts: dict) -> float:
    """What `claude_spend.metered` does not see (review R-1853, finding 5). With S = MAX_USES + 1 samplings of the server's loop
    (one before each search and one after the last), R = SEARCH_RESULT_TOKENS_WORST, P the prompt tokens, T the tool definition's:

        searches  = MAX_USES x USD_PER_SEARCH_WORST
        tokens    = S x MAX_USES x R  +  (S - 1) x P  +  S x T        (every sampling reads every result, the prompt again, the tool)
        extra     = searches + tokens x in_long + P x (in_long - in_short) + out x (out_long - out_short)

    in = the dearer of the input and cache-write rates; "long" is the rate card past `claude_spend.LONG_PROMPT_TOKENS`, which bills
    EVERY token of the call, the prompt and the output `metered` priced at the short card included; out = the `max_tokens` the
    request carries."""
    samplings = MAX_USES + 1
    prompt = _prompt_tokens(parts)
    tool_tokens = len(json.dumps(tool())) // 3 + 1
    tokens = (
        samplings * MAX_USES * SEARCH_RESULT_TOKENS_WORST
        + (samplings - 1) * prompt
        + samplings * tool_tokens
    )
    long_in, long_out, long_write, _ = claude_spend.price_for(
        MODEL, claude_spend.LONG_PROMPT_TOKENS + 1
    )
    short_in, short_out, short_write, _ = claude_spend.price_for(MODEL, 0)
    in_long, in_short = max(long_in, long_write), max(short_in, short_write)
    per_token = (
        tokens * in_long
        + prompt * (in_long - in_short)
        + _out_cap() * (long_out - short_out)
    )
    return MAX_USES * USD_PER_SEARCH_WORST + per_token / 1_000_000


def main_worst_usd(parts: dict) -> float:
    """`claude_spend.metered`'s own worst case of the request (its messages and system, and the `max_tokens` it carries)."""
    chars = len(json.dumps([parts["messages"], parts["system"]], ensure_ascii=False))
    return claude_spend.worst_case_usd(MODEL, chars, _out_cap())


# ------------------------------------------------------------------------------------------------ what comes back


def _short(value, limit: int) -> str | None:
    plain = isinstance(value, (str, int, float)) and not isinstance(value, bool)
    text = " ".join(str(value).split()) if plain else ""
    text = "".join(c for c in text if c.isprintable())
    return text[:limit] or None


def publisher_url(value) -> str | None:
    """The URL when it is https on a publisher's own site (or a sub-domain of it), else None (dropped)."""
    if (
        not isinstance(value, str)
        or len(value) > 300
        or any(c.isspace() for c in value)
    ):
        return None
    try:
        parts = urlsplit(value)
        host, port = (parts.hostname or "").lower(), parts.port
    except ValueError:
        return None
    if (
        parts.scheme != "https"
        or parts.username
        or parts.password
        or port not in (None, 443)
    ):
        return None
    ours = any(host == d or host.endswith("." + d) for d in PUBLISHER_DOMAINS)
    return value if ours else None


def _year(value) -> int | None:
    ok = isinstance(value, int) and not isinstance(value, bool)
    return value if ok and 1900 <= value <= datetime.now(UTC).year + 1 else None


FIELDS = ("title", "latest_edition", "year", "publisher", "url")


def read_answer(answer: dict) -> tuple[dict, bool]:
    """(the fields of the reply, each cleaned and capped, an off-list URL dropped; whether the reply could be READ).

    Readable (review R-1853, finding 3) only when the answer ended normally, no search came back as an error, and its text is one
    JSON object with the asked keys. A pause, a cut at `max_tokens`, a refusal, a search error or prose is not readable: it is
    never "nothing found"."""
    blocks = [b for b in answer.get("content") or [] if isinstance(b, dict)]
    search_error = any(
        b.get("type") == "web_search_tool_result"
        and not isinstance(b.get("content"), list)
        for b in blocks
    )
    text = "".join(str(b.get("text") or "") for b in blocks if b.get("type") == "text")
    ended = answer.get("stop_reason") in ("end_turn", "stop_sequence")
    readable = ended and not search_error and _asked_keys(text)
    got = agent_claude.parse_json_object(text)
    got = got if isinstance(got, dict) else {}
    fields = {
        "title": _short(got.get("title"), 200),
        "latest_edition": _short(got.get("latest_edition"), 60),
        "year": _year(got.get("year")),
        "publisher": _short(got.get("publisher"), 100),
        "url": publisher_url(got.get("url")),
    }
    # review R2-1856: something was reported but nothing usable was kept: never "nothing found"
    usable = [k for k in FIELDS if k != "publisher"]
    reported = any(got.get(k) not in (None, "", [], {}) for k in usable)
    readable = readable and (any(fields[k] for k in usable) or not reported)
    return fields, bool(readable)


def _asked_keys(text: str) -> bool:
    """The reply's text is one JSON object with the asked keys (also the cache's check of a stored answer's text)."""
    got = agent_claude.parse_json_object(text)
    return isinstance(got, dict) and any(k in got for k in FIELDS)


def stored_on(stored: dict | None) -> str | None:
    """When a stored answer was searched (its record's UTC time), or None when unknown, in the future or too old to use."""
    try:
        when = datetime.fromisoformat(str((stored or {}).get("stored_at")))
        age = datetime.now(UTC) - when
        fresh = timedelta(0) <= age <= timedelta(days=MAX_STORED_AGE_DAYS)
    except (ValueError, TypeError):  # no time, or one without its zone: never used
        return None
    return when.isoformat(timespec="seconds") if fresh else None


def _row(fields: dict, usd: float, why: str | None = None) -> dict:
    found = any(fields[k] for k in ("title", "latest_edition", "year", "url"))
    return {"outcome": FOUND if found else NOTHING, "why": why, "usd": usd, **fields}


def searches_made(answer: dict) -> int:
    """How many searches the answer says were made: the usage count, or the search blocks when that is larger."""
    usage = answer.get("usage") if isinstance(answer.get("usage"), dict) else {}
    stated = usage.get("server_tool_use")
    stated = stated if isinstance(stated, dict) else {}
    try:
        counted = max(0, int(stated.get("web_search_requests") or 0))
    except (TypeError, ValueError):
        counted = 0
    blocks = [b for b in answer.get("content") or [] if isinstance(b, dict)]
    return max(counted, sum(b.get("type") == "server_tool_use" for b in blocks))


# ------------------------------------------------------------------------------------------------ one request


class _Stop(Exception):
    """A limit (a cap, an account stop, the run kept on this computer, the lane closed): no further name is searched in this run."""

    def __init__(self, why: str) -> None:
        super().__init__(why)
        self.why = why


def _failure(failure) -> tuple[str, str, bool]:
    """(kind, code, billed) of `agent_claude._send_once`'s failure, read by index, so a longer tuple (a retry flag) reads the same."""
    return str(failure[0]), str(failure[1]), bool(failure[2])


def search_one(
    name: str, *, send=None, env=None, timeout: float = REQUEST_TIMEOUT_SECONDS
) -> dict:
    """Ask for one cleaned public name. Returns the row's fields and its cost; raises `_Stop` when nothing more may be sent."""
    parts = body_parts(name)
    try:
        raw = agent_claude._transport(send)
        request = agent_claude._request(MODEL, _out_cap(), env)
    except agent_claude.AgentClaudeError as exc:
        raise _Stop(f"the Claude lane is closed ({exc.code})") from None
    request = {**request, "timeout": min(float(request["timeout"]), float(timeout))}
    body = dict(request["body"])
    body.update(parts)
    body["model"], body["max_tokens"] = MODEL, _out_cap()
    digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    try:  # the cache door first (its approved-list gate is the reservation's own): a stored readable answer costs 0, no socket
        stored, key = claude_spend.answer_on_file(
            STEP, body, version=ANSWER_VERSION, valid=_asked_keys, prompt_sha256=digest
        )
        fields, readable = read_answer(stored or {})
        # a hit keeps the ORIGINAL search time; a stored answer read_answer refuses (not expected) is asked again, paid
        if readable and (when := stored_on(stored)):
            return {**_row(fields, 0.0, STORED_WORDS), "searched_at": when}
        held = claude_spend.reserve(
            STEP, extra_worst_usd(parts), model=MODEL, prompt_sha256=digest
        )
    except claude_spend.StopRun as exc:
        request = None
        raise _Stop(f"a limit stopped it ({type(exc).__name__})") from None
    closed = False
    try:
        answer, failure = agent_claude._send_once(raw, request, body, step=STEP)
        request = None  # the headers (the key) leave this frame first
        if failure is not None:
            kind, code, billed = _failure(failure)
            if billed:
                claude_spend.settle(held, usage=None, finish_reason=f"failed:{code}", model=MODEL,
                                    estimated_usd=held.worst_usd)  # fmt: skip
            else:
                claude_spend.release(held, f"unbilled:{code}")
            closed = True
            if kind == "stop":
                raise _Stop(f"a limit stopped it ({code})")
            usd = (held.worst_usd + main_worst_usd(parts)) if billed else 0.0
            return {"outcome": FAILED, "why": code, "usd": usd}
        answer = answer if isinstance(answer, dict) else {}
        fee = searches_made(answer) * USD_PER_SEARCH
        claude_spend.settle(held, usage=None, finish_reason="web_search_fee", model=MODEL, estimated_usd=fee)  # fmt: skip
        closed = True
        usd = round(agent_claude._usd(MODEL, answer, body) + fee, 6)
        fields, readable = read_answer(answer)
        if not readable:  # never kept: a failed, refused or unreadable answer is asked again next time
            return {"outcome": INCOMPLETE, "why": UNREADABLE_WORDS, "usd": usd}
        claude_spend.keep_answer(key, STEP, answer, cost_usd=usd, valid=_asked_keys)
        return _row(fields, usd)
    finally:
        request = None
        if not closed:  # any other path after the reservation: charged at its worst case, never left open
            claude_spend.settle(held, usage=None, finish_reason="failed:unsettled", model=MODEL,
                                estimated_usd=held.worst_usd)  # fmt: skip


# ------------------------------------------------------------------------------------------------ the run


_STATEMENTS = (
    f"""CREATE TABLE IF NOT EXISTS {TABLE} (
        run_id TEXT NOT NULL,
        name TEXT NOT NULL CHECK (length(name) > 0),
        searched_name TEXT,
        outcome TEXT NOT NULL CHECK (outcome IN ('{FOUND}', '{NOTHING}', '{INCOMPLETE}', '{NOT_SEARCHED}', '{FAILED}')),
        why TEXT,
        title TEXT,
        latest_edition TEXT,
        year INTEGER,
        publisher TEXT,
        url TEXT,
        searched_at TEXT NOT NULL,
        usd REAL NOT NULL DEFAULT 0 CHECK (usd >= 0),
        PRIMARY KEY (run_id, name)
    )""",
)


def _has_table(conn) -> bool:
    sql = "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?"
    return conn.execute(sql, (TABLE,)).fetchone() is not None


def _missing(conn, run_id: str) -> list[str]:
    sql = "SELECT name FROM agent_review_missing_book WHERE run_id = ? ORDER BY name"
    try:
        return [r[0] for r in conn.execute(sql, (run_id,))]
    except sqlite3.OperationalError:  # no AI review tables: no book listed
        return []


def _paper(conn, run_id: str) -> str | None:
    row = conn.execute(
        "SELECT submittal_document_id FROM review_runs WHERE id = ?", (run_id,)
    ).fetchone()
    return row[0] if row and row[0] else None


def paper_went_to_claude(run_id: str) -> bool:
    """True only when this run's AI reviewer had at least one Claude call ANSWERED: a settled ledger line of the run under the
    reviewer's step that was not refused, not a cache hit and not a failure. Anything else (no line, refusals only, failures only,
    an unreadable ledger) is False: nothing taken from the paper is sent."""
    try:
        lines = claude_spend.entries()
    except (OSError, ValueError):
        return False
    for e in lines:
        if e.get("run") != run_id or e.get("step") != agent_claude.STEP:
            continue
        if e.get("refused") or e.get("reserved") or e.get("cached"):
            continue
        finish = str(e.get("finish_reason") or "")
        if finish and not finish.startswith(("failed", "refused", "cache_hit")):
            return True
    return False


def _write(conn, run_id: str, name: str, searched: str | None, row: dict) -> None:
    with conn:
        conn.execute(
            f"INSERT OR REPLACE INTO {TABLE} (run_id, name, searched_name, outcome, why, title, latest_edition, year, publisher, url,"
            " searched_at, usd) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, name, searched, row["outcome"], row.get("why"), row.get("title"), row.get("latest_edition"), row.get("year"),
             row.get("publisher"), row.get("url"), row.get("searched_at") or datetime.now(UTC).isoformat(timespec="seconds"),
             float(row.get("usd") or 0.0)),
        )  # fmt: skip


def _held_back(run_id: str, paper: str | None) -> str | None:
    """Why nothing taken from this paper may be sent now, or None. Asked inside the paper's declaration."""
    from . import claude_approved

    if not paper or not paper_went_to_claude(run_id):
        return NOT_SENT_WORDS
    refused = claude_approved.refusal()
    if refused is not None:
        return f"the paper is not cleared for Claude now ({refused[0]}), so nothing taken from it is sent"
    return None


class _Budget:
    """What one run may still spend: requests, USD and wall time."""

    def __init__(self) -> None:
        self.cap = float(settings.standards_web_search_usd_per_run)
        self.until = time.monotonic() + TIME_LIMIT_SECONDS
        self.spent, self.asked = 0.0, 0

    def refuses(self, parts: dict) -> str | None:
        if self.asked >= MAX_PER_RUN:
            return COUNT_WORDS
        if self.spent + extra_worst_usd(parts) + main_worst_usd(parts) > self.cap:
            return CAP_WORDS
        if self.until - time.monotonic() < 5.0:
            return TIME_WORDS
        return None

    def timeout(self) -> float:
        return max(1.0, min(REQUEST_TIMEOUT_SECONDS, self.until - time.monotonic()))


def search_run(run_id: str, *, send=None, env=None, conn=None, heartbeat=None) -> dict:
    """Search every rule book the run listed as not held. Switch off: does nothing at all (no table, no request).

    Counts only in the result and the log, never a name or an answer. Its spend is always booked to the run (review R2-1856: the
    run cap and the run's spend record hold even when it is called outside the job wrapper). Holds of this step left open by a
    process that ended are closed first (`standards_web_search_money.close_stale`)."""
    if not enabled() or not run_id:
        return {"ran": False}
    money.close_stale(STEP)
    with claude_spend.for_run(run_id):
        return _search_run(run_id, send=send, env=env, conn=conn, beat=heartbeat or (lambda: None))  # fmt: skip


def _search_run(run_id: str, *, send=None, env=None, conn=None, beat) -> dict:
    from . import claude_approved

    conn = conn or connect()
    names = _missing(conn, run_id)
    if not names:
        return {"ran": True, "asked": 0, "usd": 0.0}
    for statement in _STATEMENTS:
        conn.execute(statement)
    done = {
        r[0]
        for r in conn.execute(f"SELECT name FROM {TABLE} WHERE run_id = ?", (run_id,))
    }
    paper = _paper(conn, run_id)
    budget, stop = _Budget(), None
    # declared: these prompts carry what was taken from THE PAPER (review R-1853, finding 1); the gate asks about it at every send
    with (
        claude_approved.carrying([paper] if paper else []),
        claude_approved.reviewing(run_id),
    ):
        stop = _held_back(run_id, paper)
        sent_names: set[str] = set()
        for name in names:
            if name in done:
                continue
            beat()  # the job's worker stays alive on the page while each request runs
            searched = known_public_name(name)
            parts = body_parts(searched) if searched else None
            why = NOT_PUBLIC if parts is None else (stop or budget.refuses(parts))
            # review R4-1856: one search per name sent, never paid twice
            if why is None and searched in sent_names:
                why = SEARCHED_ONCE
            if why is not None:
                row = {"outcome": NOT_SEARCHED, "why": why}
            else:
                try:
                    row = search_one(
                        searched, send=send, env=env, timeout=budget.timeout()
                    )
                    budget.asked += row.get("why") != STORED_WORDS  # stored: not sent
                    budget.spent += float(row.get("usd") or 0.0)
                except _Stop as exc:
                    stop = exc.why
                    row = {"outcome": NOT_SEARCHED, "why": stop}
            sent = row["outcome"] in (FOUND, NOTHING, INCOMPLETE, FAILED)
            if sent:
                sent_names.add(searched)
            _write(conn, run_id, name, searched if sent else None, row)
    log.info("standards web search: run %s, %d book(s) not held, %d asked, USD %.4f", run_id, len(names), budget.asked,
             budget.spent)  # fmt: skip
    return {"ran": True, "asked": budget.asked, "usd": round(budget.spent, 6)}


def after_run(run_id: str, heartbeat=None) -> None:
    """The AI review job's hook, BEFORE the run is marked completed (a driver that stops the app on "completed" no longer ends a
    search with its hold open; paid run of 17 Nov 2026), then its cost is added to the run's own `usd` (`money.add_to_run`):
    never fails the review (a failure is logged by kind only); at most `TIME_LIMIT_SECONDS`."""
    if not enabled():
        return
    try:
        try:
            search_run(run_id, heartbeat=heartbeat)
        finally:  # names already paid count on the run even when the search stopped with an error
            money.add_to_run(run_id, STEP)
    except Exception as exc:  # noqa: BLE001 - shown, never used: the review stands whatever happens here
        log.warning("standards web search skipped: %s", type(exc).__name__)


# ------------------------------------------------------------------------------------------------ what is shown


def words(row: dict | None) -> str:
    """The one plain sentence for one book, on the page and in the CRS file's column."""
    if not row:
        return "not searched yet"
    hit, when = row.get("why") == STORED_WORDS, str(row.get("searched_at"))[:10]
    stored = f"; {STORED_WORDS}, searched on {when}" if hit else ""
    if row["outcome"] == FOUND:
        bits = [row.get("title"), row.get("latest_edition"), f"({row['year']})" if row.get("year") else None, row.get("publisher"),
                row.get("url")]  # fmt: skip
        return "; ".join(b for b in bits if b) + f" ({NOT_VERIFIED})" + stored
    if row["outcome"] == NOTHING:
        return "searched online, nothing found on the publisher's site" + stored
    return f"{row['outcome']}: {row.get('why') or 'no reason recorded'}"


def shown(conn, run_id: str | None, names: list[str]) -> list[dict] | None:
    """What the page and the CRS file show for the run's books not held, or None when the switch is off (nothing is added)."""
    if not enabled():
        return None
    rows: dict[str, dict] = {}
    if run_id and _has_table(conn):
        from .review_points import book_name_of

        # FTU-16: the list names the book alone; the search stored the run's own name
        rows = {
            book_name_of(r["name"]): dict(r)
            for r in conn.execute(f"SELECT * FROM {TABLE} WHERE run_id = ?", (run_id,))
        }
    keep = ("outcome", *FIELDS, "searched_at", "usd")
    return [
        {
            "name": n,
            **{k: (rows.get(n) or {}).get(k) for k in keep},
            "words": words(rows.get(n)),
        }
        for n in names
    ]


def into(counts: dict, conn, run_id: str | None, names: list[str]) -> dict:
    """Add `found_online` to the page's counts of books not held; return the facts the CRS file reads. Off: {} and nothing added."""
    found = shown(conn, run_id, names)
    if found is None:
        return {}
    counts["not_held"]["found_online"] = found
    return {"found_online": found}


def cost_of(found: list[dict] | None) -> float | None:
    """The search's own cost for the CRS file's "How it was reviewed" (a run recorded before 17 Nov 2026 has it outside the AI
    review's cost; a later one inside it, `money.COST_ROW_INCLUDED`), or None while off."""
    if found is None:
        return None
    return round(sum(float(f.get("usd") or 0.0) for f in found), 6)
