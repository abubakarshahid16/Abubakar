"""#805 STEP 8: the AI judges sentence rules and scoped rules against ONE submittal, at review time, on a COPY.

WHICH RULES. From the labelled store: box b rules ("stored by kind") and rules whose status is `scoped: judge at review
time`, for the submittal's document kind and its equipment type (or `general`). The scope text of a scoped rule goes to
the model with the rule.

HOW. At most `PER_PROMPT` rules per prompt, each prompt asked TWICE as two independent calls (the second reorders the
rules and says so, so it is a new ask and never a replay of the cached first). Each rule gets a verdict (pass / fail /
query / not_applicable), the page and the exact words of the submittal that support it, and, for a scoped rule, whether
its scope applies to this equipment (yes / no / unsure).

CODE DECIDES WHAT STANDS (AI proposes, code verifies, the engineer decides):
  * the quote must stand on the cited page of the submittal (`compiled_rule_proof.quote_verified`); the page must exist;
  * the rule text and clause shown are the stored ones, taken from the store by code, never from the reply;
  * a Pass needs verified quoted evidence, a Fail or a Query needs a verified quote; else `needs engineer`;
  * the two calls must give the same verdict and the same scope answer, else `needs engineer` with both shown;
  * a scoped rule whose scope is `unsure` or differs is `needs engineer`; `no` (both calls) means it does not apply and
    no row is made;
  * a verdict row is only ever Fail, Query or needs engineer, or a Pass that carries its verified evidence. Every row says
    `AI judgement, engineer to confirm`.

Standards text and the one approved submittal only. Counts only in a report. Nothing is written to the live database.
"""

from __future__ import annotations

import json
import re
import time

from app import datasheet_checks
from app.compiled_rule_proof import quote_verified
from rule_box_tools import rule_box_check, rule_box_labels, rule_box_run

PER_PROMPT = 5
JUDGE_VERSION = "box-judge-v1"
JUDGED = "rule_box_judgements"
LABEL = "AI judgement, engineer to confirm"
VERDICTS = ("pass", "fail", "query", "not_applicable")
SCOPE_ANSWERS = ("yes", "no", "unsure")
NEEDS_ENGINEER = "needs engineer"
FINAL = {"pass": "Pass", "fail": "Fail", "query": "Query"}
JUDGE_TOKENS = 1500
QUOTE_CHARS = 900


def ensure_schema(conn) -> None:
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {JUDGED} (document_id TEXT NOT NULL, rule_id TEXT NOT NULL, status TEXT NOT NULL,"
        " reason TEXT, page INTEGER, evidence TEXT, scope_text TEXT, scope_applies TEXT, clause TEXT, rule_quote TEXT,"
        " calls_json TEXT, label TEXT NOT NULL, model TEXT NOT NULL, prompt_version TEXT NOT NULL, created_at TEXT NOT NULL,"
        " PRIMARY KEY (document_id, rule_id))"
    )
    conn.commit()


def submittal_types(equipment_type: str | None) -> set[str]:
    """Vocabulary types whose field list is the submittal's own, plus `general`."""
    table = datasheet_checks.load_rules().get("checklists") or {}
    key = datasheet_checks.table_key(equipment_type, table) if equipment_type else None
    out = {rule_box_labels.GENERAL}
    for t in rule_box_labels.equipment_types():
        if rule_box_labels.checklist_name(t) and rule_box_labels.checklist_name(t) == (
            key if key in table else equipment_type
        ):
            out.add(t)
    return out


def pages_of(conn, document_id: str) -> dict[int, str]:
    return {
        r["page_no"]: r["text"] or ""
        for r in conn.execute(
            "SELECT page_no, text FROM pages WHERE document_id = ? ORDER BY page_no",
            (document_id,),
        )
    }


def relevant_rules(conn, document_id: str, kind: str = "datasheet") -> list:
    doc = conn.execute(
        "SELECT x.equipment_type FROM document_classification x WHERE x.document_id = ?",
        (document_id,),
    ).fetchone()
    types = submittal_types(doc["equipment_type"] if doc else None)
    marks = ",".join("?" for _ in types)
    return conn.execute(
        "SELECT r.id, r.standard_document_id, r.clause, r.quote, k.status, k.scope_text, k.reason AS scope_reason,"
        " l.equipment_type, l.document_kind"
        f" FROM compiled_rules r JOIN {rule_box_labels.TABLE} l ON l.rule_id = r.id"
        f" JOIN {rule_box_check.CHECKS} k ON k.rule_id = r.id"
        f" WHERE k.status IN ('{rule_box_check.BY_KIND}', '{rule_box_check.rule_box_scope.SCOPED}')"
        f" AND l.equipment_type IN ({marks}) AND l.document_kind IN (?, 'any')"
        " AND NOT EXISTS (SELECT 1 FROM "
        + JUDGED
        + " j WHERE j.rule_id = r.id AND j.document_id = ?)"
        " ORDER BY r.standard_document_id, r.page, r.id",
        (*sorted(types), kind, document_id),
    ).fetchall()


