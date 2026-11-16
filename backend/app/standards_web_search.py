"""ONLINE SEARCH FOR RULE BOOKS WE DO NOT HOLD (owner decision, 17 Nov 2026, #1584 comment 6927034366, pending his confirmation
there: "Approved to use ... online search for standards we do not have. Both are switched off now, and no KJO document goes outside
without approval.").

WHAT IT DOES. After an AI review ends, for each rule book the review listed as not held (`agent_review_missing_book`), it asks Claude,
with Anthropic's server-side web search tool, for the PUBLIC catalogue entry of that standard: its full title, its latest edition and
year, its publisher and one page on the publisher's own site. The answer is SHOWN, never used: it is a line on the page and a column on
the one CRS file's sheet "Rule books not held", headed "Found online (not verified, book not held)". It is never a rule quote, never a
clause, never a verdict input, never a point, and the review's counts do not change.

WHAT LEAVES THE MACHINE. Only the public name of a standard, rebuilt by code from a closed set of word shapes (`clean_name`: a
publisher family such as API or ISO first, then words with a digit, a roman numeral or a fixed qualifier such as "Part" or
"Section"); a name with any other word is refused and nothing is sent for it. Never document text, never a file name, never a page,
never the paper's name. The request carries a fixed system sentence, "Standard: <name>", and the web search tool limited to the
publishers' own sites (`PUBLISHER_DOMAINS`). Declared to the approved-documents gate as carrying NO document
(`claude_approved.per_request_consent(())`, an empty declaration that replaces any outer one), so a run kept on this computer
("Local only") still sends nothing: the gate and `agent_claude.gate_open` both read the run's bar.

THE LANE. The existing Claude lane only: `agent_claude._request` (the provider switch, both egress flags, https, the allowed host, the
key) and `agent_claude._send_once` (`claude_spend.metered`: reserve, send through `reader_transport`, settle). No new company, no new
key, no new socket module.

MONEY. One request per missing book, at most `MAX_PER_RUN` a run, and at most `settings.standards_web_search_usd_per_run` a run.
The web search tool has its own price per search beside the tokens, and its results come back as input tokens that the prompt does not
show, so `claude_spend.metered`'s worst case (the prompt and `max_tokens`) is not enough. Before each request a second reservation
under the same step holds the rest of the worst case (`extra_worst_usd`: every allowed search at twice the list price and every
allowed search's results at the dearest input rate); it is settled to the searches the answer reports, released when the API provably
did no work. So the run, step, day and month caps in `claude_spend` hold. A 4xx costs nothing, as on every Claude call.

OFF (`settings.standards_web_search_enabled`, default False): nothing is asked, nothing is created, the page and the CRS file are
byte for byte as before. No document text, no answer text and no key is logged; the log says counts and outcomes only.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import unicodedata
from datetime import UTC, datetime
from urllib.parse import urlsplit

from . import agent_claude, claude_spend
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
#: Anthropic's list price of the web search tool, USD 10 per 1,000 searches: an ESTIMATE, the invoice is the truth. Reserved at
#: twice that, so a price change cannot break a cap; settled at the list price.
USD_PER_SEARCH = 0.01
USD_PER_SEARCH_WORST = 0.02
#: The input tokens one search's results may add over the server's loop, generously; priced at the dearest input rate.
SEARCH_RESULT_TOKENS_WORST = 75_000
TABLE = "standards_web_search"
COLUMN = "Found online (not verified, book not held)"
NOT_VERIFIED = "found online, not verified; the book is not held"

#: Publisher families whose standards are public and sold by their publisher; the first word of a name that may leave.
FAMILIES = (
    "API",
    "ASME",
    "ISO",
    "NACE",
    "AMPP",
    "ASTM",
    "IEC",
    "EN",
    "BS",
    "ANSI",
    "MSS",
    "AWS",
    "NFPA",
    "IEEE",
)
#: Words a standard's public name may carry besides its family and its numbers.
QUALIFIERS = frozenset(
    {
        "PART",
        "SECTION",
        "SEC",
        "DIVISION",
        "DIV",
        "STD",
        "RP",
        "SPEC",
        "MR",
        "TM",
        "SP",
        "BPVC",
        "PTC",
        "TR",
        "TS",
    }
)
#: The publishers' own sites: the search is limited to them and a URL is kept only on one of them (or a sub-domain).
PUBLISHER_DOMAINS = (
    "api.org", "asme.org", "iso.org", "ampp.org", "nace.org", "astm.org", "iec.ch", "ieee.org", "nfpa.org", "aws.org",
    "msshq.org", "ansi.org", "bsigroup.com", "cen.eu",
)  # fmt: skip
_ROMAN = re.compile(r"(?=[IVX])X?(IX|IV|V?I{0,3})")
_WORD = re.compile(r"[A-Za-z0-9.\-]{1,16}")

SYSTEM = (
    "You look up the public catalogue entry of one engineering standard on its publisher's own website. Use the web search tool at "
    "most twice. Reply with ONE JSON object and no other text: "
    '{"title": string or null, "latest_edition": string or null, "year": integer or null, "publisher": string or null, '
    '"url": string or null}. The url is one page on the publisher\'s own site. Use null for anything you did not find there. '
    "Do not guess."
)

FOUND, NOTHING, NOT_SEARCHED, FAILED = (
    "found",
    "nothing found",
    "not searched",
    "search failed",
)
NOT_PUBLIC = "not a public standard name, so it was not sent"
CAP_WORDS = "the USD limit for online search in this review was reached"
COUNT_WORDS = f"at most {MAX_PER_RUN} rule books are searched in one review"


def enabled() -> bool:
    return bool(settings.standards_web_search_enabled)


# ------------------------------------------------------------------------------------------------ what may leave


def clean_name(raw) -> str | None:
    """The public name of a standard as code rebuilds it, or None when it is not one (nothing is sent for it).

    No fold: punctuation becomes a space, any dash a hyphen; a letter or digit outside plain ASCII (a look-alike, a full-width
    form) is refused, never guessed. The first word must be a publisher family, and every other word a family, a fixed
    qualifier, a roman numeral, one letter or a short word with a digit. So no sentence of a paper can ride along:
    "API 610 as per the datasheet" is refused, "NACE MR0175/ISO 15156-3" leaves as "NACE MR0175 ISO 15156-3"."""
    text = str(raw or "")
    out = []
    for ch in text:
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
    words = [w.strip(".-") for w in "".join(out).split()]
    words = [w for w in words if w]
    if not words or len(words) > 8 or words[0].upper() not in FAMILIES:
        return None
    for i, word in enumerate(words):
        upper = word.upper()
        if upper in FAMILIES or upper in QUALIFIERS or _ROMAN.fullmatch(upper):
            words[i] = upper
        elif not (len(word) == 1 and word.isalpha()) and not (
            _WORD.fullmatch(word) and any(c.isdigit() for c in word)
        ):
            return None
    name = " ".join(words)
    if len(name) > NAME_LIMIT or not any(c.isdigit() for c in name):
        return None
    return name


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


def extra_worst_usd() -> float:
    """What `claude_spend.metered` does not see: every allowed search's fee and results, and the tool definition."""
    tokens = SEARCH_RESULT_TOKENS_WORST * MAX_USES + len(json.dumps(tool())) // 3 + 1
    p_in, _out, p_write, _read = claude_spend.price_for(MODEL, tokens)
    return MAX_USES * USD_PER_SEARCH_WORST + tokens * max(p_in, p_write) / 1_000_000


