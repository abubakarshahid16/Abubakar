"""#805 rule boxes: the scope gate and the field identity check. Both stand between a typed check and "AI-proven".

The 3 Nov spot-check of the first 39 AI-proven rules found 20 wrong, and the two models shared the misses, so agreement
alone proves nothing. The misses were a scope the check dropped (a material, a service, a sub-type, an exception) and a
field whose quantity is not the rule's quantity. Two general gates, no layout named:

SCOPE GATE (code, no model). A rule may decide on a datasheet field only if NOTHING in its stored scope narrows it beyond
the equipment type the field list belongs to: no condition, no exception, no condition word in its own words, and no
word in `applies_to` beyond the type's own words and plain function words. Else the status is `scoped: judge at review
time`, with the scope text kept, and the rule is never a typed check that decides.

FIELD IDENTITY. The first model names the SUBJECT words of the rule (verified inside its quote), and code compares them
with the field's label by `subject_pairing.quantity_words`, the pairing rule already used for submittals: the two word
sets must be equal. A different, fresh model is then asked one more question per candidate: is the quantity the rule's
subject the field's meaning (same / narrower / different), and is it a requirement on the equipment. Only `same` and
`yes` advance.

ON A COPY. Standards text only. Counts only in a report.
"""

from __future__ import annotations

import re
import time

from app import field_links, rule_typed_check, subject_pairing
from rule_box_tools import rule_box_run

SCOPED = "scoped: judge at review time"
IDENTITY = "rule_box_identity"
IDENTITY_VERSION = "box-identity-v1"
IDENTITY_TOKENS = 200
RELATIONS = ("same", "narrower", "different")
_TRIGGER = re.compile(
    r"\b(unless|except|excluding|only|when|whenever|if|where|provided|other than|apart from|in case)\b",
    re.IGNORECASE,
)
_PLAIN = frozenset(
    [
        "a",
        "an",
        "the",
        "of",
        "and",
        "or",
        "for",
        "to",
        "in",
        "on",
        "at",
        "by",
        "with",
        "without",
        "this",
        "that",
        "these",
        "those",
        "all",
        "any",
        "each",
        "every",
        "purposes",
        "purpose",
        "standard",
        "standards",
        "requirements",
        "requirement",
        "equipment",
        "item",
        "items",
        "system",
        "systems",
        "component",
        "components",
        "shall",
        "followed",
        "apply",
        "applies",
        "is",
        "are",
        "be",
        "as",
    ]
)


def ensure_schema(conn) -> None:
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {IDENTITY} (rule_id TEXT PRIMARY KEY, relation TEXT, requirement TEXT,"
        " model TEXT NOT NULL, prompt_version TEXT NOT NULL, created_at TEXT NOT NULL)"
    )
    conn.commit()


def _stem(word: str) -> str:
    return word[:-1] if word.endswith("s") and len(word) > 3 else word


def _words(text) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z]+", str(text or "").lower())}


def scope_problem(row, equipment_type: str) -> tuple[str, str] | None:
    """(reason, scope text) when the rule is narrowed by anything, else None. Over-cautious by design: a doubt is scoped."""
    condition = " ".join(str(row["condition_text"] or "").split())
    exception = " ".join(str(row["exception_text"] or "").split())
    if condition:
        return "condition", condition
    if exception:
        return "exception", exception
    if rule_typed_check.is_conditional(row["quote"]) or _TRIGGER.search(
        str(row["quote"] or "")
    ):
        return "condition_word_in_the_rule", ""
    extra = (
        _words(row["applies_to"]) - _words(equipment_type) - {_stem(w) for w in _PLAIN}
    )
    if extra:
        return "applies_to_narrows", " ".join(str(row["applies_to"]).split())
    return None


def subject_matches(subject: str, label: str, equipment_type: str) -> bool:
    """The rule's subject and the field's label name the same quantity (`subject_pairing`'s rule: equal word sets)."""
    left = subject_pairing.quantity_words(subject, equipment_type)
    right = subject_pairing.quantity_words(label, equipment_type)
    return bool(left) and left == right


def label_of(role: str) -> str:
    return field_links.canonical(role.replace("_", " "))