def prompt_for(
    rows: list,
    label_of_standard: dict[str, str],
    pages: dict[int, str],
    order: list[int],
    second: bool,
) -> str:
    text = "\n\n".join(f"=== PAGE {n} ===\n{t}" for n, t in pages.items())
    parts = []
    for shown, idx in enumerate(order, 1):
        r = rows[idx]
        scope = (
            f"\n   SCOPE OF THIS RULE (keep it): {' '.join(str(r['scope_text']).split())[:600]}"
            if r["status"] != rule_box_check.BY_KIND
            else ""
        )
        parts.append(
            f"{shown}. [{label_of_standard.get(r['standard_document_id'], '')}, clause {r['clause']}] "
            f"{' '.join(str(r['quote']).split())[:QUOTE_CHARS]}{scope}"
        )
    again = (
        "This is an independent second reading: judge each rule afresh from the datasheet alone.\n"
        if second
        else ""
    )
    return (
        "You review ONE submitted datasheet against requirements of engineering standards, as a careful senior engineer.\n"
        f"{again}"
        "For each numbered requirement answer: verdict = pass (the datasheet meets it), fail (it breaks it), query (the"
        " datasheet is unclear, silent or contradictory on it) or not_applicable (the requirement is not about this"
        " datasheet). Give the page number and the EXACT words copied from that page that support the verdict (needed for"
        " pass, fail and query). If a requirement has a SCOPE, say scope_applies = yes, no or unsure: does that scope"
        " describe this equipment? Never guess: when unsure say query / unsure.\n\n"
        f"REQUIREMENTS:\n" + "\n".join(parts) + f"\n\nTHE DATASHEET:\n{text}\n\n"
        'Answer ONLY a JSON array, one object per requirement in order: [{"i": 1, "verdict": "...", "scope_applies":'
        ' "yes" | "no" | "unsure" | null, "page": <number or null>, "quote": "<exact words>" | null, "reason": "<one'
        ' short sentence>"}].'
    )


def parse(text: str):
    from app.ai.json_reply import unfenced

    try:
        data = json.loads(unfenced(text))
    except (ValueError, TypeError):
        decoder, raw = json.JSONDecoder(), str(text or "")
        data = None
        for m in re.finditer(r"\[", raw):
            try:
                data, _ = decoder.raw_decode(raw, m.start())
                break
            except ValueError:
                continue
    if isinstance(data, dict):
        data = data.get("rules") or data.get("results")
    return data if isinstance(data, list) else None


def verified(
    record, shown_index: int, pages: dict[int, str], scoped: bool
) -> dict | None:
    """One call's record for one rule, or None when its shape is wrong. `ok` says the evidence stands on the page."""
    if (
        not isinstance(record, dict)
        or record.get("i") != shown_index
        or record.get("verdict") not in VERDICTS
    ):
        return None
    verdict = record["verdict"]
    scope = record.get("scope_applies") if scoped else None
    if scoped and scope not in SCOPE_ANSWERS:
        return None
    page, quote = record.get("page"), record.get("quote")
    ok = (
        isinstance(page, int)
        and page in pages
        and isinstance(quote, str)
        and quote_verified(quote, pages[page])
    )
    return {
        "verdict": verdict,
        "scope": scope,
        "page": page if ok else None,
        "quote": quote if ok else None,
        "evidence_ok": ok,
        "reason": " ".join(str(record.get("reason") or "").split())[:300],
    }


def combine(
    first: dict | None, second: dict | None, scoped: bool
) -> tuple[str, str | None, dict | None]:
    """(status, reason, the call whose evidence is shown). Status is Pass / Fail / Query, `not applicable`, or needs engineer."""
    if first is None or second is None:
        return NEEDS_ENGINEER, "a call gave no readable answer", None
    if scoped:
        if first["scope"] != second["scope"] or "unsure" in (
            first["scope"],
            second["scope"],
        ):
            return (
                NEEDS_ENGINEER,
                "the two readings differ or are unsure whether the scope applies",
                None,
            )
        if first["scope"] == "no":
            return (
                "not applicable",
                "scope does not apply to this equipment (both readings)",
                None,
            )
    if first["verdict"] != second["verdict"]:
        return NEEDS_ENGINEER, "the two readings differ", None
    if first["verdict"] == "not_applicable":
        return "not applicable", "not about this datasheet (both readings)", None
    if not (first["evidence_ok"] and second["evidence_ok"]):
        return NEEDS_ENGINEER, "a quote was not found on the cited page", None
    return FINAL[first["verdict"]], None, first


