"""Convert the lab labeller's table into a product label file (11 Nov 2026), so labels already paid for are not paid twice.

NOTHING IS TRUSTED FROM THE LAB. For every lab row that holds a model's answer, this module takes only the lab's stored
per-pass ANSWERS (model, prompt version, kind, field, reading) and decides again with the product's own `decide`:
  * the rule and its quote are read from THIS copy's own tables (`rule_label_import._stored_rule`), never from the lab;
  * the quote is found again by the product's own check (`compiled_rule_proof.quote_verified`) on the page the rule
    cites, or, for a lab row that says `quote_recovery = "page"`, on the page the lab names; every other recovery mode
    is `quote_not_found`;
  * each stored reading is re-proved against the quote (`rule_labels.check_reading`);
  * the lab's prompt version ("rule-label-v2", no first-words echo) is accepted only here, and the rows are marked
    `origin: "lab-order12"`; both passes must carry the same version;
  * a quote on a recognised (OCR) page of low or unknown page confidence is never approved (the product's page rule).
A row the product cannot prove comes out `needs_human` with the cause, or `quote_not_found`; nothing is promoted. The lab's
state is used for one thing only: counting how many of its approvals the product kept, and why it lost the rest.
Reads the copy only. Writes a label file with no quote text.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter

from . import rule_label_import, rule_labels
from .compiled_rule_proof import quote_verified
from .rule_label_schema import AI_APPROVED, QUOTE_NOT_FOUND


def _json(raw):
    try:
        return json.loads(raw) if raw else []
    except ValueError:
        return None


def _pass(row, p: str, quote: str, fallback_prompt: str | None):
    """The lab's stored answer of pass `p` as a product PassAnswer, or None when the lab holds none."""
    if row[f"{p}_model"] is None:
        return None
    values = _json(row[f"{p}_values"])
    raw = {
        "comparator": row[f"{p}_comparator"],
        "values": values,
        "unit": row[f"{p}_unit"],
        "strength": row[f"{p}_strength"],
        "subject": row[f"{p}_subject"],
    }
    kind, field = row[f"{p}_paper_kind"], row[f"{p}_field"]
    if values is None or not isinstance(values, list) or not rule_labels.shape_ok(raw):
        valid, reading = (
            False,
            {
                "comparator": None,
                "values": [],
                "unit": None,
                "strength": None,
                "subject": "",
            },
        )
    else:
        valid, reading = rule_labels.check_reading(raw, quote)
    content = {"paper_kind": kind, "field": field, "reading": reading, "valid": valid}
    return rule_labels.PassAnswer(
        row[f"{p}_model"],
        row[f"{p}_prompt_version"] or fallback_prompt or "",
        kind,
        field,
        reading,
        valid,
        rule_labels.answer_hash(content),
    )


def convert(conn: sqlite3.Connection, pages_of, page_origin) -> tuple[list[dict], dict]:
    """(label rows in the product's file shape, counts). `pages_of(sdid)` and `page_origin(sdid)` give the page text and
    origin as the app cites them."""
    conn.row_factory = sqlite3.Row
    rows, counts, lost = [], Counter(), Counter()
    for lab in conn.execute(
        "SELECT * FROM rule_label WHERE a_model IS NOT NULL OR b_model IS NOT NULL ORDER BY source, rule_ref"
    ):
        counts["lab_rows"] += 1
        counts["lab_" + str(lab["state"])] += 1
        held = rule_label_import._stored_rule(conn, lab["source"], lab["rule_ref"])
        if held is None:
            counts["unknown_rule"] += 1
            lost["unknown_rule"] += lab["state"] == AI_APPROVED
            continue
        rule = held[0]
        quote = rule["quote"]
        recovery = lab["quote_recovery"]
        page = rule["page"]
        found = False
        text = pages_of(rule["sdid"])
        if recovery is None:
            found = bool(quote_verified(quote, text.get(page)))
        elif recovery == "page" and lab["quote_page"] is not None:
            page = lab["quote_page"]
            found = bool(quote_verified(quote, text.get(page)))
        a = _pass(lab, "a", quote, lab["prompt_version"])
        b = _pass(lab, "b", quote, lab["prompt_version"])
        if a is None:
            counts["lab_pass_b_only_skipped"] += 1
            continue
        low = (
            rule_labels.page_is_low_confidence_ocr(page_origin(rule["sdid"]).get(page))
            if found
            else False
        )
        d = rule_labels.decide(
            a,
            b,
            quote_found=found,
            quote_text=quote,
            quote_ocr_low=low,
            prompt_version=a.prompt
            if a.prompt in rule_labels.LAB_PROMPTS
            else rule_labels.PROMPT_VERSION,
        )
        if d is None:
            continue
        if d.state == AI_APPROVED and lab["state"] != AI_APPROVED:
            # never promoted: the lab's own (stricter) checks said no, so a person decides
            d = rule_labels.Decision(
                "needs_human", d.paper_kind, d.field, "lab_not_approved", d.reading
            )
        if d.state != AI_APPROVED and lab["state"] == AI_APPROVED:
            why = (
                "quote_not_found"
                if d.state == QUOTE_NOT_FOUND
                else (d.disagreement or d.state)
            )
            for part in why.split(","):
                lost[part] += 1
            counts["lab_approved_lost"] += 1
        counts["product_" + d.state] += 1
        if d.state == "labelled_a":
            continue
        accepted = (a.prompt if a else None) in rule_labels.LAB_PROMPTS
        rows.append(
            {
                "source": lab["source"],
                "rule_ref": lab["rule_ref"],
                "rule_version_id": None,
                "paper_kind": d.paper_kind,
                "field": d.field,
                "state": d.state,
                "disagreement": d.disagreement,
                "a_model": a.model if a else None,
                "a_prompt": a.prompt if a else None,
                "a_answer_sha256": a.answer_sha256 if a else None,
                "b_model": b.model if b else None,
                "b_prompt": b.prompt if b else None,
                "b_answer_sha256": b.answer_sha256 if b else None,
                "quote_page": page if found else None,
                "quote_sha256": rule_labels.quote_hash(quote),
                "quote_recovery": recovery if found and recovery == "page" else None,
                "labelled_at": lab["labelled_at"],
                "reading": dict(d.reading) if d.reading else None,
                "origin": rule_labels.LAB_ORIGIN if accepted else None,
            }
        )
    return rows, {**counts, "lost_reasons": dict(+lost)}


def write(rows: list[dict], out) -> None:
    from pathlib import Path

    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "format": rule_label_import.EXPORT_FORMAT,
                "prompt_versions": list(rule_labels.LAB_PROMPTS),
                "rows": rows,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
