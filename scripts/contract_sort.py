"""CONTRACTS SORT (order 14 lane E, 17 Nov 2026): each contract document into ONE part group, by the headings on its opening
pages. READ ONLY, LOCAL ONLY: no model, no network, no write to any database.

    python scripts/contract_sort.py --db <COPY of the database> [--engineer-dir DIR] [--live-db PATH]
                                    [--ledger PATH] [--approved PATH] [--json FILE]

THE GROUPS are fixed (`GROUPS`); 8, "engineer to decide", is a real answer: no cue, cues that name different parts, or a
heading code cannot find on its page. A firm group is a code reading of a heading, shown as one (engineer to confirm).

THE CUES are general headings and labels true for any contract (`CUES` and the labelled parts of `app.contract_checks`:
Schedule, Annex, Appendix, Exhibit, Attachment), read only on the opening (`document_kind._cover_lines`: the cover and the top of
the title page), never a body sentence, never one document's layout (CLAUDE.md rule 13). A cue is ranked by what it says about
the paper (`TIERS`): an amendment or minutes ABOUT a part beats the part's own name, a part's name beats its label, a label beats
the word "agreement". Two different groups at the top rank -> group 8, unless exactly one of them starts its line.

THE REASON of a firm group is the heading line and its page, verified by THE quote check of the app
(`app.contract_checks.verified` -> `compiled_rule_proof.quote_verified`, the check G1 uses). A reason code cannot find -> 8.

WHAT IT PRINTS: document ids, group numbers and names, cue kinds, page numbers, counts and the E1-E9 pass/fail lines. Never a
title, heading, quote or file name: those go ONLY into the engineer file (`--engineer-dir`: contract-sort.xlsx and .md).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import socket
import sqlite3
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for _p in (REPO / "backend", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# the read-only page access of the contract checks command; the labels, the quote check and the CT checklist of the app;
# the opening a paper names itself on (`document_kind`)
from contract_checks import _read_only, load_pages  # noqa: E402

from app import contract_checks as parts  # noqa: E402
from app.compiled_rule_proof import MIN_QUOTE_CHARS  # noqa: E402
from app.document_kind import _NUMBERED_LINE, _cover_lines  # noqa: E402

Pages = list[tuple[int, str]]

GROUPS = {
    1: "main agreement",
    2: "general conditions",
    3: "special / particular conditions",
    4: "schedule, annex, appendix or exhibit",
    5: "attachment / form / template",
    6: "amendment, variation or addendum",
    7: "correspondence or minutes",
    8: "engineer to decide",
}
ENGINEER = 8

#: E9: the contract checks (`reference/contract_checks.json`) that apply to each group, with why.
CHECKS: dict[int, tuple[tuple[str, ...], str]] = {
    1: (
        ("CT-02", "CT-03", "CT-04", "CT-05", "CT-06", "CT-07", "CT-08"),
        "the signed body: its parts, parties, terms, caps, precedence and needed clauses",
    ),
    2: (
        ("CT-03", "CT-04", "CT-05", "CT-06", "CT-07", "CT-08"),
        "the standing clauses: guarantees, terms, caps, precedence, needed clauses",
    ),
    3: (
        ("CT-03", "CT-04", "CT-05", "CT-06", "CT-07"),
        "they change the general conditions: the changed terms, caps and precedence",
    ),
    4: (
        ("CT-01", "CT-02", "CT-04", "CT-05"),
        "a labelled part: payment stages, its own sub-parts, its values and blanks",
    ),
    5: (
        ("CT-03", "CT-05"),
        "a form or attachment: who gives it and what is left blank",
    ),
    6: (
        ("CT-02", "CT-04", "CT-05"),
        "a change: the parts it names, the values it changes, its blanks",
    ),
    7: (
        (),
        "not a contract part: no contract check; the engineer reads it for agreed changes",
    ),
    8: ((), "no check runs until the engineer names the group"),
}

#: The ranks, highest first: what the paper is ABOUT (0), a part's own name (1), a labelled part (2), the word agreement (3).
ABOUT, NAME, LABEL, AGREEMENT = 0, 1, 2, 3
TIERS = {
    ABOUT: "about another part",
    NAME: "part name",
    LABEL: "part label",
    AGREEMENT: "agreement",
}

_W = (
    r"(?i:{})"  # cue words in any case; a number or a letter label stays case-sensitive
)
_NO = r"(?:(?i:no\.?|number|nr\.?|#)\s*)?"
_LAB = r"(?:\d{1,3}|[IVX]{1,5}|[A-Z])(?![\w-])"
CUES: tuple[tuple[str, int, int, re.Pattern[str]], ...] = (
    (
        "amendment",
        6,
        ABOUT,
        re.compile(
            _W.format(
                r"\b(?:amendment|addendum|variation(?:\s+order)?|change\s+order|modification)\s+"
            )
            + _NO
            + _LAB
            + "|"
            + _W.format(r"\b(?:amendment|addendum|variation|change\s+order)\s+to\b")
        ),
    ),
    (
        "minutes",
        7,
        ABOUT,
        re.compile(
            _W.format(
                r"\b(?:minutes\s+of|meeting\s+minutes|record\s+of\s+(?:the\s+)?meeting|transmittal)\b"
            )
        ),
    ),
    (
        "general conditions",
        2,
        NAME,
        re.compile(
            _W.format(
                r"\b(?:general|standard)\s+(?:conditions|terms(?:\s+and\s+conditions)?)\b|\bterms\s+and\s+conditions\b"
            )
        ),
    ),
    (
        "special conditions",
        3,
        NAME,
        re.compile(
            _W.format(
                r"\b(?:special|particular|supplementary|additional)\s+(?:conditions|terms(?:\s+and\s+conditions)?)\b"
                r"|\bconditions\s+of\s+particular\s+application\b"
            )
        ),
    ),
    #: the agreement's own form names the agreement ("Form of Agreement", "Form of Contract"); it is longer than "form of" and
    #: "agreement", so it owns those words on its line.
    (
        "form of agreement",
        1,
        NAME,
        re.compile(
            _W.format(
                r"\bform\s+of\s+(?:the\s+)?(?:contract\s+)?(?:agreement|contract)\b"
            )
        ),
    ),
    (
        "form",
        5,
        NAME,
        re.compile(
            _W.format(
                r"\bform\s+of\b|\bpro[\s-]?forma\b|\btemplate\b|\bformat\s+(?:of|for)\b"
            )
        ),
    ),
    ("schedule of", 4, LABEL, re.compile(_W.format(r"\bschedule\s+of\b"))),
    (
        "agreement",
        1,
        AGREEMENT,
        re.compile(_W.format(r"\b(?:articles\s+of\s+)?agreement\b")),
    ),
)
#: The labelled parts of `app.contract_checks` (LABEL_WORDS) and the group each word names.
LABEL_GROUP = {
    "schedule": 4,
    "appendix": 4,
    "annex": 4,
    "exhibit": 4,
    "attachment": 5,
    "enclosure": 5,
}
#: The signed body's own opening words, read on the first page only: "THIS AGREEMENT is made on ...".
BODY_AGREEMENT = re.compile(
    _W.format(
        r"\bthis\s+(?:agreement|contract)\b[^.;]{0,60}?\b(?:is\s+made|made\s+(?:and\s+entered\s+into\s+)?(?:on|this|as\s+of|"
        r"between)|entered\s+into)\b"
    )
)
#: A label or numbering a heading may start with before its name: "SCHEDULE B - ", "Annex 3: ", "PART II ", "The ".
_PREFIX = re.compile(
    r"^\W*(?:(?i:schedule|appendix|annex|exhibit|attachment|enclosure|part|section)\s*[\"'\u201c\u201d\u2018\u2019]?\s*"
    r"(?:[IVXL]{1,6}|[A-Z]|\d{1,3})(?![A-Za-z0-9])[\"'\u201c\u201d\u2018\u2019]?)?[\s\-\u2013\u2014:.,]*(?:(?i:the)\s+)?"
)
_LETTERED = re.compile(r"^\(?(?:[a-z]|[ivxl]{1,5}|\d{1,3})[.)]\s+\S", re.I)
_CONTENTS = re.compile(
    r"^\W*(?:table\s+of\s+contents|contents|index|list\s+of\b)", re.I
)
_SMALL = {
    "of",
    "and",
    "the",
    "to",
    "for",
    "in",
    "on",
    "a",
    "an",
    "with",
    "by",
    "or",
    "no",
    "no.",
}
HEADING_WORDS = (
    14  # `document_kind._TITLE_WORDS_MAX`: longer is a sentence, not a heading
)
LIST_LABELS = (
    parts.LIST_OTHERS + 1
)  # this many different labels of one word on the opening make it a list of parts
MIN_SHARE = 0.8  # of letters in capitals, or of words capitalised: a heading's shape
TOP_LINES = 8  # a part names itself in the top lines of its page (a list further down names other parts)


@dataclass(frozen=True)
class Cue:
    group: int
    tier: int
    name: str  # a general cue kind, never document words
    page: int
    quote: str  # the heading line: engineer file only
    at_start: bool
    depth: int = -1  # a labelled part's depth (`contract_checks.DEPTH`)
    verified: bool = False


@dataclass
class Sorted:
    document_id: str
    group: int
    why: str  # a general sentence, never document words
    reason: Cue | None = None
    cues: list[Cue] = field(default_factory=list)

    def public(self) -> dict:
        """What may be printed: ids, group, cue kinds, pages, verified flags. No quote."""
        r = self.reason
        return {
            "document_id": self.document_id,
            "group": self.group,
            "group_name": GROUPS[self.group],
            "why": self.why,
            "reason_page": r.page if r else None,
            "reason_cue": r.name if r else None,
            "reason_verified": bool(r and r.verified),
            "cues": [(c.name, c.page, c.verified) for c in self.cues],
        }

    def engineer(self) -> dict:
        return {**self.public(), "reason_quote": self.reason.quote if self.reason else None,
                "cue_quotes": [(c.name, c.page, c.quote, c.verified) for c in self.cues]}  # fmt: skip


# ------------------------------------------------------------------------------------------------ the opening and its cues


def _shaped(text: str) -> bool:
    """A heading's shape: capitals, or every word that is not a small word capitalised."""
    letters = [c for c in text if c.isalpha()]
    if len(letters) >= 3 and sum(c.isupper() for c in letters) >= MIN_SHARE * len(
        letters
    ):
        return True
    words = [w for w in re.findall(r"[^\W\d_][\w'-]*", text) if w.lower() not in _SMALL]
    return bool(words) and sum(w[0].isupper() for w in words) >= MIN_SHARE * len(words)


