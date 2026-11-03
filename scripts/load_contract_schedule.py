"""#805 STEP 5: load a contract schedule's requirement items as rules with source 'contract schedule', on a COPY.

    python scripts/load_contract_schedule.py --db <copy> --file <LOCAL json outside the repo> --by NAME
    python scripts/load_contract_schedule.py --db <copy> --list

The items are DATA you supply: {"contract": "...", "items": [{"id", "clause", "kind", "text"}]}; the template in
`scripts/contract_schedule_template.json` holds placeholders only. The real wording lives in a local file, never in git,
and a file inside the repository is refused. An item is a COMPLETENESS check on a submittal (a thing is present or is not
present), never an equipment limit: a value, unit or comparator is refused, and so is a kind that is not a completeness
kind. Rules are append-only (`contract_schedule_rule`); a changed text is a new row, the old one stays; a repeat adds
nothing. `completeness()` is the pure check: PRESENT only with a verified page quote; NOT_PRESENT only when the whole
submittal was searched and nothing was found; anything else goes to the engineer ("not mentioned" is never "met").

Sends nothing and calls no model: USD 0. A live-shaped --db is refused. Nothing in the app reads this table yet.
Exit: 0 done; 2 refused (says why).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import unicodedata
import uuid
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "scripts"))

from app import claims, numparse  # noqa: E402

SOURCE = "contract schedule"
#: What the submittal must show. Each is present or not present; none is a number to meet.
KINDS = (
    "calculations_with_datasheets",
    "old_comments_closed",
    "holds_listed",
    "deviation_waiver_form",
)
ALLOWED_KEYS = {"id", "clause", "kind", "text"}
PRESENT, NOT_PRESENT, NEEDS_ENGINEER = "present", "not_present", "needs_engineer"
EXIT_REFUSED = 2
#: What the repo's own vocabularies do not cover: number words, and comparator phrases `claims` has no entry for.
_NUMBER_WORD = re.compile(
    r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|(?:thir|four|fif|six|seven|eigh|nine)teen"
    r"|(?:twen|thir|for|fif|six|seven|eigh|nine)ty|hundred|thousand|million|dozen|half|quarter|percent|per\s?cent)\b",
    re.IGNORECASE,
)
_COMPARATOR_PHRASE = re.compile(
    r"[<>=\u2264\u2265\u00b1]|\+\s?/\s?-|\b(?:up to|no (?:fewer|more|less|greater) than|fewer than|more than"
    r"|less than|greater than|or (?:more|less)|at (?:least|most)|within|between|minimum|maximum|min|max)\b",
    re.IGNORECASE,
)
#: Words `claims.is_unit` accepts that are also plain English: not a unit here.
_UNIT_LOOKALIKES = frozenset({"in", "a", "m", "g", "s", "t", "l", "h"})


def _states_a_limit(text: str) -> bool:
    """A number, number word, unit, or comparator anywhere in an item's text: the repo's own detectors first
    (`numparse`, `claims.is_unit`, `claims.comparator_ending`), any numeral of any script (fullwidth digits, one-half),
    then the few vocabularies they lack."""
    text = _normalise(text)
    if numparse.find_numbers(text) or numparse.find_fractions(text):
        return True
    if any(unicodedata.numeric(ch, None) is not None for ch in text):
        return True
    words = re.findall(r"[^\W_]+", text)
    if any(claims.is_unit(w) and w.casefold() not in _UNIT_LOOKALIKES for w in words):
        return True
    if any(
        claims.comparator_ending(" ".join(words[:i])) for i in range(1, len(words) + 1)
    ):
        return True
    return bool(_NUMBER_WORD.search(text) or _COMPARATOR_PHRASE.search(text))


_PLACEHOLDER = re.compile(r"<[^<>]*>")

_TABLE = f"""CREATE TABLE contract_schedule_rule (
    id TEXT PRIMARY KEY, contract TEXT NOT NULL CHECK (length(trim(contract)) > 0),
    item_id TEXT NOT NULL CHECK (length(trim(item_id)) > 0), clause TEXT NOT NULL CHECK (length(trim(clause)) > 0),
    kind TEXT NOT NULL CHECK (kind IN ({",".join(f"'{k}'" for k in KINDS)})),
    text TEXT NOT NULL CHECK (length(trim(text)) > 0), text_sha256 TEXT NOT NULL CHECK (length(text_sha256) = 64),
    source TEXT NOT NULL CHECK (source = '{SOURCE}'), version_no INTEGER NOT NULL CHECK (version_no >= 1),
    loaded_by TEXT NOT NULL, loaded_at TEXT NOT NULL, UNIQUE (contract, item_id, version_no))"""
_GUARDS = (
    *(
        f"CREATE TRIGGER contract_schedule_rule_no_{verb.lower()} BEFORE {verb} ON contract_schedule_rule"
        " BEGIN SELECT RAISE(ABORT, 'contract schedule: rules are append-only'); END"
        for verb in ("UPDATE", "DELETE")
    ),
)


class Refused(ValueError):
    """The file or the database is not fit to load; says why, never quoting the contract's words."""


