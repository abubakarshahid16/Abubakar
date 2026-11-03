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
  * a Query needs a verified quote; else `needs engineer`. THE JUDGE NEVER CREATES A PASS OR A FAIL (a Pass is the job of the
    separately reviewed Pass gate, #1682): where it would have, it records needs engineer with the verified quotes;
  * the two calls must give the same verdict and the same scope answer, else `needs engineer` with both shown;
  * a scoped rule whose scope is `unsure` or differs is `needs engineer`; `no` (both calls) means it does not apply and
    no row is made;
  * THE DOCUMENT KIND IS TOLD to the model and it must say whether a document of that kind could state the thing at all;
    both calls `no` means `not applicable` (not something this document kind states);
  * the quoted words must touch the rule's subject (at least 2 content words in common, `subject_pairing`'s word rule),
    else `needs engineer`: an adjacent quote is not evidence;
  * near-identical rules (same words, numbers and punctuation aside) are judged ONCE and make ONE row listing every clause;
  * a rule whose text is cut (ends in a colon, a comma or no full stop) is never sent: `needs engineer`, text incomplete;
  * an exported row with no page or no comment is impossible: the export refuses;
  * a contractor-facing row is only ever a Query with its verified quote. Every row says
    `AI judgement, engineer to confirm`.

Standards text and the one approved submittal only. Counts only in a report. Nothing is written to the live database.
"""

from __future__ import annotations

import contextlib
import json
import re
import time

from app import datasheet_checks, subject_pairing
from app.compiled_rule_proof import quote_verified
from rule_box_tools import rule_box_check, rule_box_labels, rule_box_run

PER_PROMPT = 5
JUDGE_VERSION = "box-judge-v2"
JUDGED = "rule_box_judgements"
LABEL = "AI judgement, engineer to confirm"
VERDICTS = ("pass", "fail", "query", "not_applicable")
SCOPE_ANSWERS = ("yes", "no", "unsure")
NEEDS_ENGINEER = "needs engineer"
FINAL = {"query": "Query"}  # no Pass and no Fail: see combine()
JUDGE_TOKENS = 1500
QUOTE_CHARS = 900


def ensure_schema(conn) -> None:
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {JUDGED} (document_id TEXT NOT NULL, rule_id TEXT NOT NULL, status TEXT NOT NULL,"
        " reason TEXT, page INTEGER, evidence TEXT, scope_text TEXT, scope_applies TEXT, clause TEXT, rule_quote TEXT,"
        " calls_json TEXT, label TEXT NOT NULL, model TEXT NOT NULL, prompt_version TEXT NOT NULL, created_at TEXT NOT NULL,"
        " standard TEXT, PRIMARY KEY (document_id, rule_id))"
    )
    with contextlib.suppress(Exception):  # an older copy of the table
        conn.execute(f"ALTER TABLE {JUDGED} ADD COLUMN standard TEXT")
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


def normal_text(text) -> str:
    """The rule's words with numbers, clause marks and punctuation taken out: what makes two rules the same rule."""
    return " ".join(re.sub(r"[^a-z ]+", " ", str(text or "").lower()).split())[:400]


def is_incomplete(text) -> bool:
    """A rule cut off: it ends in a colon or a comma, or does not end in a full stop (or like)."""
    t = str(text or "").strip()
    return not t or t[-1] in ":," or t[-1] not in '.;?!)\u201d"'


_EDITION = re.compile(
    r"\blatest\b.{0,40}\b(edition|issue|revision|version)\b|\b(edition|issue|revision)\b.{0,40}\blatest\b",
    re.I,
)


def is_edition_rule(text) -> bool:
    """A rule that asks for the latest edition: judged only with an editions register, never from a datasheet alone."""
    return bool(_EDITION.search(str(text or "")))


def prepare(rows: list) -> tuple[list[dict], list, list[tuple]]:
    """(units, unsent rows, merged). A unit is one rule asked once: `rep` and every row `members` of the same words.
    Unsent rows are cut-off rules and edition rules: they make no call."""
    units: dict[tuple, dict] = {}
    incomplete, merged = [], []
    for r in rows:
        if is_incomplete(r["quote"]) or is_edition_rule(r["quote"]):
            incomplete.append(r)
            continue
        key = (
            normal_text(r["quote"]),
            r["status"] != rule_box_check.BY_KIND,
            normal_text(r["scope_text"]),
        )
        if key in units:
            units[key]["members"].append(r)
            merged.append((units[key]["rep"], r))
        else:
            units[key] = {"rep": r, "members": [r]}
    return list(units.values()), incomplete, merged


