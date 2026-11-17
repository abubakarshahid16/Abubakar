"""S1 identify and S4 judge: the two steps that read the paper. One code path for every paper.

`_decide` is the measured experiment's code part of a judgment, unchanged: the quote verified by code, the numbers compared by
code, a value the vendor left open is a Question, a knowledge item is never Met or Not met. Only its number comparison now goes
through the app's own unit code (`verify.compare`) instead of the experiment's own conversion.
"""

from __future__ import annotations

import json
import re

from . import (
    PAPER_COMPARE_PASSED,
    PROVISIONAL,
    PROVISIONAL_FAILS,
    PROVISIONAL_UNCHECKED,
)
from . import library as L
from . import prompts as P
from .engine import StepFailed
from .verify import compare, find_page, norm, quoted_value, rule_operator

LABELS = ("Met", "Not met", "Question", "Does not apply", "AI opinion")
HELD = "held standard"
KNOWLEDGE = "not from a held standard"
NOT_JUDGED = "not_judged"
NOT_ON_ANY_PAGE = "not_on_any_page"
JUDGE_BATCH = 8
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
    return {
        "kind": kind,
        "equipment_type": etype,
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
    here = quoted_value(wanted, quote)
    if here is not None and here["value"] != paper["value"]:
        return here, None
    second = str(nums.get("limit_quote") or "")
    hint = nums.get("limit_page") if isinstance(nums.get("limit_page"), int) else None
    page = find_page(second, paper_doc.pages, hint) if second else None
    return (quoted_value(wanted, second), page) if page is not None else (None, None)


def _paper_numbers(
    nums: dict, paper: dict, quote: str, rule_quote: str, notes: list[str], paper_doc
) -> tuple[str, dict | None]:
    """PAPER vs PAPER (the lead, 18 Nov 2026): the rule's words hold no value, the paper states both the value and its limit. Code
    reads both from verified paper quotes and compares them by the app's unit code. The operator comes from the rule's verified
    words (`rule_operator`): then the label follows the result ("compared by code"). When no rule gives it, the AI's operator is
    used and the line is an AI opinion, the comparison in its code note: never a code verdict."""
    limit, limit_page = _paper_limit(nums, paper, quote, paper_doc)
    if limit is None:
        notes.append(
            "the rule value is not in the rule's verified words nor in a verified quote of the paper"
        )
        return "Question", None
    op, op_from = rule_operator(rule_quote), "the rule's verified words"
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
    if op_from == "the AI's answer":
        notes.append(
            "no rule gives the comparison: an AI opinion, never a code verdict"
        )
        return "AI opinion", code_cmp
    return {"pass": "Met", "fail": "Not met"}[code_cmp["result"]], code_cmp


def _provisional_figure(quote: str) -> bool:
    from app import blank_markers

    return blank_markers.is_provisional_figure(quote)


#: What a failed check says of the stated figure, by the rule's operator.
_FAILS_AS = {
    "<=": "is above the {r} limit",
    "<": "is not below the {r} limit",
    ">=": "is below the {r} minimum",
    ">": "is not above the {r} minimum",
    "==": "is not the {r} required",
    "!=": "is the {r} excluded",
}


def _provisional(
    it: dict, j: dict, quote: str, page: int, base: dict, paper_doc=None
) -> dict:
    """A PROVISIONAL figure (a stated figure beside a who-supplies note; verified quote): code checks it from the verified quotes
    as for any value, but the label is ALWAYS Question (the standing order: a value left to the vendor is a Question, nothing
    unproven is a Pass or Fail). A failed check is a sent Question that states the check in numbers (`PROVISIONAL_FAILS`); a
    check code could not run is a sent Question with the AI's comment (`PROVISIONAL_UNCHECKED`); only a PASSED check stays in
    "All points" (`PROVISIONAL`, never sent). The limit may be the rule's or one the paper states (`_paper_numbers`)."""
    nums = j.get("numbers") if isinstance(j.get("numbers"), dict) else None
    code_cmp = None
    if nums and it["source"] == HELD:
        _label, code_cmp = _numbers(
            nums, quote, str(it.get("rule_quote") or ""), [], paper_doc
        )
    result = code_cmp.get("result") if isinstance(code_cmp, dict) else None
    fails = result == "fail"
    note = {"fail": PROVISIONAL_FAILS, "pass": PROVISIONAL}.get(
        str(result), PROVISIONAL_UNCHECKED
    )
    return {
        **base,
        "field": str(j.get("field") or "")[:100],
        "page": page,
        "label": "Question",
        "quote": quote,
        "quote_unverified": "",
        "comment": _fails_comment(code_cmp, quote, base)
        if fails
        else str(j.get("comment") or "")[:400],
        "code": note,
        "numbers": nums,
        "code_compare": code_cmp,
        "deferred": False,
    }


def _num(v) -> str:
    return f"{float(v):f}".rstrip("0").rstrip(".")


def _fails_comment(code_cmp: dict, quote: str, base: dict) -> str:
    """The sent comment of a failed provisional figure, every number from code's check of the verified quotes."""
    from app import blank_markers

    (pv, pu), (rv, ru) = code_cmp["paper"], code_cmp["rule"]
    stated = f"{_num(pv)} {pu}".strip()
    rule = f"{_num(rv)} {ru}".strip()
    who = blank_markers.who_supplies(quote) or "who supplies it"
    if code_cmp.get("read_from") == "verified paper quotes":
        page = code_cmp.get("limit_page")
        where = f"page {page} of this paper" if page else "this paper"
    elif base.get("standard"):
        where = f"{base['standard']} clause {base['clause']}".strip()
    else:
        where = "the rule"
    fails = _FAILS_AS.get(str(code_cmp.get("op") or ""), "does not meet the {r} rule")
    return f"The stated {stated} ({who.lower()}) {fails.format(r=rule)} of {where}; contractor to confirm the value."


def _shown_item(it: dict, books: dict, text: L.BookText) -> dict:
    b = books.get(it.get("book") or "")
    return {
        "id": it["id"],
        "topic": it["topic"],
        "what_to_check": it["what_to_check"],
        "standard": b["identifier"] if b else "",
        "clause": it["clause"],
        "rule_quote": it["rule_quote"],
        "clause_text": _clause_context(text, it),
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
) -> tuple[list[dict], str]:
    """One decided line per item of `items`, in order, and a stop code ('' when every batch was asked).

    One window (the paper fits): the measured method exactly. Several windows (a long paper): every batch is judged in each
    window; an item's answers are merged by `_merge`. A batch never asked (cancelled, or the run stopped) is 'not judged'."""
    books = {b["alias"]: b for b in checklist.get("books") or []}
    windowed = len(windows) > 1
    answers: dict[str, list[dict]] = {it["id"]: [] for it in items}
    errors: dict[str, str] = {}
    stop = ""
    batches = [items[k : k + JUDGE_BATCH] for k in range(0, len(items), JUDGE_BATCH)]
    total = max(1, len(batches) * max(1, len(windows)))
    done = 0
    for win in windows or [sorted(paper.pages)]:
        cached = paper_block(paper, win if windowed else None)
        head = (
            (
                P.WINDOW_LINE
                % {"first": win[0], "last": win[-1], "count": len(paper.pages)}
            )
            if windowed
            else ""
        )
        for batch in batches:
            if stop:
                break
            if cancelled is not None and cancelled():
                stop = "cancelled"
                break
            try:
                got = _ask_batch(model, paper, batch, books, text, cached, head, lead)
            except StepFailed as exc:
                code = str(exc)
                for it in batch:
                    errors.setdefault(it["id"], code)
                if exc.stops_run:
                    stop = code
                continue
            for it in batch:
                j = got.get(it["id"])
                if j is not None:
                    answers[it["id"]].append(j)
            done += 1
            if progress is not None:
                progress(int(100 * done / total), "judge")
        if stop:
            break
    lines = [
        _merge(it, answers[it["id"]], paper, books, errors.get(it["id"], ""), windowed)
        for it in items
    ]
    return lines, stop


def _ask_batch(
    model,
    paper,
    batch: list[dict],
    books: dict,
    text: L.BookText,
    cached: str,
    head: str,
    lead: str,
) -> dict:
    """One judge call for one batch: {item id: the model's judgment}. Declares the paper and the batch's books only."""
    carries = {paper.paper_id} | {
        b for b in (item_book(it, books) for it in batch) if b
    }
    out = model.ask(
        step="aim_judge",
        model=lead,
        system="",
        cached=cached,
        prompt=head
        + P.S4_TASK
        % {"items": "\n".join(_dumps(_shown_item(it, books, text)) for it in batch)},
        carries=carries,
        max_tokens=12000,
    )
    rows = (out or {}).get("judgments") or [] if isinstance(out, dict) else []
    return {str(j.get("id")): j for j in rows if isinstance(j, dict)}


def _merge(
    it: dict, js: list[dict], paper, books: dict, err: str, windowed: bool
) -> dict:
    if not windowed:
        return _decide(it, js[0] if js else None, paper, books, err)
    here = [j for j in js if not j.get("not_here")]
    if not here:
        if js and not err:  # every part of the paper was read and none shows it
            line = _decide(
                it,
                {
                    "label": "Question",
                    "comment": "the paper does not show this on any page",
                },
                paper,
                books,
                "",
            )
            line["code"] = NOT_ON_ANY_PAGE
            return line
        return _decide(it, None, paper, books, err)
    decided = [_decide(it, j, paper, books, "") for j in here]
    decided.sort(
        key=lambda d: (
            not d.get("quote"),
            _KEEP_ORDER.index(d["label"]) if d["label"] in _KEEP_ORDER else 9,
        )
    )
    return decided[0]


def _decide(it: dict, j: dict | None, paper, books: dict, err: str) -> dict:
    """Code's part of the judgment: the quote, the numbers, the deferred value, the knowledge-item limit."""
    b = books.get(it.get("book") or "")
    base = {
        "item_id": it["id"],
        "standard": b["identifier"] if b else "",
        "clause": it["clause"],
        "source": it["source"],
        "topic": it["topic"],
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
    if page is not None and _provisional_figure(quote):
        return _provisional(it, j, quote, page, base, paper)
    deferred = bool(j.get("deferred")) or _deferred(quote)
    if (
        deferred and label != "Question"
    ):  # ANY label (owner, 18 Nov): a value left to the vendor is a Question
        label = "Question"
        notes.append(
            "the value is left open by the vendor: a question, never a verdict"
        )
    nums = j.get("numbers") if isinstance(j.get("numbers"), dict) else None
    code_cmp = None
    if nums and label in ("Met", "Not met") and it["source"] == HELD:
        label, code_cmp = _numbers(
            nums, quote, str(it.get("rule_quote") or ""), notes, paper
        )
    elif it["kind"] == "limit" and label in ("Met", "Not met") and it["source"] == HELD:
        label = "Question"
        notes.append("a limit with no numbers for code to compare")
    if it["source"] == KNOWLEDGE and label in ("Met", "Not met"):
        label = "AI opinion" if label == "Not met" else "Does not apply"
        notes.append("not from a held standard: never Met or Not met")
    return {
        **base,
        "field": str(j.get("field") or "")[:100],
        "page": page if page is not None else hint,
        "label": label,
        "quote": quote if page is not None else "",
        "quote_unverified": quote if (quote and page is None) else "",
        "comment": str(j.get("comment") or "")[:400],
        "code": _code_note(notes, code_cmp),
        "numbers": nums,
        "code_compare": code_cmp,
        "deferred": deferred,
    }


def _code_note(notes: list[str], code_cmp: dict | None) -> str:
    """The line's code note: its notes joined; a PASSED compare of two paper values with the AI's operator is held back from the
    comments (`PAPER_COMPARE_PASSED`; the comparison itself is kept in `code_compare`)."""
    if (
        isinstance(code_cmp, dict)
        and code_cmp.get("op_from") == "the AI's answer"
        and code_cmp.get("result") == "pass"
    ):
        return PAPER_COMPARE_PASSED
    return "; ".join(notes)


def _numbers(
    nums: dict, quote: str, rule_quote: str, notes: list[str], paper_doc=None
) -> tuple[str, dict | None]:
    """A held item's numbers. A code stamp rests ONLY on the verified quotes (review R1, B1): the paper value and its unit are read
    by code from the verified paper quote, the rule value, its unit and the operator from the item's verified rule quote
    (`verify.quoted_value`); the model's numbers only say WHICH value is meant. Then code compares (`verify.compare`, the app's
    unit code) and its result decides the label. Anything code cannot read from the quotes is a Question. (label, comparison)."""
    paper = quoted_value(nums.get("paper_value"), quote)
    if paper is None:
        notes.append("the paper value is not in the verified quote")
        return "Question", None
    rule = quoted_value(nums.get("rule_value"), rule_quote)
    if rule is None and paper_doc is not None:
        return _paper_numbers(nums, paper, quote, rule_quote, notes, paper_doc)
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