def build_jobs(
    document_id: str, rows: list, labels: dict[str, str], pages: dict[int, str]
):
    jobs, members = [], {}
    for n in range(0, len(rows), PER_PROMPT):
        chunk = rows[n : n + PER_PROMPT]
        docs = frozenset({document_id, *(r["standard_document_id"] for r in chunk)})
        for call, second in (("a", False), ("b", True)):
            order = list(range(len(chunk)))
            if second:
                order.reverse()
            key = f"jdg:{n // PER_PROMPT:05d}:{call}"
            jobs.append(
                rule_box_run.Job(
                    key,
                    prompt_for(chunk, labels, pages, order, second),
                    docs,
                    JUDGE_TOKENS,
                )
            )
            members[key] = (chunk, order, n // PER_PROMPT, call)
    return jobs, members


def make_storer(
    conn, document_id: str, pages: dict[int, str], model: str, members: dict
):
    answers: dict[tuple[int, str], dict[int, dict | None]] = {}
    tally = {
        "rows": 0,
        "Pass": 0,
        "Fail": 0,
        "Query": 0,
        "needs engineer": 0,
        "not applicable": 0,
    }

    def finish(chunk_no: int, chunk: list) -> None:
        calls = answers.get((chunk_no, "a"), {}), answers.get((chunk_no, "b"), {})
        for i, r in enumerate(chunk):
            scoped = r["status"] != rule_box_check.BY_KIND
            first, second = calls[0].get(i), calls[1].get(i)
            status, reason, shown = combine(first, second, scoped)
            tally[status] += 1
            tally["rows"] += 1
            conn.execute(
                f"INSERT OR REPLACE INTO {JUDGED} VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    document_id,
                    r["id"],
                    status,
                    reason,
                    shown["page"] if shown else None,
                    shown["quote"] if shown else None,
                    r["scope_text"] if scoped else None,
                    (first or {}).get("scope"),
                    r["clause"],
                    r["quote"],
                    json.dumps([first, second]),
                    LABEL,
                    model,
                    JUDGE_VERSION,
                    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                ),
            )
        conn.commit()

    def apply(job, text: str) -> bool:
        chunk, order, chunk_no, call = members[job.key]
        records = parse(text)
        by_shown = (
            {x.get("i"): x for x in records if isinstance(x, dict)} if records else {}
        )
        per_rule: dict[int, dict | None] = {}
        for shown, idx in enumerate(order, 1):
            scoped = chunk[idx]["status"] != rule_box_check.BY_KIND
            per_rule[idx] = verified(by_shown.get(shown), shown, pages, scoped)
        answers[(chunk_no, call)] = per_rule
        if (chunk_no, "a") in answers and (chunk_no, "b") in answers:
            finish(chunk_no, chunk)
        return records is not None

    def flush() -> None:
        """A prompt whose call never answered leaves its rules `needs engineer`, never unseen."""
        done = {(c, k) for (c, k) in answers}
        seen = {}
        for _key, (chunk, _order, chunk_no, _call) in members.items():
            seen[chunk_no] = chunk
        for chunk_no, chunk in seen.items():
            if not all((chunk_no, k) in done for k in ("a", "b")) or any(
                r["id"]
                not in {
                    x[1]
                    for x in conn.execute(
                        f"SELECT document_id, rule_id FROM {JUDGED} WHERE document_id = ?",
                        (document_id,),
                    )
                }
                for r in chunk
            ):
                finish(chunk_no, chunk)

    apply.flush = flush
    apply.tally = tally
    return apply


def export_crs(conn, document_id: str, path) -> int:
    """The judged rows as a workbook the answer-key scorer reads (sheet `CRS`). Only Fail, Query, needs engineer and a
    Pass with verified evidence; each row carries the stored clause, the stored rule words and the label."""
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "CRS"
    ws.append(
        [
            "Row",
            "Clause",
            "Page",
            "Result",
            "Requirement (stored words)",
            "Evidence (verified quote)",
            "Comment",
            "Label",
        ]
    )
    n = 0
    for r in conn.execute(
        f"SELECT * FROM {JUDGED} WHERE document_id = ? AND status NOT IN ('not applicable') ORDER BY clause",
        (document_id,),
    ):
        n += 1
        ws.append(
            [
                n,
                r["clause"],
                r["page"],
                r["status"],
                r["rule_quote"],
                r["evidence"],
                r["reason"],
                r["label"],
            ]
        )
    wb.save(path)
    return n