def standard_name(label: str) -> str:
    """The standard as an engineer writes it: the stored label without a file extension."""
    return re.sub(
        r"\.(pdf|docx?|xlsx?)$", "", str(label or "").strip(), flags=re.I
    ).strip()


def clause_label(row, labels: dict[str, str]) -> str:
    return f"{standard_name(labels.get(row['standard_document_id'], ''))} clause {row['clause']}".strip()


def clauses_of(unit: dict, labels: dict[str, str]) -> str:
    seen, out = set(), []
    for m in unit["members"]:
        text = clause_label(m, labels)
        if text not in seen:
            seen.add(text)
            out.append(text)
    return "; ".join(out)


def prompt_for(
    units: list[dict],
    label_of_standard: dict[str, str],
    pages: dict[int, str],
    order: list[int],
    second: bool,
    kind: str = "datasheet",
) -> str:
    text = "\n\n".join(f"=== PAGE {n} ===\n{t}" for n, t in pages.items())
    parts = []
    for shown, idx in enumerate(order, 1):
        r = units[idx]["rep"]
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
        "This is an independent second reading: judge each rule afresh from the document alone.\n"
        if second
        else ""
    )
    return (
        f"You review ONE submitted {kind} against requirements of engineering standards, as a careful senior engineer.\n"
        f"{again}"
        "For each numbered requirement answer: document_can_state = yes or no: is this requirement about this "
        f"{kind} at all, so that a {kind} could state or show it? (site duties, delivery media, BIM, databases, process"
        " and who does what are not). If no, give a reason of at most five words and the other fields do not matter."
        " verdict = pass (the document"
        " meets it), fail (it breaks it), query (the document is unclear, silent or contradictory on something it should"
        " state) or not_applicable (not about this document). Give the page number and the EXACT words copied from that"
        " page that support the verdict (needed for pass, fail and query); the words must be about the same thing the"
        " requirement limits. A requirement that says 'unless stated otherwise' is not breached by silence. If a"
        " requirement has a SCOPE, say scope_applies = yes, no or unsure: does that scope describe this equipment?"
        " Never guess: when unsure say query / unsure.\n\n"
        "REQUIREMENTS:\n" + "\n".join(parts) + f"\n\nTHE {kind.upper()}:\n{text}\n\n"
        'Answer ONLY a JSON array, one object per requirement in order: [{"i": 1, "document_can_state": "yes" | "no",'
        ' "verdict": "...", "scope_applies": "yes" | "no" | "unsure" | null, "page": <number or null>, "quote": "<exact'
        ' words>" | null, "reason": "<one short sentence>"}].'
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


def touches(quote: str, rule_text: str) -> bool:
    """The quote shares at least two content words with the rule (one, if the rule has only one): not an adjacent line."""
    rule_words = subject_pairing.quantity_words(rule_text)
    shared = rule_words & subject_pairing.quantity_words(quote)
    return len(shared) >= min(2, len(rule_words)) and bool(shared)


_NEGATION = re.compile(
    r"\b(no|not|never|none|nil|blank|tba|tbc|tbd|n/a|na|n\.a\.?|without|absent|missing|excluded|exclude|excluding|except|"
    r"omitted|others|cannot|can't|unavailable|by others|to be provided|to be advised|to be confirmed|vendor to|"
    r"supplier to|contractor to|by vendor|by supplier)\b|\(\s*to be|^\W*$",
    re.I,
)
_LANGUAGES = ("english", "arabic", "french", "german", "spanish", "chinese")


def pass_problem(rule_text: str, quote: str) -> str | None:
    """Why this quote cannot make a Pass, or None. A Pass needs an AFFIRMATIVE statement carrying the value the rule asks
    for: a figure or an edition number when the rule has one, a language when the rule names one. Silence, a blank, a
    negation, or a rule that says 'unless stated otherwise' is never a Pass."""
    if re.search(r"\bunless\b", rule_text, re.I):
        return "silence"
    if _NEGATION.search(quote):
        return "not_affirmative"
    if re.search(r"\d", rule_text) and not re.search(r"\d", quote):
        return "no_value"
    for lang in _LANGUAGES:
        if lang in rule_text.lower() and lang not in quote.lower():
            return "no_value"
    return None


def clean_reason(text, rule_text: str, words: int = 8) -> str:
    """The model's short reason, cut to a few words; dropped when it brings a number the rule does not have."""
    said = " ".join(str(text or "").split())
    if set(_NUMBER.findall(said)) - set(_NUMBER.findall(rule_text)):
        return ""
    return " ".join(said.split()[:words]).rstrip(".")


def verified(
    record, shown_index: int, pages: dict[int, str], scoped: bool, rule_text: str = ""
) -> dict | None:
    """One call's record for one rule, or None when its shape is wrong. `evidence_ok`: the quote stands on the cited page
    AND touches the rule's subject."""
    if (
        not isinstance(record, dict)
        or record.get("i") != shown_index
        or record.get("verdict") not in VERDICTS
        or record.get("document_can_state") not in ("yes", "no")
    ):
        return None
    scope = record.get("scope_applies") if scoped else None
    if scoped and scope not in SCOPE_ANSWERS:
        return None
    page, quote = record.get("page"), record.get("quote")
    on_page = (
        isinstance(page, int)
        and page in pages
        and isinstance(quote, str)
        and quote_verified(quote, pages[page])
    )
    near = on_page and (not rule_text or touches(quote, rule_text))
    return {
        "verdict": record["verdict"],
        "can_state": record["document_can_state"],
        "scope": scope,
        "page": page if on_page else None,
        "quote": quote if on_page else None,
        "evidence_ok": bool(near),
        "on_page": bool(on_page),
        "reason": " ".join(str(record.get("reason") or "").split())[:300],
        "short_reason": clean_reason(record.get("reason"), rule_text),
        "pass_problem": pass_problem(rule_text, quote)
        if on_page and rule_text
        else None,
    }


def combine(
    first: dict | None, second: dict | None, scoped: bool
) -> tuple[str, str | None, dict | None]:
    """(status, reason, the call whose evidence is shown). Status: Query, `not applicable`, or needs engineer. THERE IS NO
    PASS AND NO FAIL here: a Pass is created only by the separately reviewed Pass gate (#1682), never by the judge. Where
    the judge would have said Pass it records needs engineer, "the quotes suggest the rule is met", with the verified
    quotes for the internal sheet. A Query states the value against the limit only when the datasheet comparison itself
    says the rule is violated. The reason is INTERNAL wording; the contractor comment never uses it."""
    if first is None or second is None:
        return NEEDS_ENGINEER, "a call gave no readable answer", None
    if first["can_state"] != second["can_state"]:
        return (
            NEEDS_ENGINEER,
            "the two readings differ on whether this document kind can state it",
            None,
        )
    if first["can_state"] == "no":
        return (
            "not applicable",
            first["short_reason"]
            or second["short_reason"]
            or "not something this document kind states",
            None,
        )
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
        return (
            "not applicable",
            first["short_reason"] or "not about this document",
            None,
        )
    if not (first["evidence_ok"] and second["evidence_ok"]):
        if first["on_page"] and second["on_page"]:
            return (
                NEEDS_ENGINEER,
                "the quoted words do not touch the rule's subject",
                None,
            )
        return NEEDS_ENGINEER, "a quote was not found on the cited page", None
    verdict = first["verdict"]
    if verdict == "pass":
        if "silence" in (first["pass_problem"], second["pass_problem"]):
            return (
                "not applicable",
                "the rule says unless stated otherwise and nothing is stated: silence is not compliance",
                None,
            )
        return NEEDS_ENGINEER, "the quotes suggest the rule is met", first
    if verdict == "fail":
        return NEEDS_ENGINEER, "the reading says the rule is broken", first
    if _NEGATION.search(first["quote"] or "") or _NEGATION.search(
        second["quote"] or ""
    ):
        return (
            NEEDS_ENGINEER,
            "the quoted words are a negation or a placeholder, not a stated value",
            first,
        )
    if len(first["reason"].split()) < 3:
        return NEEDS_ENGINEER, "no reason was given for the verdict", None
    return "Query", first["reason"], first


def build_jobs(
    document_id: str,
    units: list[dict],
    labels: dict[str, str],
    pages: dict[int, str],
    kind: str = "datasheet",
):
    jobs, members = [], {}
    for n in range(0, len(units), PER_PROMPT):
        chunk = units[n : n + PER_PROMPT]
        docs = frozenset(
            {document_id, *(u["rep"]["standard_document_id"] for u in chunk)}
        )
        for call, second in (("a", False), ("b", True)):
            order = list(range(len(chunk)))
            if second:
                order.reverse()
            key = f"jdg:{n // PER_PROMPT:05d}:{call}"
            jobs.append(
                rule_box_run.Job(
                    key,
                    prompt_for(chunk, labels, pages, order, second, kind),
                    docs,
                    JUDGE_TOKENS,
                )
            )
            members[key] = (chunk, order, n // PER_PROMPT, call)
    return jobs, members


def _write(
    conn,
    document_id,
    rule,
    status,
    reason,
    shown,
    first,
    second,
    clauses,
    standard,
    model,
) -> None:
    scoped = rule["status"] != rule_box_check.BY_KIND
    conn.execute(
        f"INSERT OR REPLACE INTO {JUDGED} (document_id, rule_id, status, reason, page, evidence, scope_text, scope_applies,"
        " clause, rule_quote, calls_json, label, model, prompt_version, created_at, standard)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            document_id,
            rule["id"],
            status,
            reason,
            shown["page"] if shown else None,
            shown["quote"] if shown else None,
            rule["scope_text"] if scoped else None,
            (first or {}).get("scope"),
            clauses,
            rule["quote"],
            json.dumps([first, second]),
            LABEL,
            model,
            JUDGE_VERSION,
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            standard,
        ),
    )


def settle_unsent(conn, document_id: str, incomplete: list, labels, model) -> None:
    """Rules never sent: edition rules (no register: not applicable) and rules whose text is cut off (needs engineer)."""
    for r in incomplete:
        if not is_incomplete(r["quote"]) and is_edition_rule(r["quote"]):
            status, why = (
                "not applicable",
                "edition rule: no editions register is loaded, so nothing to compare",
            )
        else:
            status, why = NEEDS_ENGINEER, "rule text incomplete"
        _write(
            conn,
            document_id,
            r,
            status,
            why,
            None,
            None,
            None,
            clause_label(r, labels),
            labels.get(r["standard_document_id"], ""),
            model,
        )
    conn.commit()


def make_storer(
    conn,
    document_id: str,
    pages: dict[int, str],
    model: str,
    members: dict,
    labels: dict | None = None,
):
    labels = labels or {}
    answers: dict[tuple[int, str], dict[int, dict | None]] = {}
    used_quotes: set = set()
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
        for i, unit in enumerate(chunk):
            rep = unit["rep"]
            scoped = rep["status"] != rule_box_check.BY_KIND
            first, second = calls[0].get(i), calls[1].get(i)
            status, reason, shown = combine(first, second, scoped)
            if status == "Query" and shown:
                spot = (shown["page"], normal_text(shown["quote"]))
                if spot in used_quotes:
                    status, reason, shown = (
                        NEEDS_ENGINEER,
                        "the same quote is already used for another rule",
                        None,
                    )
                else:
                    used_quotes.add(spot)
            if (
                status == NEEDS_ENGINEER and shown is None
            ):  # the nearest passage either reading found, for the engineer
                shown = next((c for c in (first, second) if c and c.get("page")), None)
            clauses = clauses_of(unit, labels)
            standard = labels.get(rep["standard_document_id"], "")
            for member in unit["members"]:
                tally[status] += 1
                tally["rows"] += 1
                _write(
                    conn,
                    document_id,
                    member,
                    status if member is rep else "merged",
                    reason if member is rep else f"same rule as {rep['clause']}",
                    shown,
                    first,
                    second,
                    clauses,
                    standard,
                    model,
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
            rep = chunk[idx]["rep"]
            scoped = rep["status"] != rule_box_check.BY_KIND
            per_rule[idx] = verified(
                by_shown.get(shown), shown, pages, scoped, rep["quote"]
            )
        answers[(chunk_no, call)] = per_rule
        if (chunk_no, "a") in answers and (chunk_no, "b") in answers:
            finish(chunk_no, chunk)
        return records is not None

    def flush() -> None:
        """A prompt whose call never answered leaves its rules `needs engineer`, never unseen."""
        written = {
            r[0]
            for r in conn.execute(
                f"SELECT rule_id FROM {JUDGED} WHERE document_id = ?", (document_id,)
            )
        }
        seen = {chunk_no: chunk for (chunk, _o, chunk_no, _c) in members.values()}
        for chunk_no, chunk in seen.items():
            if any(m["id"] not in written for u in chunk for m in u["members"]):
                finish(chunk_no, chunk)

    apply.flush = flush
    apply.tally = tally
    return apply


# ------------------------------------------------------------------------------------------ the CRS rows
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
PLAIN = {
    "the two readings differ": "Two independent readings of this rule disagreed.",
    "the two readings differ on whether this document kind can state it": "Two independent readings disagreed on whether this kind of document can show this at all.",
    "rule text incomplete": "The stored text of this rule is cut off, so it was not judged.",
    "the quoted words do not touch the rule's subject": "The passage found on the datasheet does not clearly concern this rule.",
    "a quote was not found on the cited page": "A passage the reading relied on could not be found on its page.",
    "a call gave no readable answer": "An answer could not be read.",
    "the two readings differ or are unsure whether the scope applies": "It is unclear whether this rule's scope applies to this equipment.",
    "no reason was given for the verdict": "The reading gave no reason for its verdict.",
    "the same quote is already used for another rule": "The only passage found was already used for another rule.",
    "the quotes suggest the rule is met": "The datasheet passage suggests this rule is met; not proven by code, so check it yourself.",
    "the reading says the rule is broken": "The readings suggest this rule is broken; not proven by code, so check it yourself.",
    "the quoted words are a negation or a placeholder, not a stated value": "The passage found is a placeholder or a negation, not a stated value; check it yourself.",
}


def plain_look(row) -> str:
    """One line for the engineer, in plain words: what to look at. No code words."""
    why = PLAIN.get(row["reason"] or "", "The readings did not settle.")
    where = f" (nearest passage: datasheet page {row['page']})" if row["page"] else ""
    found = (
        f" Passage: \u201c{' '.join(str(row['evidence']).split())[:240]}\u201d."
        if row["evidence"]
        else ""
    )
    return f"{why} Check {row['clause']} against the datasheet{where}.{found}"


def _quoted(text, limit: int) -> str:
    words = " ".join(str(text or "").split())
    return words if len(words) <= limit else words[: limit - 1].rstrip() + "…"


def comment_of(row) -> str:
    """A contractor CRS row's wording, BUILT BY CODE ONLY and NEUTRAL: it quotes what the datasheet states and what the
    rule requires, and asks the contractor to confirm. It never says that a value meets, exceeds, violates or lies below a
    limit: no direction is computed. The model's sentence and the internal reasons stay in the internal workbook."""
    return (
        f"The datasheet states \u201c{_quoted(row['evidence'], 240)}\u201d on page {row['page']}. "
        f"{row['clause']} requires \u201c{_quoted(row['rule_quote'], 260)}\u201d. "
        "Contractor to confirm that the stated value complies and revise if not."
    )


class RowRefused(ValueError):
    """A result row with no page or no comment cannot be emitted."""


def export_crs(conn, document_id: str, path, internal_path=None) -> int:
    """TWO workbooks. `path`: the CONTRACTOR copy, one sheet `CRS` with Query rows only, no label and no
    word about AI or the engineer; a row with no page or no comment is refused. `internal_path` (default beside it, with
    `-internal` in its name): `AI judgement not decided`, the needs-engineer rows with one plain line each, and the label.
    Merged and not-applicable rules make no row. Returns the number of CRS rows."""
    from pathlib import Path

    import openpyxl

    path = Path(path)
    internal_path = (
        Path(internal_path)
        if internal_path
        else path.with_name(path.stem + "-internal.xlsx")
    )
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "CRS"
    ws.append(
        ["Row", "Clause", "Page", "Result", "Comment", "Requirement (stored words)"]
    )
    n = 0
    for r in conn.execute(
        f"SELECT * FROM {JUDGED} WHERE document_id = ? AND status = 'Query' ORDER BY clause, rule_id",
        (document_id,),
    ):
        comment = comment_of(r)
        if not comment or not (r["page"] and r["evidence"]) or not r["clause"]:
            raise RowRefused(
                f"rule {r['rule_id']}: a {r['status']} row needs a clause, a page and a comment"
            )
        n += 1
        ws.append([n, r["clause"], r["page"], r["status"], comment, r["rule_quote"]])
    wb.save(path)
    inner = openpyxl.Workbook()
    sheet = inner.active
    sheet.title = "AI judgement not decided"
    sheet.append(
        [
            "Row",
            "Clause",
            "Nearest page",
            "What the engineer should look at",
            "Requirement (stored words)",
            "Label",
        ]
    )
    for k, r in enumerate(
        conn.execute(
            f"SELECT * FROM {JUDGED} WHERE document_id = ? AND status = ? ORDER BY clause, rule_id",
            (document_id, NEEDS_ENGINEER),
        ),
        1,
    ):
        sheet.append(
            [
                k,
                r["clause"],
                r["page"],
                plain_look(r),
                r["rule_quote"],
                "Internal: " + r["label"],
            ]
        )
    notes = inner.create_sheet("AI notes")
    notes.append(
        [
            "Clause",
            "Result",
            "Page",
            "The reading's own sentence (internal)",
            "Internal reason",
        ]
    )
    for r in conn.execute(
        f"SELECT * FROM {JUDGED} WHERE document_id = ? AND status = 'Query' ORDER BY clause, rule_id",
        (document_id,),
    ):
        calls = [c for c in json.loads(r["calls_json"] or "[]") if c]
        notes.append(
            [
                r["clause"],
                r["status"],
                r["page"],
                (calls[0].get("reason") if calls else "") or "",
                r["reason"] or "",
            ]
        )
    inner.save(internal_path)
    return n