def read_items(path: Path, *, repo: Path = REPO) -> tuple[str, list[dict]]:
    """(contract label, items) of a local file, each item checked. Raises `Refused`."""
    resolved = Path(path).resolve()
    if resolved.is_relative_to(repo.resolve()):
        raise Refused(
            "the schedule's real wording must live in a local file outside the repository"
        )
    try:
        data = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        raise Refused(
            f"the file cannot be read as JSON ({type(err).__name__})"
        ) from err
    contract = str(data.get("contract") or "").strip()
    items = data.get("items")
    if not contract or _PLACEHOLDER.search(contract):
        raise Refused("name the contract in 'contract' (a placeholder is not a name)")
    if not isinstance(items, list) or not items:
        raise Refused("'items' must be a non-empty list")
    seen: set[str] = set()
    for n, item in enumerate(items, 1):
        if not isinstance(item, dict):
            raise Refused(f"item {n} is not an object")
        extra = set(item) - ALLOWED_KEYS
        if extra:
            raise Refused(
                f"item {n} has fields {sorted(extra)}: a schedule item is present or not present, never an equipment limit"
            )
        for key in sorted(ALLOWED_KEYS):
            value = str(item.get(key) or "").strip()
            if not value:
                raise Refused(f"item {n} has no {key}")
            if _PLACEHOLDER.search(value):
                raise Refused(f"item {n} still holds a placeholder in {key}")
        if _states_a_limit(item["text"]):
            raise Refused(
                f"item {n} has a number, unit or comparator in its text: never an equipment limit"
            )
        if item["kind"] not in KINDS:
            raise Refused(
                f"item {n} has a kind that is not a completeness kind; allowed: {', '.join(KINDS)}"
            )
        if item["id"].strip() in seen:
            raise Refused(f"item id repeated in item {n}")
        seen.add(item["id"].strip())
    return contract, [{k: str(item[k]).strip() for k in ALLOWED_KEYS} for item in items]


def _live_check(conn) -> None:
    from app import live_guard

    path = next(
        (r[2] for r in conn.execute("PRAGMA database_list") if r[1] == "main"), ""
    )
    if path and live_guard.is_live_shaped(path):
        raise Refused("this is a live-shaped database; load on a copy")


def ensure_table(conn) -> None:
    _live_check(conn)
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name = 'contract_schedule_rule'"
    ).fetchone():
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        for statement in (_TABLE, *_GUARDS):
            conn.execute(statement)
    except BaseException:
        conn.rollback()
        raise
    conn.commit()


def load(conn, contract: str, items: list[dict], actor: str) -> dict:
    """Append the items; a repeat adds nothing, a changed text adds the next version. Counts only."""
    if not (actor or "").strip():
        raise Refused("say who loads the schedule")
    ensure_table(conn)
    out = {"new": 0, "new_version": 0, "unchanged": 0}
    now = datetime.now(UTC).isoformat(timespec="seconds")
    with conn:
        for item in items:
            sha = hashlib.sha256(item["text"].encode("utf-8")).hexdigest()
            last = conn.execute(
                "SELECT version_no, text_sha256 FROM contract_schedule_rule WHERE contract = ? AND item_id = ?"
                " ORDER BY version_no DESC LIMIT 1",
                (contract, item["id"]),
            ).fetchone()
            if last and last[1] == sha:
                out["unchanged"] += 1
                continue
            conn.execute(
                "INSERT INTO contract_schedule_rule (id, contract, item_id, clause, kind, text, text_sha256, source,"
                " version_no, loaded_by, loaded_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    uuid.uuid4().hex,
                    contract,
                    item["id"],
                    item["clause"],
                    item["kind"],
                    item["text"],
                    sha,
                    SOURCE,
                    (last[0] + 1) if last else 1,
                    actor.strip(),
                    now,
                ),
            )
            out["new_version" if last else "new"] += 1
    return out