def main_worst_usd(parts: dict) -> float:
    """`claude_spend.metered`'s own worst case of the request (its messages and system, and the `max_tokens` it carries)."""
    chars = len(json.dumps([parts["messages"], parts["system"]], ensure_ascii=False))
    return claude_spend.worst_case_usd(
        MODEL, chars, claude_spend.output_cap(MODEL, MAX_TOKENS)
    )


# ------------------------------------------------------------------------------------------------ what comes back


def _short(value, limit: int) -> str | None:
    text = (
        " ".join(str(value).split())
        if isinstance(value, (str, int, float)) and not isinstance(value, bool)
        else ""
    )
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
    return (
        value
        if any(host == d or host.endswith("." + d) for d in PUBLISHER_DOMAINS)
        else None
    )


def _year(value) -> int | None:
    try:
        year = (
            int(str(value).strip()[:4])
            if value is not None and not isinstance(value, bool)
            else None
        )
    except ValueError:
        return None
    return (
        year
        if year is not None and 1900 <= year <= datetime.now(UTC).year + 1
        else None
    )


def read_answer(answer: dict) -> dict:
    """The fields of the reply, each cleaned and capped; an off-list URL dropped. Nothing found: every field None."""
    text = "".join(
        str(b.get("text") or "")
        for b in answer.get("content") or []
        if isinstance(b, dict) and b.get("type") == "text"
    )
    got = agent_claude.parse_json_object(text) or {}
    return {
        "title": _short(got.get("title"), 200),
        "latest_edition": _short(got.get("latest_edition"), 60),
        "year": _year(got.get("year")),
        "publisher": _short(got.get("publisher"), 100),
        "url": publisher_url(got.get("url")),
    }