def is_heading(text: str) -> bool:
    """A short line, not a list entry, not a sentence: what a paper names itself with."""
    words = text.split()
    if not words or len(words) > HEADING_WORDS or text.endswith((",", ";")):
        return False
    if text.endswith(".") and len(words) >= 6:
        return False
    return not (_NUMBERED_LINE.match(text) or _LETTERED.match(text))


def opening(pages: Pages) -> list[tuple[int, str]]:
    """The cover lines (`document_kind._cover_lines`) that stand in the TOP_LINES of their page, each once; on a page, nothing
    after a contents heading."""
    top = {
        p: {
            ln.strip().strip("|").strip()
            for ln in [x for x in t.splitlines() if x.strip()][:TOP_LINES]
        }
        for p, t in pages
    }
    stopped: set[int] = set()
    out: list[tuple[int, str]] = []
    for page, line in _cover_lines([{"page_no": p, "text": t} for p, t in pages]):
        text = line.strip().strip("|").strip()
        if (
            not text
            or page in stopped
            or (page, text) in out
            or text not in top.get(page, ())
        ):
            continue
        if _CONTENTS.match(text):
            stopped.add(page)
            continue
        out.append((page, text))
    return out


def _quote(lines: list[tuple[int, str]], i: int) -> str:
    """The heading line; a line too short for the quote check takes the next line of its page with it."""
    page, text = lines[i]
    if len(text) < MIN_QUOTE_CHARS and i + 1 < len(lines) and lines[i + 1][0] == page:
        return f"{text} {lines[i + 1][1]}"
    return text