def current_rules(conn, contract: str | None = None) -> list[dict]:
    """The newest version of each item, as rules with source 'contract schedule'. No table: none."""
    try:
        rows = conn.execute(
            "SELECT contract, item_id, clause, kind, text, source, version_no FROM contract_schedule_rule r"
            " WHERE version_no = (SELECT MAX(version_no) FROM contract_schedule_rule"
            " WHERE contract = r.contract AND item_id = r.item_id) AND (? IS NULL OR contract = ?)"
            " ORDER BY contract, item_id",
            (contract, contract),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    names = ("contract", "id", "clause", "kind", "text", "source", "version")
    return [dict(zip(names, r, strict=True)) for r in rows]


_DASHES = dict.fromkeys(
    map(
        ord, "\u2010\u2011\u2012\u2013\u2014\u2015\u2212\u2043\ufe58\ufe63\uff0d\u00ad"
    ),
    "-",
)


def _normalise(text: str) -> str:
    """One normaliser for the quote check, the absence search and the refusal checks: NFKC (fullwidth letters, digits and
    punctuation to plain), format characters removed (zero-width space and joiner, marks, word joiner, BOM, soft hyphen),
    every dash and the minus sign to a hyphen."""
    folded = unicodedata.normalize("NFKC", str(text or ""))
    folded = "".join(ch for ch in folded if unicodedata.category(ch) != "Cf")
    return folded.translate(_DASHES)


def _fold(text: str) -> str:
    """The quote check's own folding (`compiled_rule_proof.quote_verified`): hyphen breaks joined, whitespace of every
    kind (new line, no-break space) squashed, case folded. The search uses this on the term and on the page."""
    from app.ai_requirements import _squash
    from app.compiled_rule_pages import join_hyphens

    return _squash(join_hyphens(" ".join(_normalise(text).split())))


def _page_no(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def completeness(rule: dict, evidence: dict | None) -> tuple[str, str]:
    """(status, reason) of one schedule item on one submittal, decided here from the submittal's own pages.
    `evidence` = {"pages": {page number: page text}, "page_count": int, "terms": [phrases to look for],
    "found": [{"quote": str, "page": int}]}. Nothing is taken on trust: no flag says a quote is verified or the search
    was whole.
    PRESENT needs a found quote that stands on ITS OWN cited page's text (`compiled_rule_proof.quote_verified`, the one
    quote check) with a page that is a positive whole number. NOT_PRESENT needs every page 1..page_count read
    (page_count > 0, a text for each), at least one search term, no claimed find, and none of the terms on any page.
    Everything else is NEEDS_ENGINEER: unsure never reads as met or as missing."""
    from app.compiled_rule_proof import quote_verified

    if rule.get("kind") not in KINDS:
        return NEEDS_ENGINEER, "the item is not a completeness kind"
    evidence = evidence or {}
    pages = evidence.get("pages") if isinstance(evidence.get("pages"), dict) else {}
    found = [f for f in evidence.get("found") or [] if isinstance(f, dict)]
    for f in found:
        if _page_no(f.get("page")) and quote_verified(
            _normalise(f.get("quote")), _normalise(pages.get(f["page"]))
        ):
            return PRESENT, "a quote that stands on its cited page"
    if found:
        return (
            NEEDS_ENGINEER,
            "something was found but no quote stands on its cited page",
        )
    count = evidence.get("page_count")
    terms = [
        str(t).casefold().strip() for t in evidence.get("terms") or [] if str(t).strip()
    ]
    whole = (
        _page_no(count)
        and set(pages) == set(range(1, count + 1))
        and all(isinstance(t, str) and t.strip() for t in pages.values())
    )
    if not whole:
        return NEEDS_ENGINEER, "not every page was read, so absence is not shown"
    if not terms:
        return NEEDS_ENGINEER, "no search term was given, so absence is not shown"
    if any(_fold(t) in _fold(text) for text in pages.values() for t in terms):
        return NEEDS_ENGINEER, "a search term is on a page but no quote was given"
    return NOT_PRESENT, "every page was read and none holds the item"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", maxsplit=1)[0])
    ap.add_argument(
        "--db", required=True, type=Path, help="a COPY; a live-shaped path is refused"
    )
    what = ap.add_mutually_exclusive_group(required=True)
    what.add_argument(
        "--file", type=Path, help="the LOCAL schedule json, outside the repository"
    )
    what.add_argument(
        "--list",
        action="store_true",
        help="the rules loaded (ids and clauses, no wording)",
    )
    ap.add_argument("--by", help="who loads it")
    args = ap.parse_args(argv)
    from rehearse_requirement_reextraction import refuse_live

    from app.config import settings
    from app.db import connect

    settings.db_path = refuse_live(args.db)
    conn = connect()
    try:
        if args.list:
            rules = current_rules(conn)
            print(
                json.dumps(
                    {
                        "rules": [
                            {
                                k: r[k]
                                for k in ("contract", "id", "clause", "kind", "version")
                            }
                            for r in rules
                        ]
                    }
                )
            )
            return 0
        contract, items = read_items(args.file)
        print(
            json.dumps(
                {
                    "contract": contract,
                    "items": len(items),
                    **load(conn, contract, items, args.by or ""),
                }
            )
        )
    except Refused as refused:
        print(json.dumps({"refused": str(refused)}))
        return EXIT_REFUSED
    return 0


if __name__ == "__main__":
    sys.exit(main())