def searches_made(answer: dict) -> int:
    """How many searches the answer says were made: the usage count, or the search blocks when that is larger."""
    usage = answer.get("usage") if isinstance(answer.get("usage"), dict) else {}
    stated = (
        (usage.get("server_tool_use") or {})
        if isinstance(usage.get("server_tool_use"), dict)
        else {}
    )
    try:
        counted = max(0, int(stated.get("web_search_requests") or 0))
    except (TypeError, ValueError):
        counted = 0
    blocks = sum(
        1
        for b in answer.get("content") or []
        if isinstance(b, dict) and b.get("type") == "server_tool_use"
    )
    return max(counted, blocks)


# ------------------------------------------------------------------------------------------------ one request


class _Stop(Exception):
    """A limit (a cap, the run kept on this computer, the lane closed): no further name is searched in this run."""

    def __init__(self, why: str) -> None:
        super().__init__(why)
        self.why = why


def search_one(name: str, *, send=None, env=None) -> dict:
    """Ask for one cleaned public name. Returns the row's fields and its cost; raises `_Stop` when nothing more may be sent."""
    parts = body_parts(name)
    extra = extra_worst_usd()
    try:
        raw = agent_claude._transport(send)
        request = agent_claude._request(
            MODEL, claude_spend.output_cap(MODEL, MAX_TOKENS), env
        )
    except agent_claude.AgentClaudeError as exc:
        raise _Stop(f"the Claude lane is closed ({exc.code})") from None
    body = dict(request["body"])
    body.update(parts)
    body["model"], body["max_tokens"] = (
        MODEL,
        claude_spend.output_cap(MODEL, MAX_TOKENS),
    )
    digest = hashlib.sha256(
        json.dumps(body, sort_keys=True).encode("utf-8")
    ).hexdigest()
    try:
        held = claude_spend.reserve(STEP, extra, model=MODEL, prompt_sha256=digest)
    except claude_spend.StopRun as exc:
        del request
        raise _Stop(f"a spending limit stopped it ({type(exc).__name__})") from None
    answer, failure = agent_claude._send_once(raw, request, body, step=STEP)
    del request  # the headers (the key) leave this frame before anything else happens
    if failure is not None:
        kind, code, billed = failure
        if billed:
            claude_spend.settle(
                held,
                usage=None,
                finish_reason=f"failed:{code}",
                model=MODEL,
                estimated_usd=held.worst_usd,
            )
        else:
            claude_spend.release(held, f"unbilled:{code}")
        if kind == "stop":
            raise _Stop(f"a spending limit stopped it ({code})")
        return {
            "outcome": FAILED,
            "why": code,
            "usd": (held.worst_usd + main_worst_usd(parts)) if billed else 0.0,
        }
    answer = answer if isinstance(answer, dict) else {}
    fee = searches_made(answer) * USD_PER_SEARCH
    claude_spend.settle(
        held, usage=None, finish_reason="web_search_fee", model=MODEL, estimated_usd=fee
    )
    usd = round(agent_claude._usd(MODEL, answer, body) + fee, 6)
    fields = read_answer(answer)
    found = any(fields[k] for k in ("title", "latest_edition", "year", "url"))
    return {"outcome": FOUND if found else NOTHING, "why": None, "usd": usd, **fields}


# ------------------------------------------------------------------------------------------------ the run