def _word_cues(lines: list[tuple[int, str]], i: int) -> list[Cue]:
    page, text = lines[i]
    if not is_heading(text):
        return []
    start = _PREFIX.match(text).end()
    shaped, found = _shaped(text), []
    for name, group, tier, rx in CUES:
        for m in rx.finditer(text):
            at_start = m.start() <= start
            if shaped or at_start:
                found.append(
                    (
                        m.end() - m.start(),
                        m.start(),
                        Cue(group, tier, name, page, _quote(lines, i), at_start),
                    )
                )
    kept: list[tuple[int, int, Cue]] = []
    for size, pos, cue in sorted(
        found, key=lambda f: (-f[0], f[1])
    ):  # the longest cue owns its words
        if all(pos + size <= p or p + s <= pos for s, p, _c in kept):
            kept.append((size, pos, cue))
    return [c for _s, _p, c in sorted(kept, key=lambda k: k[1])]


def _label_cues(lines: list[tuple[int, str]]) -> list[Cue]:
    """A line that starts with a labelled part (`contract_checks._heading_part`); a word with LIST_LABELS different labels on the
    opening is a list of parts: it names them, it is none of them (as `contract_checks.package_part`)."""
    found = []
    for i, (page, text) in enumerate(lines):
        if is_heading(text) and parts._heading_part(text):
            for word, label, _pos in parts.labels(text):
                found.append((word, label, Cue(LABEL_GROUP[word], LABEL, f"label: {word}", page, _quote(lines, i),
                                               at_start=True, depth=parts.DEPTH[word])))  # fmt: skip
    listed = {
        w
        for w, _l, _c in found
        if len({lab for w2, lab, _c2 in found if w2 == w}) >= LIST_LABELS
    }
    return [c for w, _l, c in found if w not in listed]