# ------------------------------------------------------------------------------------------ identity step
def identity_prompt(row, label: str, role: str, field_label: str) -> str:
    return (
        "You compare ONE requirement of an engineering standard with ONE datasheet field.\n"
        f"THE STANDARD: {label}\nTHE REQUIREMENT (its exact words): {' '.join(str(row['quote']).split())[:1500]}\n"
        f"THE FIELD: {field_label} (name {role}) on a datasheet of a {row['equipment_type']}\n\n"
        "Question 1: is the quantity the requirement limits the SAME quantity the field states, a NARROWER one (the field"
        " is wider, the requirement covers only part of it: a material, a service, a sub-type, a component) or a"
        " DIFFERENT one? Question 2: is it a requirement on the equipment itself (yes), rather than on a procedure,"
        " a document, a person, a test method or a definition (no)?\n"
        'Answer ONLY one JSON object: {"relation": "same" | "narrower" | "different", "requirement_on_the_equipment":'
        ' "yes" | "no"}.'
    )


def identity_todo(conn) -> list:
    return conn.execute(
        "SELECT r.id, r.standard_document_id, r.quote, l.equipment_type, c.field_role, c.model AS check_model"
        " FROM compiled_rules r JOIN rule_box_checks c ON c.rule_id = r.id"
        " JOIN rule_box_second s ON s.rule_id = r.id JOIN rule_box_labels l ON l.rule_id = r.id"
        f" WHERE c.status = 'checked' AND s.agree = 1 AND NOT EXISTS (SELECT 1 FROM {IDENTITY} i WHERE i.rule_id = r.id)"
        " ORDER BY r.id"
    ).fetchall()


def identity_jobs(conn, gate, model: str, labels: dict[str, str]):
    out, members, skipped = [], {}, 0
    for r in identity_todo(conn):
        if r["check_model"] == model:
            skipped += 1
            continue
        if (
            gate(r["standard_document_id"], labels.get(r["standard_document_id"], ""))
            is not None
        ):
            skipped += 1
            continue
        key = f"idn:{r['id']}"
        out.append(
            rule_box_run.Job(
                key,
                identity_prompt(
                    r,
                    labels.get(r["standard_document_id"], ""),
                    r["field_role"],
                    label_of(r["field_role"]),
                ),
                frozenset({r["standard_document_id"]}),
                IDENTITY_TOKENS,
            )
        )
        members[key] = r
    return out, members, {"prompts": len(out), "skipped": skipped}


def identity_storer(conn, members: dict, model: str, parse):
    tally = {"same": 0, "not_same": 0, "not_a_requirement": 0}

    def apply(job, text: str) -> bool:
        data = parse(text)
        row = members[job.key]
        relation = data.get("relation") if isinstance(data, dict) else None
        requirement = (
            data.get("requirement_on_the_equipment") if isinstance(data, dict) else None
        )
        if relation not in RELATIONS or requirement not in ("yes", "no"):
            return False
        conn.execute(
            f"INSERT OR REPLACE INTO {IDENTITY} VALUES (?,?,?,?,?,?)",
            (
                row["id"],
                relation,
                requirement,
                model,
                IDENTITY_VERSION,
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            ),
        )
        conn.commit()
        tally[
            "same" if relation == "same" and requirement == "yes" else "not_same"
        ] += 1
        tally["not_a_requirement"] += requirement == "no"
        return True

    apply.tally = tally
    return apply


def advanced_count(conn) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM rule_box_checks c JOIN rule_box_second s ON s.rule_id = c.rule_id"
        f" JOIN {IDENTITY} i ON i.rule_id = c.rule_id WHERE c.status = 'checked' AND s.agree = 1 AND COALESCE(c.scope_required, 0) = 0"
        " AND i.relation = 'same' AND i.requirement = 'yes'"
    ).fetchone()[0]


def advanced_by_type(conn) -> dict[str, int]:
    return {
        r[0]: r[1]
        for r in conn.execute(
            "SELECT l.equipment_type, COUNT(*) FROM rule_box_checks c JOIN rule_box_second s ON s.rule_id = c.rule_id"
            f" JOIN {IDENTITY} i ON i.rule_id = c.rule_id JOIN rule_box_labels l ON l.rule_id = c.rule_id"
            " WHERE c.status = 'checked' AND s.agree = 1 AND COALESCE(c.scope_required, 0) = 0 AND i.relation = 'same' AND i.requirement = 'yes'"
            " GROUP BY 1 ORDER BY 1"
        )
    }
