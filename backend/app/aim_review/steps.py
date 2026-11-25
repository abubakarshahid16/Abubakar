"""S1 identify and S4 judge: the two steps that read the paper. One code path for every paper.

`_decide` is the measured experiment's code part of a judgment, unchanged: the quote verified by code, the numbers compared by
code, a value the vendor left open is a Question, a knowledge item is never Met or Not met. Only its number comparison now goes
through the app's own unit code (`verify.compare`) instead of the experiment's own conversion.
"""

from __future__ import annotations

import json
import logging
import re

from . import (
    CONTRACTOR_FILLED,
    PAPER_COMPARE_PASSED,
    PROVISIONAL,
)
from . import items as I
from . import library as L
from . import prompts as P
from .engine import StepFailed
from .fail_words import (  # noqa: F401 - one home: fail_words
    PAIRED_NOTE,
    PROVEN_FAIL,
    _fails_comment,
    _num,
    proven_fail,
)
from .verify import (
    compare,
    find_page,
    met_unproven,
    norm,
    paper_relation,
    rule_operator,
    value_in,
)

log = logging.getLogger(__name__)

LABELS = ("Met", "Not met", "Question", "Does not apply", "AI opinion")
HELD = "held standard"
KNOWLEDGE = "not from a held standard"
NOT_JUDGED = "not_judged"
NOT_ON_ANY_PAGE = "not_on_any_page"
#: The words code writes on such a line (code's own filler: no field, page or quote of the paper is named by it).
NOT_ON_ANY_PAGE_WORDS = "the paper does not show this on any page"
JUDGE_BATCH = 8
#: At most this many places (findings) per item: an item that fails on several sheets of one paper gives one line per place.
MAX_FINDINGS = 6
#: The judge's output room: 8 items x up to 6 findings each.
JUDGE_MAX_TOKENS = 24000
#: At most this many judge calls in flight at once (the one setting; `aim_review.parallel`).
JUDGE_PARALLEL = 3
CLAUSE_WINDOW = 900
#: In a windowed judgment, the order in which one item's answers from several windows are kept: a verified quote first, then
#: the label that asks the most of the vendor (a firm finding is never hidden behind a "met" read in another part of the paper).
_KEEP_ORDER = ("Not met", "Met", "AI opinion", "Question", "Does not apply")


def _dumps(o) -> str:
    return json.dumps(o, ensure_ascii=False)


def paper_block(paper, only: list[int] | None = None) -> str:
    return P.PAPER_HEAD + paper.text_with_markers(only)


# ------------------------------------------------------------------ S1 identify


def s1_identify(model, paper, known: list[str], lead: str) -> dict:
    types = "\n".join(f"{t['id']}: {t['name']}" for t in L.taxonomy())
    out = model.ask(
        step="aim_identify",
        model=lead,
        system="",
        cached=paper_block(paper),
        prompt=P.S1_TASK
        % {
            "kinds": _dumps(list(L.KINDS)),
            "types": types,
            "known": _dumps(known or []),
        },
        carries={paper.paper_id},
        max_tokens=6000,
        effort="low",
    )
    if not isinstance(out, dict):
        raise StepFailed("aim_identify: not_an_object")
    kind = str(out.get("kind") or "other").strip().lower()
    kind = kind if kind in L.KINDS else "other"
    etype = out.get("equipment_type")
    etype = etype if etype in L.type_ids() else None
    ev = [
        _verified(e, paper.pages)
        for e in out.get("evidence") or []
        if isinstance(e, dict)
    ]
    cited, cited_dropped = [], []
    for c in out.get("cited") or []:
        if not isinstance(c, dict) or not str(c.get("name") or "").strip():
            continue
        v = _verified(c, paper.pages)
        (cited if v["verified"] else cited_dropped).append({**c, **v})
    key = (
        re.sub(
            r"[^a-z0-9_]+", "_", str(out.get("subject_key") or etype or kind).lower()
        ).strip("_")[:60]
        or kind
    )
    scope = (
        _verified(out["scope"], paper.pages)
        if isinstance(out.get("scope"), dict)
        else None
    )
    return {
        "kind": kind,
        "equipment_type": etype,
        # the paper's stated scope: kept ONLY as a quote code found on its page (K1; no free text beyond it)
        "scope_quote": scope["quote"][:300] if scope and scope["verified"] else "",
        "scope_page": scope["page"] if scope and scope["verified"] else None,
        "subject": str(out.get("subject") or "")[:200],
        "subject_key": key,
        "service": str(out.get("service") or "")[:400],
        "evidence": ev,
        "evidence_verified": sum(1 for e in ev if e["verified"]),
        "cited": cited,
        "cited_unverified": cited_dropped,
    }