def cues_of(pages: Pages) -> list[Cue]:
    lines = opening(pages)
    out = [c for i in range(len(lines)) for c in _word_cues(lines, i)] + _label_cues(
        lines
    )
    if pages:
        first_page, first_text = pages[0]
        m = BODY_AGREEMENT.search(" ".join(first_text.split()))
        if m:
            out.append(
                Cue(
                    1,
                    AGREEMENT,
                    "agreement opening words",
                    first_page,
                    m.group(0),
                    at_start=False,
                )
            )
    return out


# ------------------------------------------------------------------------------------------------ the decision


def decide(document_id: str, cues: list[Cue], pages: Pages) -> Sorted:
    """ONE group. Every cue's quote is checked on its page first; the top rank decides; two groups there -> 8 unless exactly one
    group starts its line; the deciding quote must verify, else 8."""
    on = dict(pages)
    cues = [
        replace(c, verified=parts.verified(c.quote, on.get(c.page, ""))) for c in cues
    ]
    if not cues:
        return Sorted(
            document_id,
            ENGINEER,
            "no heading on the opening names a part of a contract",
            None,
            [],
        )
    top = min(c.tier for c in cues)
    lead = [c for c in cues if c.tier == top]
    if top == LABEL and any(c.depth >= 0 for c in lead):
        deepest = max(c.depth for c in lead)
        lead = [c for c in lead if c.depth in (deepest, -1)]
    if len({c.group for c in lead}) > 1:
        starting = [c for c in lead if c.at_start]
        if len({c.group for c in starting}) != 1:
            return Sorted(
                document_id,
                ENGINEER,
                f"headings of rank '{TIERS[top]}' name different parts",
                None,
                cues,
            )
        lead = starting
    group = lead[0].group
    proof = next((c for c in lead if c.verified), None)
    if proof is None:
        return Sorted(
            document_id,
            ENGINEER,
            "the deciding heading was not found on its page by the quote check",
            None,
            cues,
        )
    return Sorted(
        document_id,
        group,
        f"heading ({TIERS[top]}) on the opening, quote verified on its page",
        proof,
        cues,
    )


