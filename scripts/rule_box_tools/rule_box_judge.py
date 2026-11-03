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
  * THE DOCUMENT KIND IS TOLD to the model and it must say whether a document of that kind could state the thing at all;
    both calls `no` means `not applicable` (not something this document kind states);
  * the quoted words must touch the rule's subject (at least 2 content words in common, `subject_pairing`'s word rule),
    else `needs engineer`: an adjacent quote is not evidence;
  * near-identical rules (same words, numbers and punctuation aside) are judged ONCE and make ONE row listing every clause;
  * a rule whose text is cut (ends in a colon, a comma or no full stop) is never sent: `needs engineer`, text incomplete;
  * an exported row with no page or no comment is impossible: the export refuses;
  * a verdict row is only ever Fail, Query or needs engineer, or a Pass that carries its verified evidence. Every row says
    `AI judgement, engineer to confirm`.

Standards text and the one approved submittal only. Counts only in a report. Nothing is written to the live database.
"""

from __future__ import annotations

import contextlib
import json
import re
import time

from app import claims, comparison, datasheet_checks, subject_pairing
from app.compiled_rule_proof import quote_verified
from rule_box_tools import rule_box_check, rule_box_labels, rule_box_run

PER_PROMPT = 5
JUDGE_VERSION = "box-judge-v2"
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


#: Closed table of the ways a rule states its comparator (a negated form is read as itself, so "not less than" is never read
#: as "less than"). A rule whose comparator is not exactly one op, once, is not compared.
_COMPARATOR_PHRASES = (
    ("not more than", "<="),
    ("not greater than", "<="),
    ("not higher than", "<="),
    ("not larger than", "<="),
    ("no more than", "<="),
    ("no greater than", "<="),
    ("no higher than", "<="),
    ("not exceeding", "<="),
    ("not to exceed", "<="),
    ("shall not exceed", "<="),
    ("must not exceed", "<="),
    ("not exceed", "<="),
    ("not above", "<="),
    ("not over", "<="),
    ("less than or equal to", "<="),
    ("at most", "<="),
    ("up to", "<="),
    ("maximum", "<="),
    ("max.", "<="),
    ("max", "<="),
    ("≤", "<="),
    ("<=", "<="),
    ("not less than", ">="),
    ("not lower than", ">="),
    ("not smaller than", ">="),
    ("no less than", ">="),
    ("no lower than", ">="),
    ("not below", ">="),
    ("not under", ">="),
    ("greater than or equal to", ">="),
    ("at least", ">="),
    ("minimum", ">="),
    ("min.", ">="),
    ("min", ">="),
    ("≥", ">="),
    (">=", ">="),
    ("less than", "<"),
    ("lower than", "<"),
    ("smaller than", "<"),
    ("below", "<"),
    ("under", "<"),
    ("more than", ">"),
    ("greater than", ">"),
    ("higher than", ">"),
    ("larger than", ">"),
    ("exceeding", ">"),
    ("exceeds", ">"),
    ("exceed", ">"),
    ("above", ">"),
    ("over", ">"),
)
_OP_OF = dict(_COMPARATOR_PHRASES)


def _phrase_rx() -> re.Pattern:
    parts = []
    for phrase, _ in sorted(_COMPARATOR_PHRASES, key=lambda x: -len(x[0])):
        left = r"(?<!\w)" if phrase[0].isalpha() else ""
        right = r"(?!\w)" if phrase[-1].isalpha() else ""
        parts.append(left + re.escape(phrase) + right)
    return re.compile("|".join(parts), re.I)


_PHRASE_RX = _phrase_rx()
_RANGE = re.compile(
    r"\bbetween\b.*\band\b|\d\s*(?:to|through|thru|and|–|—|-|~)\s*\d|\d\s*\.\.\s*\d|~\s*\d",  # noqa: RUF001
    re.I,
)
_PLACEHOLDER_VALUE = re.compile(r"^\W*$")


def normalise_numbers(text: str) -> str:
    """Decimal commas become points ("1,5 MPa" is 1.5 MPa) and thousands commas go ("1,000 kPa"), so the unit-aware reader
    sees the number the document wrote. A comma between digits followed by exactly three digits is a thousands comma."""
    text = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", text)
    return re.sub(r"(?<=\d),(?=\d{1,2}(?!\d))", ".", text)


def read_comparator(rule_text: str) -> str | None:
    """The ONE comparator a rule states, or None when it states none, or two that differ. Longest phrase wins, so a
    negated form is read as itself."""
    found = {_OP_OF[m.group(0).lower()] for m in _PHRASE_RX.finditer(rule_text.lower())}
    return next(iter(found)) if len(found) == 1 else None


_WORDS_OF_OP = {
    "<=": "at most",
    ">=": "at least",
    "<": "below",
    ">": "above",
    "=": "equal to",
}


def figure_check(rule_text: str, quote: str) -> tuple[str, str]:
    """(state, words) for a rule that asks for a figure. `no_figure`: the rule has no digit. `meets` / `violates`: the ONE
    figure the rule asks for was compared with the ONE same-quantity value in the quote by the datasheet comparison itself
    (units converted, gauge and absolute apart), the comparator read by the closed table above. `cannot`: anything else
    (the figure, unit or comparator cannot be read; a range in the rule OR in the quote; more than one value, or none, of
    the same quantity; a unit that does not convert): then no Pass and no Fail can rest on it."""
    if not re.search(r"\d", rule_text):
        return "no_figure", ""
    rule_text, quote = normalise_numbers(rule_text), normalise_numbers(quote)
    if _RANGE.search(rule_text):
        return "cannot", "the rule states a range"
    if _RANGE.search(quote):
        return "cannot", "the quoted words give a range"
    asked = [
        m
        for m in claims.extract_measurements(" ".join(rule_text.split()))
        if claims.unit_dimension(m.raw_unit)
    ]
    if len(asked) != 1:
        return "cannot", "the rule's figure could not be read as one value"
    op = read_comparator(rule_text)
    if op is None:
        return "cannot", "the rule's comparator could not be read"
    limit = asked[0]
    dimension = claims.unit_dimension(limit.raw_unit)
    stated = [
        m
        for m in claims.extract_measurements(" ".join(quote.split()))
        if claims.unit_dimension(m.raw_unit) == dimension
    ]
    if len(stated) != 1:
        return (
            "cannot",
            "the quoted words do not give exactly one value of the same quantity",
        )
    requirement = {
        "requirement_type": "numeric_limit",
        "operator": op,
        "raw_value": limit.raw_value,
        "raw_unit": limit.raw_unit,
        "value": limit.normalized_value,
    }
    fact = {
        "raw_value": stated[0].raw_value,
        "raw_unit": stated[0].raw_unit,
        "value": stated[0].normalized_value,
        "field_name": "judge",
        "page": 1,
        "confirmed_by": "rule_box_judge",
    }
    status = comparison.compare(requirement, fact).get("status")
    words = f"{stated[0].raw_value} {stated[0].raw_unit} against {_WORDS_OF_OP[op]} {limit.raw_value} {limit.raw_unit}"
    if status == comparison.COMPLIANT:
        return "meets", words
    if status == comparison.NON_COMPLIANT:
        return "violates", words
    return "cannot", "the stated value could not be compared with the rule's figure"


_TERM_TAIL = re.compile(
    r"\b(?:shall|must|should|is to|are to)\s+(?:be|have|use|comply with|conform to)\s+(?:made\s+)?(?:(?:of|from|in|with|to|as)\s+)?(.+?)(?:[.;]|$)",
    re.I,
)
_NEGATIVE_RULE = re.compile(
    r"\b(?:shall|must|should)\s+not\b|\bnot\s+be\b|\bnever\b|\bno\b", re.I
)
_ARTICLES = {"a", "an", "the", "of", "any", "one", "following"}


def required_terms(rule_text: str) -> list[str]:
    """What a rule with no figure requires, by code: the words after 'shall be / of / in / with', split into alternatives.
    Empty when the rule is a prohibition or states no such tail."""
    text = " ".join(rule_text.split())
    if _NEGATIVE_RULE.search(text):
        return []
    m = _TERM_TAIL.search(text)
    if not m:
        return []
    out = []
    for part in re.split(r",|/|\bor\b|\band\b", m.group(1), flags=re.I):
        words = [
            w for w in re.findall(r"[A-Za-z0-9\-]+", part) if w.lower() not in _ARTICLES
        ]
        if 0 < len(words) <= 4:
            out.append(" ".join(words).lower())
    return out[:6]


def term_check(rule_text: str, quote: str) -> tuple[str, str]:
    """For a rule WITHOUT a digit: `meets` only when a required term stands, as whole words, in the VALUE of the quote (what
    follows its label), the value is not a placeholder or a negation, and an edition rule is never met (no register).
    Else `cannot`."""
    if re.search(r"\d", rule_text):
        return "no_figure", ""
    if is_edition_rule(rule_text):
        return "cannot", "an edition rule needs the editions register"
    terms = required_terms(rule_text)
    if not terms:
        return "cannot", "the rule's required term could not be read"
    value = quote.split(":", 1)[1] if ":" in quote else quote
    value = " ".join(value.split())
    if _PLACEHOLDER_VALUE.match(value) or _NEGATION.search(value):
        return "cannot", "the quoted value is empty, a placeholder or a negation"
    folded = " ".join(re.findall(r"[a-z0-9\-]+", value.lower()))
    for term in terms:
        if re.search(r"(?<![\w-])" + re.escape(term) + r"(?![\w-])", folded):
            return "meets", term
    return "cannot", "the quoted value does not name a required term"


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
        "figure": figure_check(rule_text, quote)
        if on_page and rule_text
        else ("no_figure", ""),
        "terms": term_check(rule_text, quote)
        if on_page and rule_text
        else ("no_figure", ""),
    }


def combine(
    first: dict | None, second: dict | None, scoped: bool
) -> tuple[str, str | None, dict | None]:
    """(status, reason, the call whose evidence is shown). Status: Pass / Fail / Query, `not applicable`, or needs engineer.
    The reason is INTERNAL wording; the contractor comment never uses it (see `comment_of`)."""
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
    figures = {first["figure"][0], second["figure"][0]}
    terms = {first["terms"][0], second["terms"][0]}
    if first["verdict"] in ("pass", "fail") and "cannot" in figures:
        return (
            "Query",
            "the code could not compare the stated value with the rule's figure",
            first,
        )
    if first["verdict"] == "pass":
        if "silence" in (first["pass_problem"], second["pass_problem"]):
            return (
                "not applicable",
                "the rule says unless stated otherwise and nothing is stated: silence is not compliance",
                None,
            )
        if "violates" in figures:
            return (
                "Query",
                f"the stated value does not meet the rule: {first['figure'][1]}",
                first,
            )
        if "cannot" in terms:
            return (
                "Query",
                "the quoted words do not state what the rule asks for",
                first,
            )
        if first["pass_problem"] or second["pass_problem"]:
            return (
                "Query",
                "the quoted words do not state what the rule asks for",
                first,
            )
        if "meets" not in figures and "meets" not in terms:
            return (
                "Query",
                "the quoted words do not state what the rule asks for",
                first,
            )
    if first["verdict"] == "fail" and "meets" in figures:
        return (
            NEEDS_ENGINEER,
            "the reading says fail but the stated value meets the rule's figure",
            None,
        )
    if len(first["reason"].split()) < 3:
        return NEEDS_ENGINEER, "no reason was given for the verdict", None
    return (
        FINAL[first["verdict"]],
        first["reason"] if first["verdict"] != "pass" else None,
        first,
    )


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
            if status in ("Pass", "Query") and shown:
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
_OPEN = {
    "Fail": "Not acceptable.",
    "Query": "Contractor to confirm.",
    "Pass": "Acceptable.",
}


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
}


def plain_look(row) -> str:
    """One line for the engineer, in plain words: what to look at. No code words."""
    why = PLAIN.get(row["reason"] or "", "The readings did not settle.")
    where = f" (nearest passage: datasheet page {row['page']})" if row["page"] else ""
    return f"{why} Check {row['clause']} against the datasheet{where}."


def _quoted(text, limit: int) -> str:
    words = " ".join(str(text or "").split())
    return words if len(words) <= limit else words[: limit - 1].rstrip() + "…"


def comment_of(row) -> str:
    """A CRS row's wording, BUILT BY CODE ONLY (CRS style guide: what, the reference, the action): a fixed opening, a fixed
    template, the verified datasheet quote and page, the stored clause and the stored rule words. The model's own sentence
    and every internal reason stay out of it; they go to the internal workbook only."""
    status = row["status"]
    calls = [c for c in json.loads(row["calls_json"] or "[]") if c]
    figure = (calls[0].get("figure") if calls else None) or ("no_figure", "")
    shown = f"Datasheet page {row['page']} states “{_quoted(row['evidence'], 240)}”"
    asked = f"{row['clause']} requires “{_quoted(row['rule_quote'], 260)}”"
    if status == "Pass":
        return f"Acceptable. {shown}; this meets {row['clause']}."
    if status == "Fail":
        return f"Not acceptable. {shown}; {asked}. Contractor to revise and resubmit."
    if figure[0] == "violates":
        return f"Not acceptable. {shown}: {figure[1]}; {asked}. Contractor to revise and resubmit."
    return f"Contractor to confirm. {shown}; {asked}. Contractor to confirm that it complies and revise if needed."


class RowRefused(ValueError):
    """A result row with no page or no comment cannot be emitted."""


def export_crs(conn, document_id: str, path, internal_path=None) -> int:
    """TWO workbooks. `path`: the CONTRACTOR copy, one sheet `CRS` with Pass, Fail and Query rows only, no label and no
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
        f"SELECT * FROM {JUDGED} WHERE document_id = ? AND status IN ('Pass','Fail','Query') ORDER BY clause, rule_id",
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
        f"SELECT * FROM {JUDGED} WHERE document_id = ? AND status IN ('Pass','Fail','Query') ORDER BY clause, rule_id",
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