_STATEMENTS = (
    f"""CREATE TABLE IF NOT EXISTS {TABLE} (
        run_id TEXT NOT NULL,
        name TEXT NOT NULL CHECK (length(name) > 0),
        searched_name TEXT,
        outcome TEXT NOT NULL CHECK (outcome IN ('{FOUND}', '{NOTHING}', '{NOT_SEARCHED}', '{FAILED}')),
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
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (TABLE,)
        ).fetchone()
        is not None
    )


def _missing(conn, run_id: str) -> list[str]:
    try:
        return [
            r[0]
            for r in conn.execute(
                "SELECT name FROM agent_review_missing_book WHERE run_id = ? ORDER BY name",
                (run_id,),
            )
        ]
    except sqlite3.OperationalError:  # no AI review tables: no book listed
        return []


def _write(conn, run_id: str, name: str, searched: str | None, row: dict) -> None:
    with conn:
        conn.execute(
            f"INSERT OR REPLACE INTO {TABLE} (run_id, name, searched_name, outcome, why, title, latest_edition, year, publisher, url,"
            " searched_at, usd) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, name, searched, row["outcome"], row.get("why"), row.get("title"), row.get("latest_edition"), row.get("year"),
             row.get("publisher"), row.get("url"), datetime.now(UTC).isoformat(timespec="seconds"), float(row.get("usd") or 0.0)),
        )  # fmt: skip


def search_run(run_id: str, *, send=None, env=None, conn=None) -> dict:
    """Search every rule book the run listed as not held. Switch off: does nothing at all (no table, no request).

    Counts only in the result and the log, never a name or an answer."""
    if not enabled() or not run_id:
        return {"ran": False}
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
    cap = float(settings.standards_web_search_usd_per_run)
    spent, asked, stop = 0.0, 0, None
    # declared: this prompt carries NO document (only a public standard name); it replaces any outer declaration
    with claude_approved.per_request_consent(()):
        for name in names:
            if name in done:
                continue
            searched = clean_name(name)
            row: dict
            if searched is None:
                row = {"outcome": NOT_SEARCHED, "why": NOT_PUBLIC}
            elif stop is not None:
                row = {"outcome": NOT_SEARCHED, "why": stop}
            elif asked >= MAX_PER_RUN:
                row = {"outcome": NOT_SEARCHED, "why": COUNT_WORDS}
            elif spent + extra_worst_usd() + main_worst_usd(body_parts(searched)) > cap:
                row = {"outcome": NOT_SEARCHED, "why": CAP_WORDS}
            else:
                try:
                    row = search_one(searched, send=send, env=env)
                    asked += 1
                    spent += float(row.get("usd") or 0.0)
                except _Stop as exc:
                    stop = exc.why
                    row = {"outcome": NOT_SEARCHED, "why": stop}
            _write(
                conn,
                run_id,
                name,
                searched if row["outcome"] in (FOUND, NOTHING, FAILED) else None,
                row,
            )
    log.info(
        "standards web search: run %s, %d book(s) not held, %d asked, USD %.4f",
        run_id,
        len(names),
        asked,
        spent,
    )
    return {"ran": True, "asked": asked, "usd": round(spent, 6)}


def after_run(run_id: str) -> None:
    """The AI review job's hook, after the run is completed: never fails the review (a failure is logged by kind only)."""
    if not enabled():
        return
    try:
        search_run(run_id)
    except Exception as exc:  # noqa: BLE001 - shown, never used: the review stands whatever happens here
        log.warning("standards web search skipped: %s", type(exc).__name__)


# ------------------------------------------------------------------------------------------------ what is shown


def words(row: dict | None) -> str:
    """The one plain sentence for one book, on the page and in the CRS file's column."""
    if not row:
        return "not searched"
    if row["outcome"] == FOUND:
        bits = [row.get("title"), row.get("latest_edition"), f"({row['year']})" if row.get("year") else None, row.get("publisher"),
                row.get("url")]  # fmt: skip
        return "; ".join(b for b in bits if b) + f" ({NOT_VERIFIED})"
    if row["outcome"] == NOTHING:
        return "searched online, nothing found on the publisher's site"
    return f"{row['outcome']}: {row.get('why') or 'no reason recorded'}"


def shown(conn, run_id: str | None, names: list[str]) -> list[dict] | None:
    """What the page and the CRS file show for the run's books not held, or None when the switch is off (nothing is added)."""
    if not enabled():
        return None
    rows: dict[str, dict] = {}
    if run_id and _has_table(conn):
        rows = {
            r["name"]: dict(r)
            for r in conn.execute(f"SELECT * FROM {TABLE} WHERE run_id = ?", (run_id,))
        }
    out = []
    for name in names:
        row = rows.get(name)
        keep = (
            "outcome",
            "title",
            "latest_edition",
            "year",
            "publisher",
            "url",
            "searched_at",
            "usd",
        )
        out.append(
            {"name": name, **{k: (row or {}).get(k) for k in keep}, "words": words(row)}
        )
    return out


def into(counts: dict, conn, run_id: str | None, names: list[str]) -> dict:
    """Add `found_online` to the page's counts of books not held; return the facts the CRS file reads. Off: {} and nothing added."""
    found = shown(conn, run_id, names)
    if found is None:
        return {}
    counts["not_held"]["found_online"] = found
    return {"found_online": found}