def sort_pages(document_id: str, pages: Pages) -> Sorted:
    return decide(document_id, cues_of(pages), pages)


# ------------------------------------------------------------------------------------------------ the proof (E1-E9)


def sha256(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def line_count(path: Path | None) -> int:
    if path is None or not path.is_file():
        return 0
    with path.open("rb") as fh:
        return sum(block.count(b"\n") for block in iter(lambda: fh.read(1 << 20), b""))


def approved_counts(path: Path | None, conn: sqlite3.Connection) -> dict:
    """Counts only: rows of the Claude approved list by status, its checksum, and the consent tables of the copy."""
    out: dict = {"list_sha256": sha256(path), "list_rows": {}}
    if path is not None and path.is_file():
        try:
            rows = (json.loads(path.read_text(encoding="utf-8")) or {}).get(
                "documents"
            ) or []
        except (OSError, ValueError, AttributeError):
            rows = None
        for r in rows if isinstance(rows, list) else []:
            status = str(r.get("status", "?")) if isinstance(r, dict) else "?"
            out["list_rows"][status] = out["list_rows"].get(status, 0) + 1
    for table in ("contract_yes", "review_claude_consent"):
        try:
            out[table] = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        except sqlite3.OperationalError:
            out[table] = None
    return out


@contextmanager
def no_network(attempts: list):
    """Every outbound connection during the run is refused and counted (Claude, a second AI, a web search, a local model)."""
    saved = (
        socket.socket.connect,
        socket.socket.connect_ex,
        socket.create_connection,
        socket.getaddrinfo,
    )

    def refuse(*_a, **_k):
        attempts.append(1)
        raise OSError("contract_sort runs without network")

    socket.socket.connect = socket.socket.connect_ex = refuse  # type: ignore[method-assign]
    socket.create_connection = socket.getaddrinfo = refuse  # type: ignore[assignment]
    try:
        yield
    finally:
        (
            socket.socket.connect,
            socket.socket.connect_ex,
            socket.create_connection,
            socket.getaddrinfo,
        ) = saved


TRANSPORTS = (
    "market_transport",
    "model_transport",
    "reader_transport",
    "notifications",
)


def own_imports() -> list[str]:
    """The rule-1 socket modules this file's own code imports (expected: none)."""
    src = Path(__file__).read_text(encoding="utf-8")
    return [
        t
        for t in TRANSPORTS
        if re.search(rf"^\s*(?:from|import)\s[^\n]*\b{t}\b", src, re.M)
    ]


def contract_ids(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT document_id FROM document_classification WHERE document_role = 'CONTRACT_DOCUMENT' ORDER BY document_id")]  # fmt: skip


def kind_needs_engineer(conn: sqlite3.Connection) -> set[str]:
    """The contracts the kind decider left to the engineer (`document_kinds.state`)."""
    try:
        return {
            r[0]
            for r in conn.execute(
                "SELECT document_id FROM document_kinds WHERE state = 'needs_engineer'"
            )
        }
    except sqlite3.OperationalError:
        return set()


def run_once(db: str, ids: list[str]) -> list[Sorted]:
    return [sort_pages(d, load_pages(db, d)) for d in ids]


def checks(
    first: list[Sorted],
    second: list[Sorted],
    ids: list[str],
    held_back: set[str],
    proof: dict,
) -> list[tuple[str, bool, str]]:
    out = []
    one = [s.document_id for s in first]
    ok = (
        sorted(one) == sorted(ids)
        and len(set(one)) == len(one)
        and all(s.group in GROUPS for s in first)
    )
    out.append(
        (
            "E1",
            ok,
            f"{len(ids)} documents, {len(set(one))} with exactly one group, {len(set(ids) - set(one))} without",
        )
    )
    firm = [s for s in first if s.group != ENGINEER]
    bad = [s.document_id for s in firm if not (s.reason and s.reason.verified)]
    out.append(
        (
            "E2",
            not bad,
            f"{len(firm)} firm groups, {len(firm) - len(bad)} with a heading verified on its page",
        )
    )
    names = (
        {n for n, *_ in CUES}
        | {f"label: {w}" for w in LABEL_GROUP}
        | {"agreement opening words"}
    )
    odd = [s.document_id for s in firm if s.reason.name not in names]
    out.append(
        (
            "E3",
            not odd,
            f"every firm group from the fixed general cues ({len(names)} kinds); {len(odd)} from elsewhere",
        )
    )
    e4 = (
        proof["ledger_before"] == proof["ledger_after"]
        and proof["sockets"] == 0
        and not proof["own_imports"]
    )
    out.append(("E4", e4, f"Claude ledger lines {proof['ledger_before']} -> {proof['ledger_after']}; outbound connection "
                          f"attempts {proof['sockets']} (Claude, second AI, web: none); transport imports in this tool "
                          f"{len(proof['own_imports'])}"))  # fmt: skip
    same = [a.engineer() for a in first] == [b.engineer() for b in second]
    out.append(
        (
            "E5",
            same,
            f"two runs, {'identical' if same else 'DIFFERENT'} group and reason for {len(first)}",
        )
    )
    forced = [s.document_id for s in first if s.document_id in held_back and s.group != ENGINEER
              and not (s.reason and s.reason.verified)]  # fmt: skip
    in_firm = sum(
        1 for s in first if s.document_id in held_back and s.group != ENGINEER
    )
    out.append(("E6", not forced, f"{len(held_back & set(ids))} left to the engineer by the kind decider: {in_firm} in a firm "
                                  f"group, each with a verified heading; {len(forced)} forced"))  # fmt: skip
    out.append(
        (
            "E7",
            proof["approved_before"] == proof["approved_after"],
            "approved-to-send list counts and checksum "
            f"{'identical' if proof['approved_before'] == proof['approved_after'] else 'CHANGED'} before and after",
        )
    )
    e8 = proof["live_before"] == proof["live_after"] and proof["copy_not_live"]
    out.append(("E8", e8, f"read a copy ({'not the live file' if proof['copy_not_live'] else 'THE LIVE FILE'}); live "
                          f"checksum {'unchanged' if proof['live_before'] == proof['live_after'] else 'CHANGED'}"))  # fmt: skip
    known = {i["id"] for i in parts.checklist()["items"]}
    e9 = set(CHECKS) == set(GROUPS) and all(
        set(c) <= known for c, _w in CHECKS.values()
    )
    out.append(("E9", e9, "each group lists its contract checks: " + "; ".join(
        f"{g}: {', '.join(c) or 'none'}" for g, (c, _w) in sorted(CHECKS.items()))))  # fmt: skip
    return out


# ------------------------------------------------------------------------------------------------ the engineer file (local only)


def write_engineer(folder: Path, sorted_: list[Sorted], kinds: set[str]) -> list[Path]:
    """The form for E10, local only: each document, the tool's group, its heading and page, and an EMPTY engineer's group."""
    from openpyxl import Workbook

    folder.mkdir(parents=True, exist_ok=True)
    rows = []
    for s in sorted_:
        e = s.engineer()
        rows.append([s.document_id, s.group, GROUPS[s.group], s.why, e["reason_quote"] or "", e["reason_page"] or "",
                     "yes" if e["reason_verified"] else "no", ", ".join(CHECKS[s.group][0]) or "none",
                     "engineer to decide" if s.document_id in kinds else "contract",
                     " | ".join(f"{n} p{p}{'' if v else ' (not found on page)'}: {q}" for n, p, q, v in e["cue_quotes"]),
                     "", ""])  # fmt: skip
    head = ["document", "tool group", "group name", "why", "heading (reason)", "page", "verified on page", "contract checks",
            "kind decider", "all cues read", "engineer's group (1-8)", "cause if different"]  # fmt: skip
    wb = Workbook()
    ws = wb.active
    ws.title = "sort"
    ws.append([f"{len(rows)} contract documents sorted, {len(rows)} in this file. Code reading of headings: engineer to confirm. "
               "Accuracy not yet measured."])  # fmt: skip
    ws.append(head)
    for r in rows:
        ws.append(r)
    groups = wb.create_sheet("groups")
    groups.append(["group", "name", "documents", "contract checks", "why these checks"])
    for g, name in GROUPS.items():
        groups.append(
            [
                g,
                name,
                sum(1 for s in sorted_ if s.group == g),
                ", ".join(CHECKS[g][0]) or "none",
                CHECKS[g][1],
            ]
        )
    xlsx = folder / "contract-sort.xlsx"
    wb.save(xlsx)
    md = folder / "contract-sort.md"
    lines = ["# Contracts sort (local only, engineer to confirm)", "",
             f"{len(rows)} contract documents sorted, {len(rows)} in this file. Accuracy not yet measured.", "",
             "| " + " | ".join(head) + " |", "|" + "---|" * len(head)]  # fmt: skip
    lines += [
        "| " + " | ".join(str(c).replace("|", "/").replace("\n", " ") for c in r) + " |"
        for r in rows
    ]
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return [xlsx, md]


# ------------------------------------------------------------------------------------------------ the command


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--db", required=True, help="a COPY of the database (opened read only)"
    )
    ap.add_argument(
        "--engineer-dir",
        type=Path,
        help="where the local engineer file goes (titles and headings: never printed)",
    )
    ap.add_argument(
        "--live-db",
        type=Path,
        help="the live database: its checksum is taken before and after (E8)",
    )
    ap.add_argument(
        "--ledger",
        type=Path,
        help="the Claude spend ledger: lines counted before and after (E4)",
    )
    ap.add_argument(
        "--approved",
        type=Path,
        help="the Claude approved list: counted before and after (E7)",
    )
    ap.add_argument(
        "--json",
        type=Path,
        help="write the printable result (no document words) to this file",
    )
    a = ap.parse_args(argv)
    db = Path(a.db).resolve()
    if a.live_db is not None and db == a.live_db.resolve():
        print("REFUSED: --db is the live database; run on a copy.")
        return 2
    live_files = [Path(f"{a.live_db}{s}") for s in ("", "-wal")] if a.live_db else []
    conn = _read_only(str(db))
    try:
        ids, held_back = contract_ids(conn), kind_needs_engineer(conn)
        proof = {"live_before": [sha256(p) for p in live_files], "ledger_before": line_count(a.ledger),
                 "approved_before": approved_counts(a.approved, conn), "own_imports": own_imports(),
                 "copy_not_live": a.live_db is None or db != a.live_db.resolve()}  # fmt: skip
        attempts: list = []
        with no_network(attempts):
            first, second = run_once(str(db), ids), run_once(str(db), ids)
        proof.update(sockets=len(attempts), ledger_after=line_count(a.ledger),
                     approved_after=approved_counts(a.approved, conn), live_after=[sha256(p) for p in live_files])  # fmt: skip
    finally:
        conn.close()
    print(f"contract documents (role CONTRACT_DOCUMENT): {len(ids)}")
    for s in first:
        p = s.public()
        print(f"  {s.document_id}  group {s.group} ({GROUPS[s.group]})  cue: {p['reason_cue'] or '-'}  page: "
              f"{p['reason_page'] or '-'}  verified: {'yes' if p['reason_verified'] else 'no'}"
              f"{'  [kind decider: engineer]' if s.document_id in held_back else ''}")  # fmt: skip
    for g, name in GROUPS.items():
        print(f"group {g} ({name}): {sum(1 for s in first if s.group == g)}")
    results = checks(first, second, ids, held_back, proof)
    for code, ok, text in results:
        print(f"{code} {'PASS' if ok else 'FAIL'}: {text}")
    print("E10 accuracy not yet measured (the engineer fills the form)")
    if a.engineer_dir:
        written = write_engineer(a.engineer_dir, first, held_back)
        print(
            f"engineer file written: {len(written)} files in --engineer-dir (local only, not printed)"
        )
    if a.json:
        a.json.write_text(
            json.dumps(
                {"documents": [s.public() for s in first], "checks": results}, indent=1
            ),
            encoding="utf-8",
        )
    return 0 if all(ok for _c, ok, _t in results) else 1


if __name__ == "__main__":
    sys.exit(main())