def _verified(row: dict, pages: dict[int, str]) -> dict:
    q = str(row.get("quote") or "")
    hint = row.get("page") if isinstance(row.get("page"), int) else None
    found = find_page(q, pages, hint)
    return {
        "page": found if found is not None else hint,
        "quote": q,
        "verified": found is not None,
    }


# ------------------------------------------------------------------ S4 judge


def _clause_context(text: L.BookText, it: dict) -> str:
    if it["source"] != HELD or not it.get("book_id"):
        return ""
    page_text = text.page(it["book_id"], int(it.get("page") or 0)) or ""
    flat = re.sub(r"\s+", " ", page_text)
    q = norm(it["rule_quote"])[:40]
    i = norm(flat).find(q) if q else -1
    if i < 0:
        return flat[: 2 * CLAUSE_WINDOW]
    return flat[max(0, i - CLAUSE_WINDOW // 2) : i + CLAUSE_WINDOW]


#: What a sent Question asks, as recorded on its line (`_ask`; recorded only, nothing leaves the comments because of it).
ASK_CONCERN, ASK_CONFIRM, ASK_OPEN = "concern", "confirm", "open"


def _ask(j: dict, label: str, deferred: bool, code_cmp, nums, note: str = "") -> str:
    """The mark of a Question line, decided by code from the judge's "ask" and the run's state; "" for any other label.
    "concern" when code saw a conflict (a failed compare, numbers the judge gave), on ANY provisional figure (a figure beside a
    who-supplies note is never only confirmed) or when the judge suspects the value; "open" when the value is left open (the judge's deferred flag or code reading the quote as open: a judge's
    "confirm" there stays a question to the vendor, never "confirm"); "confirm" only on the judge's own word; any other answer
    (missing, unknown) is "concern" (the safe side)."""
    if label != "Question":
        return ""
    failed = isinstance(code_cmp, dict) and code_cmp.get("result") == "fail"
    provisional = any(
        x.strip().startswith(PROVISIONAL) for x in str(note or "").split(";")
    )
    if failed or nums or provisional or j.get("ask") == ASK_CONCERN:
        return ASK_CONCERN
    if deferred:
        return ASK_OPEN
    return ASK_CONFIRM if j.get("ask") == ASK_CONFIRM else ASK_CONCERN


def _compare(
    it: dict, label: str, nums, quote: str, notes: list[str], paper, deferred: bool
):
    """(label, code's comparison). CODE DOES EVERY NUMBER AND UNIT COMPARISON (the project's top rule): a Met / Not met with
    numbers is decided by code (a held or always-on item); and a Question or AI opinion whose numbers code reads from VERIFIED
    quotes against a HELD rule's limit is decided by code too, whatever the AI's label: a fail is a Fail by code, a pass a Pass
    by code (18 Nov 2026 after live: the judge kept "Question" on filled-in figures, so code never compared them). When code
    reaches no verdict ("unclear", a paper-vs-paper pairing, a value it cannot read) the AI's label stands. A value left open
    is never compared."""
    held = it["source"] == HELD
    rule_quote = str(it.get("rule_quote") or "")
    if nums and quote and label in ("Met", "Not met") and (held or it.get("always_on")):
        return _numbers(
            nums, quote, rule_quote, notes, paper, it.get("what_to_check") or ""
        )
    if nums and held and quote and not deferred and label in ("Question", "AI opinion"):
        tried: list[str] = []
        new, cmp_ = _numbers(
            nums, quote, rule_quote, tried, paper, it.get("what_to_check") or ""
        )
        if (
            isinstance(cmp_, dict)
            and cmp_.get("read_from") == "verified quotes"
            and cmp_.get("result") in ("pass", "fail")
        ):
            notes.extend(tried)
            return new, cmp_
    if it["kind"] == "limit" and label in ("Met", "Not met") and held:
        notes.append("a limit with no numbers for code to compare")
        return "Question", None
    return label, None


def _left_open(j: dict, quote: str, page, notes: list[str]) -> bool:
    """Is the judged value left open? A figure the contractor FILLED IN beside a who-supplies note is a stated value, judged as
    any value (owner, 18 Nov 2026 after live; the note says so on the line; Pass/Fail only when code compares it with a held
    rule): never left open, whatever the judge's flag. Otherwise the judge's flag or code reading the quote as open."""
    filled = page is not None and _provisional_figure(quote)
    if filled:
        notes.append(CONTRACTOR_FILLED)
    return (bool(j.get("deferred")) and not filled) or _deferred(quote)


def _deferred(quote: str) -> bool:
    """THE one decision "the paper leaves this value open" for a quote: `blank_markers.value_left_open` (the one list; the lead's
    decision of 18 Nov 2026). A pending marker (TBA, TBC, TBD, later, VTA, a lone "*"), a blank form, or a who-supplies note
    ("By Contractor", "as per Code") with no figure stated; a who-supplies note beside a stated figure is not open."""
    from app import blank_markers

    return blank_markers.value_left_open(quote)


def _paper_limit(
    nums: dict, paper: dict, quote: str, paper_doc
) -> tuple[dict | None, int | None]:
    """The limit when the PAPER states it (a value and its limit both on the paper): read by code from the judged quote itself (a
    number other than the paper value), else from the judge's `limit_quote`, which must be found on a page of the paper first."""
    wanted = nums.get("rule_value")
    here = value_in(wanted, nums.get("rule_unit"), quote)
    if here is not None and here["value"] != paper["value"]:
        return here, None
    second = str(nums.get("limit_quote") or "")
    hint = nums.get("limit_page") if isinstance(nums.get("limit_page"), int) else None
    page = find_page(second, paper_doc.pages, hint) if second else None
    found = value_in(wanted, nums.get("rule_unit"), second)
    return (found, page) if page is not None else (None, None)


def _paper_numbers(
    nums: dict,
    paper: dict,
    quote: str,
    rule_quote: str,
    notes: list[str],
    paper_doc,
    check: str = "",
) -> tuple[str, dict | None]:
    """PAPER vs PAPER (the lead, 18 Nov 2026): the rule's words hold no value, the paper states both the value and its limit. Code
    reads both from verified paper quotes and compares them by the app's unit code, with the operator of the rule's verified words
    (`rule_operator`), else the AI's. It is NEVER a code verdict: the model chose which paper number is the limit, so code did
    not prove the pairing. The line is an AI opinion (a Question when provisional), the comparison in its code note; a failed
    compare is sent with both numbers, a passed one is held back (`_code_note`). "Compared by code" stays for a paper value
    against a number of the VERIFIED RULE quote only (review R1, B1)."""
    limit, limit_page = _paper_limit(nums, paper, quote, paper_doc)
    if limit is None:
        notes.append(
            "the rule value is not in the rule's verified words nor in a verified quote of the paper"
        )
        return "Question", None
    op, op_from = rule_operator(rule_quote), "the rule's verified words"
    oriented = paper_relation(check, quote, str(nums.get("limit_quote") or ""))
    if oriented:
        op, op_from = (
            oriented,
            "the checklist relationship between the quoted paper fields",
        )
    if op is None:
        op, op_from = str(nums.get("operator") or ""), "the AI's answer"
    code_cmp = compare(paper["value"], paper["unit"], op, limit["value"], limit["unit"])
    if code_cmp["result"] == "cannot":
        notes.append("code could not compare the two paper values: " + code_cmp["why"])
        return "Question", code_cmp
    code_cmp.update(
        read_from="verified paper quotes", op=op, op_from=op_from, limit_page=limit_page
    )
    notes.append("code compared two values of the paper: " + code_cmp["why"])
    notes.append(
        "the AI chose which paper value is the limit: an AI opinion, never a code verdict"
    )
    return "AI opinion", code_cmp


def _paper_compare(code_cmp, page: int | None) -> bool:
    """Is this a compare of two paper values? Then a limit read from the judged quote itself is on the judged page."""
    if not (
        isinstance(code_cmp, dict)
        and code_cmp.get("read_from") == "verified paper quotes"
    ):
        return False
    if code_cmp.get("limit_page") is None:
        code_cmp["limit_page"] = page
    return True


def _provisional_figure(quote: str) -> bool:
    from app import blank_markers

    return blank_markers.is_provisional_figure(quote)


def _shown_item(it: dict, books: dict, text: L.BookText) -> dict:
    b = books.get(it.get("book") or "")
    return {
        "id": it["id"],
        "topic": it["topic"],
        "what_to_check": it["what_to_check"],
        "standard": b["identifier"] if b else "",
        "clause": it["clause"],
        "rule_quote": it["rule_quote"],
        "clause_text": it.get("context") or _clause_context(text, it),
        "applies_when": it["applies_when"],
        "paper_fields": it["paper_fields"],
        "paper_pages": it["paper_pages"],
        "kind": it["kind"],
        "source": it["source"],
    }


def item_book(it: dict, books: dict) -> str:
    """The document id an item's clause text comes from ('' for a knowledge item)."""
    if it.get("source") != HELD:
        return ""
    b = books.get(it.get("book") or "")
    return str(it.get("book_id") or (b or {}).get("book") or "")


def s4_judge(
    model,
    paper,
    checklist: dict,
    text: L.BookText,
    *,
    items: list[dict],
    windows: list[list[int]],
    lead: str,
    cancelled=None,
    progress=None,
    scope: dict | None = None,
) -> tuple[list[dict], str]:
    """The decided lines of `items`, by item then by page, and a stop code ('' when every batch was asked). An item gives one
    line, or one line per PLACE where it fails or is left open (a paper of several sheets of the same kind; `_lines_of`).

    One window (the paper fits): the measured method exactly. Several windows (a long paper): every batch is judged in each
    window; an item's answers are merged by `_merge`. A batch never asked (cancelled, or the run stopped) is 'not judged'."""
    from . import parallel

    books = {b["alias"]: b for b in checklist.get("books") or []}
    windowed = len(windows) > 1
    answers: dict[str, list[dict]] = {it["id"]: [] for it in items}
    errors: dict[str, str] = {}
    batches = [items[k : k + JUDGE_BATCH] for k in range(0, len(items), JUDGE_BATCH)]
    jobs: list[
        tuple[list[dict], dict]
    ] = []  # (batch, request) in window, then batch order: the one-at-a-time order
    for win in windows or [sorted(paper.pages)]:
        cached = paper_block(paper, win if windowed else None)
        head = (
            P.WINDOW_LINE
            % {"first": win[0], "last": win[-1], "count": len(paper.pages)}
            if windowed
            else ""
        ) + _scope_line(scope)
        jobs += [
            (b, _batch_request(paper, b, books, text, cached, head, lead))
            for b in batches
        ]
    total, finished = max(1, len(jobs)), [0]

    def tick() -> None:
        finished[0] += 1
        if progress is not None:
            progress(int(100 * finished[0] / total), "judge")

    results, stop = parallel.run_calls(
        model,
        [r for _b, r in jobs],
        workers=JUDGE_PARALLEL,
        cancelled=cancelled,
        done=tick,
    )
    for (batch, _r), got in zip(
        jobs, results, strict=True
    ):  # merged in the one-at-a-time order
        if got is None:
            continue  # never asked (cancelled, or the run stopped): its items are "not judged"
        if got[0] == "failed":
            for it in batch:
                errors.setdefault(it["id"], str(got[1]))
            continue
        rows = _rows(got[1])
        for it in batch:
            # N1: the guard reads the MODEL's own label, before code relabels anything (fix check 961f7126, B1)
            answers[it["id"]].extend(
                _scope_unverified(j, bool(_scope_line(scope)))
                for j in rows.get(it["id"]) or []
            )
    lines = [
        line
        for it in items
        for line in _lines_of(
            it, answers[it["id"]], paper, books, errors.get(it["id"], ""), windowed
        )
    ]
    return lines, stop


#: A reason that says the PAPER'S scope, phase or stage differs ("outside the paper's stated scope", "the procedure covers the
#: design phase only"): never a supply scope ("the vendor's scope of supply") nor the word "scope" alone.
_SCOPE_OUTSIDE = re.compile(
    r"\b(?:outside|beyond|not\s+within|out\s+of)\s+(?:the\s+)?"
    r"(?:(?:paper|document|procedure|study)'?s\s+(?:stated\s+)?|stated\s+)scope\b(?!\s+of\s+supply)",
    re.IGNORECASE,
)
_SCOPE_COVERS = re.compile(
    r"\bthe\s+(?:paper|document|procedure|study)\s+(?:only\s+)?(?:covers|is\s+(?:for|about|limited\s+to)|applies\s+to)\b"
    r"([^.;]*)",
    re.IGNORECASE,
)
_PHASE_WORD = re.compile(r"\b(?:phase|stage)s?\b", re.IGNORECASE)
#: A word before "phase" / "stage" that makes it a COUNT or an order ("three-phase", "the second stage of the item"),
#: not a life-cycle phase of the paper.
_COUNT_WORDS = frozenset(
    [
        "one",
        "two",
        "three",
        "four",
        "five",
        "six",
        "seven",
        "eight",
        "nine",
        "ten",
        "single",
        "double",
        "triple",
        "multi",
        "multiple",
        "first",
        "second",
        "third",
        "fourth",
        "fifth",
        "sixth",
        "final",
        "last",
        "next",
        "each",
        "every",
        "several",
        "many",
        "both",
    ]
)


def _scope_reason(comment: str) -> bool:
    """Does the reason say the PAPER's scope, phase or stage differs? "outside the paper's (stated) scope" (never "... scope of
    supply"), or "the paper / procedure / study covers / is for / applies to ... phase / stage" where that phase or stage is not
    a count or an order: not after a hyphen ("single-stage"), a count word ("three phase") or an ordinal ("2nd stage")."""
    text = str(comment or "")
    if _SCOPE_OUTSIDE.search(text):
        return True
    for clause in (m.group(1) for m in _SCOPE_COVERS.finditer(text)):
        for w in _PHASE_WORD.finditer(clause):
            before = clause[: w.start()]
            if before.endswith("-"):
                continue
            prev = re.search(r"(\w+)\W*$", before)
            word = prev.group(1).lower() if prev else ""
            if word in _COUNT_WORDS or re.fullmatch(r"\d+(?:st|nd|rd|th)?", word):
                continue
            return True
    return False


SCOPE_NOT_VERIFIED = (
    "a scope reason with no scope the paper states (verified): a question"
)


def _scope_unverified(j: dict, verified: bool) -> dict:
    """N1, enforced in code on the MODEL's own answer: a "Does not apply" whose reason says the paper's scope, phase or stage
    differs stands only when S1 found the paper's scope quote on its page; without it the answer is judged as a Question (and
    `_decide` notes why). Code's own relabels (a knowledge item's Met) are never touched: they happen later, in `_decide`."""
    if verified or not isinstance(j, dict) or j.get("label") != "Does not apply":
        return j
    if not _scope_reason(j.get("comment")):
        return j
    return {**j, "label": "Question", "scope_unverified": True}


def _scope_line(identity: dict | None) -> str:
    """The paper's stated scope for the judge (K1), only when S1's quote was verified on its page; else nothing."""
    quote = str((identity or {}).get("scope_quote") or "")
    page = (identity or {}).get("scope_page")
    return (
        P.SCOPE_LINE % {"page": page, "quote": quote}
        if quote and isinstance(page, int)
        else ""
    )


def _batch_request(
    paper,
    batch: list[dict],
    books: dict,
    text: L.BookText,
    cached: str,
    head: str,
    lead: str,
) -> dict:
    """One judge call's request for one batch, built on the calling thread (it reads rule books). Declares the paper and the
    batch's books only."""
    carries = (
        {paper.paper_id}
        | {b for b in (item_book(it, books) for it in batch) if b}
        | {str(c) for it in batch for c in it.get("carries") or ()}
    )
    return {
        "step": "aim_judge",
        "model": lead,
        "system": "",
        "cached": cached,
        "prompt": head
        + P.s4_task()
        % {"items": "\n".join(_dumps(_shown_item(it, books, text)) for it in batch)},
        "carries": carries,
        "max_tokens": JUDGE_MAX_TOKENS,
    }


def _rows(out) -> dict[str, list[dict]]:
    """{item id: [the model's findings]}, one per place (a row per place with the item's id, or one row with a "findings" list)."""
    rows = (out or {}).get("judgments") or [] if isinstance(out, dict) else []
    got: dict[str, list[dict]] = {}
    for j in rows:
        if not isinstance(j, dict):
            continue
        key = str(j.get("id"))
        found = j.get("findings")
        places = (
            [f for f in found if isinstance(f, dict)]
            if isinstance(found, list)
            else [j]
        )
        got.setdefault(key, []).extend({**f, "id": key} for f in places)
    return got


def _lines_of(
    it: dict, js: list[dict], paper, books: dict, err: str, windowed: bool
) -> list[dict]:
    """The lines of ONE item from all its findings (every window, every place). Each finding is decided by `_decide`, unchanged.
    No finding: "not judged". A long paper whose every part said "not here": one Question, the paper shows it on no page."""
    here = [j for j in js if not j.get("not_here")] if windowed else list(js)
    if (
        windowed and not here and js and not err
    ):  # every part of the paper was read and none shows it
        line = _decide(
            it,
            {
                "label": "Question",
                "comment": NOT_ON_ANY_PAGE_WORDS,
            },
            paper,
            books,
            "",
        )
        line["code"] = NOT_ON_ANY_PAGE
        return [dict(line, finding_no=1)]
    if not here:
        return [dict(_decide(it, None, paper, books, err), finding_no=1)]
    return _places(
        [I.check(_decide(it, j, paper, books, ""), j, paper) for j in here]
    )  # an item's value, not another's


def _places(decided: list[dict]) -> list[dict]:
    """One line per PLACE where the item fails or is left open (a sent line with a verified quote), by page, the same place once,
    at most MAX_FINDINGS (the rest counted in the first line's code note). None such: the one best line, as before (a verified
    quote first, then the label that asks the most of the vendor)."""
    from . import sendable

    seen, places = set(), []
    for d in decided:
        key = (d.get("page"), norm(d.get("quote") or ""))
        if (
            d.get("quote")
            and key not in seen
            and sendable({"label": d["label"], "code_note": d.get("code")})
        ):
            seen.add(key)
            places.append(d)
    if not places:
        decided.sort(
            key=lambda d: (
                not d.get("quote"),
                _KEEP_ORDER.index(d["label"]) if d["label"] in _KEEP_ORDER else 9,
            )
        )
        return [dict(decided[0], finding_no=1)]
    places.sort(key=lambda d: d.get("page") or 0)
    kept, extra = places[:MAX_FINDINGS], len(places) - MAX_FINDINGS
    if extra > 0:
        more = f"{extra} more place(s) of this item not listed (at most {MAX_FINDINGS} per item)"
        kept[0]["code"] = "; ".join(x for x in (kept[0].get("code"), more) if x)
    return [dict(d, finding_no=n) for n, d in enumerate(kept, 1)]


def decided_as(it: dict, note: str, paper, books: dict) -> dict:
    """An item code decides does not apply (a saved item from a company rule book the paper does not cite): "Does not apply",
    its note as the whole code note (never sent, never counted as a book to review again)."""
    line = _decide(it, {"label": "Does not apply", "comment": note}, paper, books, "")
    line["code"] = note
    return line


def _decide(it: dict, j: dict | None, paper, books: dict, err: str) -> dict:
    """Code's part of the judgment: the quote, the numbers, the deferred value, the knowledge-item limit."""
    b = books.get(it.get("book") or "")
    base = {
        "item_id": it["id"],
        "standard": b["identifier"] if b else "",
        "clause": it["clause"],
        "source": it["source"],
        "topic": it["topic"],
        "named_books": list(
            it.get("named_books") or []
        ),  # an always-on item: the listed books its words name (rule 5)
    }
    if j is None:
        return {
            **base,
            "field": "",
            "page": None,
            "label": "Question",
            "quote": "",
            "comment": "not judged (" + (err or "no answer for this item") + ")",
            "code": NOT_JUDGED,
        }
    label = j.get("label") if j.get("label") in LABELS else "Question"
    quote = str(j.get("quote") or "")
    hint = j.get("page") if isinstance(j.get("page"), int) else None
    page = find_page(quote, paper.pages, hint) if quote else None
    notes = []
    if quote and page is None:
        notes.append("paper quote not found by code")
        if label in ("Met", "Not met"):
            label = "Question"
    if label in ("Met", "Not met") and not quote:
        label, _ = "Question", notes.append("no paper quote for a verdict")
    if j.get("scope_unverified"):
        notes.append(SCOPE_NOT_VERIFIED)
    deferred = _left_open(j, quote, page, notes)
    if (
        deferred and label != "Question"
    ):  # ANY label (owner, 18 Nov): a value left to the vendor is a Question
        label = "Question"
        notes.append(
            "the value is left open by the vendor: a question, never a verdict"
        )
    nums = j.get("numbers") if isinstance(j.get("numbers"), dict) else None
    # code compares ONLY a quote it found on the paper (review of update 5, B1): an unfound quote is never compared, never firm
    label, code_cmp = _compare(
        it, label, nums, quote if page is not None else "", notes, paper, deferred
    )
    if it["source"] != HELD and label in (
        "Met",
        "Not met",
    ):  # any knowledge item (not held, or not from a held standard)
        label = "AI opinion" if label == "Not met" else "Does not apply"
        notes.append("not from a held standard: never Met or Not met")
    # the judge said Met and code could not prove it: internal only, never sent
    notes += met_unproven(j.get("label"), label, nums, deferred, code_cmp)
    code_note = _code_note(notes, code_cmp, j.get("label"))
    return {
        **base,
        "field": str(j.get("field") or "")[:100],
        "page": page if page is not None else hint,
        "label": label,
        "quote": quote if page is not None else "",
        "quote_unverified": quote if (quote and page is None) else "",
        "comment": _comment(
            j,
            code_cmp,
            quote,
            base,
            page,
            proven_fail(label, code_cmp, deferred, notes),
        ),
        "code": code_note,
        "numbers": nums,
        "code_compare": code_cmp,
        "deferred": deferred,
        "ask": _ask(j, label, deferred, code_cmp, nums, code_note),
    }


def _comment(
    j: dict, code_cmp, quote: str, base: dict, page, firm: bool = False
) -> str:
    """The AI's comment; for a FAILED compare of two paper values, code's sentence with both numbers and the limit's page first;
    for a fail proven by code (`proven_fail`), code's firm sentence alone (the AI's words could still ask to "confirm")."""
    said = str(j.get("comment") or "")
    if firm:
        return _fails_comment(
            code_cmp, quote, base, firm=True
        )  # whole: never cut without a mark
    if _paper_compare(code_cmp, page) and code_cmp.get("result") == "fail":
        said = _fails_comment(code_cmp, quote, base) + (" " + said if said else "")
    return said  # whole: the sheet cuts with its own mark and keeps the full text on All points


def _code_note(notes: list[str], code_cmp: dict | None, said: str | None = None) -> str:
    """The line's code note: its notes joined. A PASSED compare of two paper values (an AI pairing) is held back from the comments
    by APPENDING `PAPER_COMPARE_PASSED` (the notes say why): when the operator came from the rule's verified words, or from the AI
    when the AI itself (`said`, its own label) did not say Not met. The AI's Not met on its own operator stays a sent AI opinion."""
    held = (
        isinstance(code_cmp, dict)
        and code_cmp.get("read_from") == "verified paper quotes"
        and code_cmp.get("result") == "pass"
        and (
            code_cmp.get("op_from") == "the rule's verified words" or said != "Not met"
        )
    )
    return "; ".join([*notes, PAPER_COMPARE_PASSED] if held else notes)


def _numbers(
    nums: dict,
    quote: str,
    rule_quote: str,
    notes: list[str],
    paper_doc=None,
    check: str = "",
) -> tuple[str, dict | None]:
    """A held item's numbers. A code stamp rests ONLY on the verified quotes (review R1, B1): the paper value and its unit are read
    by code from the verified paper quote, the rule value, its unit and the operator from the item's verified rule quote
    (`verify.quoted_value`); the model's numbers only say WHICH value is meant. Then code compares (`verify.compare`, the app's
    unit code) and its result decides the label. Anything code cannot read from the quotes is a Question. (label, comparison)."""
    # the judge may give a figure it converted: code then finds the quote's own printed figure and converts it itself
    paper = value_in(nums.get("paper_value"), nums.get("paper_unit"), quote)
    if paper and paper.get("converted"):
        notes.append("code read the printed figure: " + paper["converted"])
    if paper is None:
        notes.append("the paper value is not in the verified quote")
        return "Question", None
    rule = value_in(nums.get("rule_value"), nums.get("rule_unit"), rule_quote)
    if rule is None and paper_doc is not None:
        return _paper_numbers(nums, paper, quote, rule_quote, notes, paper_doc, check)
    if rule is None:
        notes.append("the rule value is not in the rule's verified words")
        return "Question", None
    if not rule["op"]:
        notes.append("the rule's verified words give no comparison code can read")
        return "Question", None
    told = (
        str(nums.get("paper_unit") or ""),
        str(nums.get("operator") or ""),
        str(nums.get("rule_unit") or ""),
    )
    if told != (paper["unit"], rule["op"], rule["unit"]):
        notes.append(
            "units and operator read from the quotes, not from the AI's answer"
        )
    code_cmp = compare(
        paper["value"], paper["unit"], rule["op"], rule["value"], rule["unit"]
    )
    code_cmp["read_from"] = "verified quotes"
    code_cmp["op"] = rule["op"]
    notes.append("code compared: " + code_cmp["why"])
    return {"pass": "Met", "fail": "Not met"}.get(
        code_cmp["result"], "Question"
    ), code_cmp
