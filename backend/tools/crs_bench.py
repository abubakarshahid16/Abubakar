"""The CRS test bench (#1471, plan change 9 C1-1): one table that says whether a
change made the review better or worse, on saved runs, with no model call.

Two columns of numbers per saved run:

  stored   what the run wrote when it ran (the findings in the database copy)
  replay   the CURRENT code re-run over that run's stored reading: the page
           ledger, the document kind, the decide step (`comparison.run_comparison`,
           which includes the datasheet checklist) and the CRS builder - on a
           throw-away copy, with every model and Claude call refused.

A model call the replay needed is refused and counted (`model calls refused`);
the decide step's deterministic part still runs, so a refused call can only
leave a row undecided, never invent a verdict. AI-only steps (the reader, the
AI engineering check, CRS wording) are not replayed; their stored rows are not
in the replay column.

The truth file (eval/bench/truth.json) names the known wrong, untrue and
irrelevant findings by ids, checklist field names and clause ids only - never
document text. The counting rule is printed with every table.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path

from app import coverage_pair, crs_decider, deferred_pass, presence_check, run_measures

DECIDED = run_measures.DECIDED
DEFERRED = deferred_pass.DEFERRED  # one home with the audit (#1525)


MATCH_KEYS = coverage_pair.MATCH_KEYS  # one home: the pair needs the same matching
VALUE_STATES = coverage_pair.VALUE_STATES


class ModelCallRefused(RuntimeError):
    """The bench never calls a model; the replay counts every attempt."""


# ----------------------------------------------------------------- matching


_check_id = coverage_pair._check_id
_matches = coverage_pair.matches
_hits = coverage_pair.hits
_deferred_pass = deferred_pass.is_deferred_pass


_value_is_deferred = coverage_pair.value_is_deferred


_fold = run_measures.fold


# ----------------------------------------------------------------- scoring


def score(
    conn: sqlite3.Connection,
    run_id: str,
    case: dict,
    *,
    coverage: dict | None = None,
    kind: str | None = None,
    replayed: bool = False,
) -> dict:
    """The bench measures for one run from a database connection. `wrong_replay`
    holds the current code only: a saved run keeps the rows it wrote."""
    conn.row_factory = sqlite3.Row
    run = conn.execute("SELECT * FROM review_runs WHERE id = ?", (run_id,)).fetchone()
    if run is None:
        raise LookupError(f"no review run {run_id} in this database")
    doc = run["submittal_document_id"]
    findings = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM review_findings WHERE review_run_id = ?", (run_id,)
        )
    ]

    outcome = json.loads(run["outcome_json"] or "{}")
    if kind is None:
        kind = system_kind(conn, doc)
    measures = run_measures.headline(
        conn, doc, outcome, findings, case, coverage=coverage, replayed=replayed
    )
    return {
        "run": run_id,
        "document": doc,
        "model": run["model_name"] or (outcome.get("ai_matcher") or {}).get("model"),
        "findings": len(findings),
        **measures,
        "kind": effective_kind(conn, doc, kind),
        "kind_ok": effective_kind(conn, doc, kind) == case.get("kind"),
        # Informational, below the headline: one count per place a decision or
        # an engineer row is made, never added together (`finding_sources`).
        "sources": finding_sources(conn, findings),
        # The pair, one definition with the board and the CRS (`coverage_pair`).
        # Printed below the headline; the gate does not read it. `--save` writes
        # this dict and git tracks saved baselines: the public view only.
        "pair": coverage_pair.public_view(
            coverage_pair.for_run(conn, run_id, case=case, replayed=replayed)
        ),
    }


# ----------------------------------------------------------------- sources
#
# The headline counts decisions from review_findings only, and "standard rules
# decided" only those with a requirement_id. Decisions and engineer rows are
# made in more places than that; each is counted here ON ITS OWN ROW, labelled
# by where it is made, and no two sources are ever added into one number.
# An engineer row is not a decision; a Pass on a deferred value (D2) is not
# credited (`_deferred_pass`).

SRC_RULE = "decided - review findings (rule, code)"
SRC_CHECKLIST = (
    "decided - datasheet checklist (clause as text, not linked to a stored rule)"
)
SRC_PLAYBOOK = (
    "playbook rows - present / missing / unclear (engineer rows, not decisions)"
)
SRC_TICK = "safety tick rows - engineer to tick"
SRC_STATED = "stated, not checked - checklist rows that only ask a field is stated"
_NO_FINDING = "CRS rows with no finding - "
#: DECISION: a source whose rows may decide. ENGINEER: rows that are engineer
#: rows by construction (kit_core.held, spec_kit._store, transmittal_kit), so a
#: verdict on one is wrong whatever the truth file says.
DECISION, ENGINEER = "decision", "engineer"
#: The draft lanes (`crs_mapping._DRAFT_LANES`) and the engineer's chat comments:
#: engineer rows, shown with any verdict they carry, not gated (an engineer's
#: own action on one is not the code's verdict).
DRAFT = "draft"
DRAFT_ORIGINS = coverage_pair.DRAFT_ORIGINS
#: A COMPLIANT finding shown for an engineer's tick (`show_for_engineer_tick`):
#: crs_mapping prints it as a `safety_tick` row the engineer must tick, so it is
#: an engineer row, not a decision the bench credits.
TICK = "tick"

SOURCE_RULE = [
    "Rows below the headline (informational; one source per row, never added"
    " together; each count is of THIS run's rows from that source only):",
    f"'{SRC_RULE}': findings linked to a stored rule (requirement_id in"
    " standard_requirements) decided COMPLIANT or NON_COMPLIANT, of those"
    " findings; a Pass on a deferred value (D2) is not credited.",
    f"'{SRC_CHECKLIST}': datasheet_check findings that are not kit cards, decided,"
    " of those findings; D2 not credited.",
    "'decided - findings from <origin> (no stored rule linked)': every other"
    " finding source, decided of its rows; D2 not credited.",
    "'engineer rows - <origin> (drafts, not decisions)': the AI engineering"
    " check, the web standards check, the clause review and chat comments;"
    " 'draft rows with a code verdict' counts those carrying COMPLIANT or"
    " NON_COMPLIANT that no engineer confirmed (shown, not gated).",
    f"'{SRC_STATED}': with the switch on (#1638), not decisions: no value was compared.",
    f"'{SRC_TICK}': COMPLIANT findings shown for an engineer's tick (a"
    " safety_tick CRS row). Not credited as decided anywhere below the headline.",
    "'kit rows - <kit> (engineer rows)': rows a kit made (pump, vessel, exchanger"
    " draft cards on the checklist; the specification, parked-kind and"
    " transmittal kits). Never decisions: a kit row carrying a verdict is shown"
    " and turns the gate red.",
    f"'{SRC_PLAYBOOK}': rows the review playbooks add at CRS build, by state"
    " (other states: could not be checked, standard not held). Never decisions.",
    f"'{_NO_FINDING}<row kind> (engineer rows, not decisions)': other rows the"
    " CRS builder adds with no finding behind them (missing reference, standard"
    " not cited, pages not readable, carried forward, ...).",
    "A CRS-build count is blank when the CRS could not be built, and every new"
    " row is blank for a result saved before it existed (never 0).",
]


def _stored_rule_ids(conn: sqlite3.Connection) -> set[str]:
    try:
        return {r[0] for r in conn.execute("SELECT id FROM standard_requirements")}
    except sqlite3.OperationalError:  # a copy without the table: nothing links
        return set()


def _kits() -> list[tuple[str, str]]:
    from app import kit_core

    return [(k.name, k.words) for k in kit_core._kits()]


def finding_source(f: dict, rule_ids: set[str], kits) -> tuple[str, str]:
    """(row label, its type) for one stored finding: where it was made."""
    from app import spec_kit

    origin = f.get("origin")
    if origin == "datasheet_check":
        text = f"{f.get('requirement') or ''} {f.get('requirement_source_text') or ''}"
        for name, words in kits:
            if words and words in text:
                return f"kit rows - {name} (engineer rows)", ENGINEER
    if presence_check.is_stated_only(
        f
    ):  # before the tick row: one count with `coverage_pair`
        return SRC_STATED, TICK
    if (
        origin not in DRAFT_ORIGINS
        and origin != spec_kit.ORIGIN
        and f.get("show_for_engineer_tick")
        and f.get("compliance_status") == "COMPLIANT"
    ):
        # crs_mapping makes it a safety_tick row the engineer must tick: not decided
        return SRC_TICK, TICK
    if origin == "datasheet_check":
        return SRC_CHECKLIST, DECISION
    if origin == spec_kit.ORIGIN:
        code = str(f.get("reason_code") or f.get("ai_rationale") or "")
        parts = str(f.get("requirement_id") or "").split(":")
        if code.startswith(spec_kit.TRANSMITTAL):
            name = "transmittal"
        elif len(parts) >= 3 and parts[1]:
            name = parts[1]
        else:
            name = "specification"
        return f"kit rows - {name} (engineer rows)", ENGINEER
    if origin in DRAFT_ORIGINS:
        return f"engineer rows - {origin} (drafts, not decisions)", DRAFT
    if f.get("requirement_id") and f["requirement_id"] in rule_ids:
        return SRC_RULE, DECISION
    where = origin or "the comparison"
    return f"decided - findings from {where} (no stored rule linked)", DECISION


def finding_sources(conn: sqlite3.Connection, findings: list[dict]) -> dict:
    """label -> {"type", "rows", "decided", "verdicts"} for the run's findings."""
    rule_ids, kits = _stored_rule_ids(conn), _kits()
    out: dict[str, dict] = {}
    for f in findings:
        label, kind = finding_source(f, rule_ids, kits)
        slot = out.setdefault(
            label, {"type": kind, "rows": 0, "decided": 0, "verdicts": 0}
        )
        slot["rows"] += 1
        if f.get("compliance_status") in DECIDED:
            # a draft an engineer confirmed may rightly carry a status: not the code's
            if kind != DRAFT or not crs_decider.decider(f):
                slot["verdicts"] += 1
            if not _deferred_pass(f):
                slot["decided"] += 1
    return out


def crs_sources(rows: list[dict] | None) -> dict | None:
    """label -> counts for the CRS rows the builder adds with NO finding behind
    them (a finding's row is counted under its finding's source). None when the
    CRS could not be built."""
    if rows is None:
        return None
    out: dict[str, dict] = {}
    for row in rows:
        if row.get("finding_id") or row.get("finding_ids"):
            continue
        kind = row.get("row_kind") or "unlabelled"
        if kind == "playbook_check":
            slot = out.setdefault(
                SRC_PLAYBOOK,
                {"type": "playbook", "present": 0, "missing": 0, "unclear": 0},
            )
            slot.setdefault("other", 0)
            state = row.get("playbook_state")
            slot[state if state in ("present", "missing", "unclear") else "other"] += 1
            continue
        label = f"{_NO_FINDING}{kind} (engineer rows, not decisions)"
        out.setdefault(label, {"type": "crs", "rows": 0})["rows"] += 1
    return out


def _source_order(label: str) -> tuple:
    if label == SRC_RULE:
        rank = 0
    elif label == SRC_CHECKLIST:
        rank = 1
    elif label.startswith("decided -"):
        rank = 2
    elif label.startswith("engineer rows") or label in (SRC_TICK, SRC_STATED):
        rank = 3
    elif label.startswith("kit rows"):
        rank = 4
    elif label == SRC_PLAYBOOK:
        rank = 5
    else:
        rank = 6
    return rank, label


def _source_cell(m: dict, label: str) -> str:
    if "sources" not in m:  # a result saved before these rows: not measured
        return ""
    at_crs = label == SRC_PLAYBOOK or label.startswith(_NO_FINDING)
    table = m.get("crs_sources") if at_crs else m["sources"]
    if table is None:  # the CRS could not be built: blank, never 0
        return ""
    slot = table.get(label)
    if slot is None:  # measured, and this source made no row in this run
        if label == SRC_PLAYBOOK:
            return "0 / 0 / 0"
        return "0/0" if label.startswith("decided -") else "0"
    if slot["type"] == DECISION:
        return _frac(slot["decided"], slot["rows"])
    if slot["type"] == ENGINEER:
        bad = slot["verdicts"]
        return str(slot["rows"]) + (
            f" ({bad} with a verdict - must be 0)" if bad else ""
        )
    if slot["type"] == DRAFT:
        bad = slot["verdicts"]
        return str(slot["rows"]) + (
            f" ({bad} draft rows with a code verdict)" if bad else ""
        )
    if slot["type"] == "playbook":
        text = f"{slot['present']} / {slot['missing']} / {slot['unclear']}"
        return text + (f"; other states {slot['other']}" if slot["other"] else "")
    return str(slot["rows"])


def source_rows(cols: list[tuple[str, dict]]) -> list[tuple[str, list[str]]]:
    """The rows below the headline: every source any column saw, one row each."""
    labels = {SRC_RULE, SRC_CHECKLIST}
    for _, m in cols:
        labels |= set(m.get("sources") or {})
        labels |= set(m.get("crs_sources") or {})
    return [
        (label, [_source_cell(m, label) for _, m in cols])
        for label in sorted(labels, key=_source_order)
    ]


def system_kind(conn: sqlite3.Connection, doc: str) -> str:
    """The kind the review routes on: the document's ONE stored kind (the
    router's table `document_kinds`, which #1474's decider also writes), else
    the equipment-type choice of today (any equipment type = datasheet)."""
    try:
        stored = conn.execute(
            "SELECT kind FROM document_kinds WHERE document_id = ?", (doc,)
        ).fetchone()
    except sqlite3.OperationalError:  # a copy from before the router
        stored = None
    if stored is not None and stored["kind"]:
        return stored["kind"]
    row = conn.execute(
        "SELECT equipment_type FROM document_classification WHERE document_id = ?",
        (doc,),
    ).fetchone()
    if row is None:
        return "unclassified"
    return "datasheet" if row["equipment_type"] else "unclassified"


def effective_kind(conn: sqlite3.Connection, doc: str, kind: str) -> str:
    """The kind the review acts on, not only the one stored. A stored procedure or
    specification that does not take the procedure path is reviewed on the equipment
    rules, so it counts as a datasheet here."""
    from app import procedure_text
    from app.config import settings

    if kind not in procedure_text.PROCEDURE_KINDS:
        return kind
    try:
        routed = procedure_text.document_kind(doc, conn=conn)
    except sqlite3.OperationalError:  # a copy from before the router
        routed = None
    taken = settings.procedure_path_enabled and routed in procedure_text.PROCEDURE_KINDS
    return kind if taken else "datasheet"


# ----------------------------------------------------------------- replay


@contextmanager
def _models_refused(counter: list[int], installed: tuple[str, ...] = ()):
    """Every outbound model path raises; the attempt is counted.

    The engine's model LIST is answered from `installed` (the models the run
    itself recorded), so the code takes the same path it took in the run -
    a model is there - and then gets no answer from it. Refusing the list
    as well would send the replay down "no model installed" paths the run
    never took."""
    from app import model_transport, reader_transport

    def refuse(*_a, **_k):
        counter[0] += 1
        raise ModelCallRefused("the bench makes no model call")

    def probe(path, *_a, **_k):
        if path.endswith("/api/tags"):
            return {"models": [{"name": m, "model": m} for m in installed]}
        if path.endswith("/api/ps"):
            return {"models": []}
        if path.endswith("/api/version"):
            return {"version": "crs-bench"}
        return refuse()

    saved = [(model_transport, "get_json", model_transport.get_json)]
    model_transport.get_json = probe
    blocked = (
        (model_transport, ("post_json", "post_json_retrying", "stream_json")),
        (reader_transport, ("stream", "_gated", "batch_create", "list_models")),
    )
    import smtplib
    import socket

    import httpx  # the net under the gates: no request leaves, whatever imported it

    blocked += (
        (httpx.Client, ("send",)),
        (httpx.AsyncClient, ("send",)),
        (smtplib.SMTP, ("connect",)),
        (socket.socket, ("connect", "connect_ex")),
        (socket, ("create_connection",)),
    )
    for mod, names in blocked:
        for name in names:
            if hasattr(mod, name):
                saved.append((mod, name, getattr(mod, name)))
                setattr(mod, name, refuse)
    try:
        yield
    finally:
        for mod, name, fn in saved:
            setattr(mod, name, fn)


@contextmanager
def _on_copy(db_path: Path, under: Path | None = None):
    """Point the app at a throw-away copy of `db_path` for the block (in `under`
    when given, else the OS temp folder)."""
    from app import db
    from app.config import settings

    with tempfile.TemporaryDirectory(prefix="crs-bench-", dir=under) as tmp:
        target = Path(tmp) / "bench.sqlite"
        for suffix in ("", "-wal", "-shm"):
            src = Path(str(db_path) + suffix)
            if src.exists():
                shutil.copy2(src, str(target) + suffix)
        old = (settings.db_path, settings.data_dir)
        settings.db_path, settings.data_dir = target, Path(tmp)
        db.reset_connection()
        try:
            yield target
        finally:
            db.reset_connection()
            settings.db_path, settings.data_dir = old


def replay(db_path: Path, case: dict) -> dict:
    """Re-run the current code's ledger, kind, decide and CRS steps for one run."""
    from contextlib import ExitStack

    from app import access, comparison, db, main, page_ledger

    refused = [0]
    errors: list[str] = []
    with _on_copy(db_path) as copy, ExitStack() as stack:
        conn = db.connect()
        run = conn.execute(
            "SELECT * FROM review_runs WHERE id = ?", (case["run"],)
        ).fetchone()
        if run is None:
            raise LookupError(f"no review run {case['run']} in this database")
        doc = run["submittal_document_id"]
        outcome = json.loads(run["outcome_json"] or "{}")
        stack.enter_context(_models_refused(refused, run_models(outcome)))
        ids = frozenset(r["id"] for r in conn.execute("SELECT id FROM documents"))
        scope = access.AccessScope(user_id="crs-bench", allowed_document_ids=ids)

        page_ledger.refresh(doc, as_submittal=True)
        coverage = page_ledger.coverage(doc)
        kind = _replay_kind(doc, errors)
        try:
            comparison.run_comparison(
                case["run"],
                allowed_document_ids=ids,
                replace=True,
                reference_coverage=(outcome.get("completeness") or {}).get(
                    "reference_coverage"
                ),
                missing_references=[
                    m["identifier"]
                    for m in outcome.get("missing_references") or []
                    if isinstance(m, dict) and m.get("identifier")
                ],
            )
        except Exception as exc:  # noqa: BLE001 - reported on the table, not hidden
            errors.append(f"decide: {type(exc).__name__}: {exc}"[:200])
        crs_lines = crs_rows = None
        try:
            main.number_crs_rows(case["run"], scope)
            crs_rows, *_ = main._crs_content(case["run"], scope)
            crs_lines = len(crs_rows)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"crs: {type(exc).__name__}: {exc}"[:200])
        raw = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
        try:
            result = score(
                raw, case["run"], case, coverage=coverage, kind=kind, replayed=True
            )
        finally:
            raw.close()
    result.update(
        crs_lines=crs_lines,
        crs_sources=crs_sources(crs_rows),
        model_calls_refused=refused[0],
        errors=errors,
    )
    return result


def run_models(outcome: dict) -> tuple[str, ...]:
    """The local models the run's own record names (engine prefix removed)."""
    value = (outcome.get("ai_matcher") or {}).get("model")
    if not isinstance(value, str) or not value:
        return ()
    return (value.removeprefix("ollama:"),)


def _replay_kind(doc: str, errors: list[str]) -> str:
    """The kind the CURRENT classification code gives the document."""
    from app import classification, db

    conn = db.connect()
    try:
        fn = getattr(classification, "classify_document_kind", None)
        if fn is not None:
            fn(doc)
        else:  # the equipment-type choice the review routes on today
            classification.classify_equipment_type_for_submittal(doc)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"kind: {type(exc).__name__}: {exc}"[:200])
    return system_kind(conn, doc)


def stored_crs_lines(db_path: Path, run_id: str) -> int | None:
    """CRS lines as the CRS builder makes them from the run's stored findings."""
    rows = stored_crs_rows(db_path, run_id)
    return None if rows is None else len(rows)


def stored_crs_rows(db_path: Path, run_id: str) -> list[dict] | None:
    """The CRS rows the builder makes from the run's stored findings, composed
    as the export composes them (`main._crs_content`), on a copy, no model call."""
    from app import access, db, main

    try:
        with _on_copy(db_path), _models_refused([0]):
            ids = frozenset(
                r["id"] for r in db.connect().execute("SELECT id FROM documents")
            )
            rows, *_ = main._crs_content(
                run_id,
                access.AccessScope(user_id="crs-bench", allowed_document_ids=ids),
            )
            return rows
    except Exception:  # noqa: BLE001 - shown as blank, never as 0
        return None


# ----------------------------------------------------------------- settings


def use_settings_of(env_file: Path) -> None:
    """Load the answer-affecting switches from `env_file` into the running
    settings, in process only (nothing is printed). A git worktree has no
    backend/.env (git-ignored), so without this a replay there runs on the
    defaults and is not comparable with one run from the main checkout."""
    from app.config import Settings, settings

    fresh = Settings(_env_file=env_file)
    for name in type(settings).model_fields:
        setattr(settings, name, getattr(fresh, name))


BENCH_SWITCHES = ("datasheet_one_value_enabled", "owner_approved_rules_decide_enabled")


def fingerprint() -> str:
    """`config.config_version()`, the hash of the answer-affecting settings, plus the
    review switches that hash leaves out and a replay's rows depend on, by name."""
    from app import config

    switches = " ".join(f"{n}={getattr(config.settings, n)}" for n in BENCH_SWITCHES)
    # #1638: named only when on, so a baseline saved before the switch stays comparable
    if config.settings.presence_not_pass_enabled:
        switches += " presence_not_pass_enabled=True"
    return f"{config.config_version()} {switches}"


# ----------------------------------------------------------------- the table


def _frac(n, d) -> str:
    if d in (None, 0) or n is None:
        return "" if d is None else f"{n}/0"
    return f"{n}/{d}"


def run_bench(db_path: Path, truth: dict, *, do_replay: bool = True) -> list[dict]:
    from app import live_guard

    if live_guard.is_live_shaped(db_path):
        raise PermissionError("the bench never opens the live database; pass a copy")
    out = []
    raw = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        for case in truth["cases"]:
            entry = {
                "case": case,
                "config": fingerprint(),
                "stored": score(raw, case["run"], case),
            }
            crs_rows = stored_crs_rows(db_path, case["run"])
            entry["stored"]["crs_lines"] = None if crs_rows is None else len(crs_rows)
            entry["stored"]["crs_sources"] = crs_sources(crs_rows)
            if do_replay:
                entry["replay"] = replay(db_path, case)
            out.append(entry)
    finally:
        raw.close()
    return out


ROWS = [
    ("wrong verdicts (hard stop > 0)", lambda m: str(m["wrong"])),
    ("untrue lines", lambda m: str(m["untrue"])),
    ("irrelevant lines", lambda m: str(m["irrelevant"])),
    (
        "checklist decided",
        lambda m: _frac(m["checklist_decided"], m["checklist_total"]),
    ),
    (
        "standard rules decided",
        lambda m: _frac(m["rules_decided"], m["rules_in_scope"]),
    ),
    ("Fail rows", lambda m: str(m["fails"])),
    ("sent to 'needs another document'", lambda m: str(m["sent_away"])),
    ("verified-quote rate", lambda m: _frac(m["quotes_verified"], m["quotes_total"])),
    ("pages read", lambda m: _frac(m["pages_read"], m["pages_total"])),
    (
        "kind recognised",
        lambda m: ("yes" if m["kind_ok"] else "NO") + f" ({m['kind']})",
    ),
    ("Pass on 'By Contractor'/TBA (D2)", lambda m: str(m["pass_on_deferred"])),
    ("CRS lines", lambda m: "" if m.get("crs_lines") is None else str(m["crs_lines"])),
]


PAIR_COVERAGE = "coverage: standard rules decided of those that apply (one definition)"
PAIR_RISK = "risk: wrong among standard rules decided (one definition)"
PAIR_OUTCOMES = "standard rules pass / fail / unknown (one definition)"
PAIR_CHECKLIST = "checklist decided, stated apart, not added to the rules"
PAIR_BY_TYPE = "Risk and coverage per equipment type"
PAIR_BY_REASON = "Risk and coverage per gate reason"
OTHER_REASONS = coverage_pair.OTHER_REASONS
PAIR_RULE = [
    "Risk and coverage, one definition (`app/coverage_pair.py`, the same function the"
    " board call and the CRS use). Applicable: the rules the run states apply to its"
    " document (requirement_split: reached the comparison + applies but not checked),"
    " each rule once; does-not-apply and checklist-covered rules are out. Decided: code"
    " said pass or fail; a Pass on a deferred value (D2) is unknown. Risk: wrong among"
    " decided rules, 'not measured' where the truth set names no known-wrong row for the"
    " run, never 0; a truth hit on a D2 Pass stays on the headline's hard stop, not here."
    " The checklist is stated apart and never added; a wrong checklist verdict is printed"
    " on its row. The gate does not read these rows. A saved result holds no document id"
    " and no free-text gate reason here.",
    "The clause coverage line a run stores counts stored rows, not rules, and adds the"
    " rules a checklist covers, so its 'applicable' is larger on the same run.",
]


def _pair_cell(m: dict, fn) -> str:
    pair = m.get("pair")
    return "" if pair is None else fn(pair)


PAIR_ROWS = [
    (
        PAIR_COVERAGE,
        lambda p: (
            ""
            if not coverage_pair.coverage_text(p)
            else _frac(p["decided"], p["applicable"])
        ),
    ),
    (
        PAIR_RISK,
        lambda p: (
            _frac(p["risk"]["wrong"], p["risk"]["decided"])
            + (
                f" ({p['wrong_verdicts']['all']} wrong in all)"
                if p["wrong_verdicts"]["all"] != p["risk"]["wrong"]
                else ""
            )
            if p["risk"]["measured"]
            else coverage_pair.NOT_MEASURED
        ),
    ),
    (
        PAIR_OUTCOMES,
        lambda p: (
            f"{p['pass']} / {p['fail']} / "
            + ("" if p["unknown"] is None else str(p["unknown"]))
        ),
    ),
    (
        PAIR_CHECKLIST,
        lambda p: (
            _frac(p["checklist"]["decided"], p["checklist"]["rows"])
            + (
                f" ({p['checklist']['stated']} stated, not checked,"
                f" {p['checklist'].get('stated_deferred', 0)} of them on a deferred value)"
                if p["checklist"].get("stated")
                else ""
            )
            + (f" ({p['checklist']['wrong']} wrong)" if p["checklist"]["wrong"] else "")
        ),
    ),
]


def save_results(path: Path, results: list[dict]) -> None:
    """`--save`: the results as a file git may track, in a public repo. The table needs
    the equipment type (`by_equipment_type`); a saved baseline does not: the gate never
    reads it, so a classification of the document stays out of the file."""
    saved = []
    for result in results:
        entry = dict(result)
        for column in ("stored", "replay"):
            pair = (entry.get(column) or {}).get("pair")
            if pair is not None:
                kept = {k: v for k, v in pair.items() if k != "equipment_type"}
                entry[column] = {**entry[column], "pair": kept}
        saved.append(entry)
    path.write_text(json.dumps(saved, indent=1, default=str))


def _reason_cell(row: dict) -> str:
    """One gate reason's cell. Decisions that do not fit the count the run states are
    not printed against it (`coverage_pair._gate_rows`): only that count is."""
    count = (
        row["applicable"]
        if row["decided"] is None
        else f"{row['decided']}/{row['applicable']}"
    )
    wrong = f" ({row['wrong']} wrong)" if row["wrong"] is not None else ""
    return f"{row['reason']}: {count}{wrong}"


def pair_tables(cols: list[tuple[str, dict]]) -> list[str]:
    """The breakdowns: per equipment type (one column's runs each) and per gate reason."""
    lines: list[str] = []
    stored = [
        m["pair"] for name, m in cols if m.get("pair") and name.endswith("stored")
    ]
    if stored:
        lines += [
            "",
            f"{PAIR_BY_TYPE} (stored runs; each type adds only its runs):",
            "",
        ]
        for name, s in sorted(coverage_pair.by_equipment_type(stored).items()):
            risk = s["risk"]
            cov = (
                "" if s["applicable"] is None else _frac(s["decided"], s["applicable"])
            )
            said = (
                f"{risk['wrong']}/{risk['decided']} on {risk['measured_runs']} of"
                f" {s['runs']} run(s) with a truth set; {s['wrong_verdicts']} wrong in all"
                if risk["measured_runs"]
                else coverage_pair.NOT_MEASURED
            )
            lines.append(f"- {name}: coverage {cov}; risk {said}")
    rows = [(name, m["pair"]) for name, m in cols if m.get("pair")]
    if rows:
        lines += [
            "",
            f"{PAIR_BY_REASON} (each adds up to its column's applicable):",
            "",
        ]
        for name, pair in rows:
            cells = "; ".join(_reason_cell(r) for r in pair["by_gate_reason"])
            lines.append(f"- {name}: {cells or 'the run states no rules that apply'}")
    return lines


def gate(results: list[dict], baseline: list[dict] | None = None) -> list[str]:
    """Why the bench is red, or [] when green: any wrong verdict (stored or
    replay), or any measure worse than the saved baseline for the same run. A
    measure that had a value and is now blank is worse (null is never 0)."""
    reasons = []
    base = {b["case"]["run"]: b for b in (baseline or [])}
    for r in results:
        name = r["case"]["name"]
        for column in ("stored", "replay"):
            if r.get(column) and r[column]["wrong"]:
                reasons.append(
                    f"{name}: {r[column]['wrong']} wrong verdict(s) ({column})"
                )
            # An engineer-row source (a kit) never decides; a verdict on one is red.
            for label, slot in ((r.get(column) or {}).get("sources") or {}).items():
                if slot.get("type") == ENGINEER and slot.get("verdicts"):
                    reasons.append(
                        f"{name}: {slot['verdicts']} verdict(s) on {label} ({column})"
                    )
        b = base.get(r["case"]["run"])
        if not b:
            continue
        if b.get("config") and r.get("config") and b["config"] != r["config"]:
            reasons.append(
                f"{name}: settings differ from the baseline's"
                f" ({b['config']} vs {r['config']}); not comparable"
            )
            continue
        column = "replay" if r.get("replay") and b.get("replay") else "stored"
        now, then = r[column], b[column]
        for key in HIGHER_IS_WORSE:
            if then.get(key) is not None and now.get(key) is None:
                reasons.append(f"{name}: {key} {then[key]} -> blank")
            elif then.get(key) is not None and now[key] > then[key]:
                reasons.append(f"{name}: {key} {then[key]} -> {now[key]}")
        for key in LOWER_IS_WORSE:
            if then.get(key) is not None and now.get(key) is None:
                reasons.append(f"{name}: {key} {then[key]} -> blank")
            elif then.get(key) is not None and now[key] < then[key]:
                reasons.append(f"{name}: {key} {then[key]} -> {now[key]}")
        # A reader that breaks can make every quote vanish: fewer unfound quotes,
        # nothing red. Quoted findings halving while the findings do not is red.
        tq, nq = then.get("quotes_total"), now.get("quotes_total")
        tf, nf = then.get("findings") or 0, now.get("findings") or 0
        if tq and nq is not None and nq * 2 < tq and nf * 2 >= tf:
            reasons.append(
                f"{name}: quoted findings {tq} -> {nq} while findings {tf} -> {nf}"
            )
        if then["kind_ok"] and not now["kind_ok"]:
            reasons.append(f"{name}: kind was right, now {now['kind']}")
    return reasons


# Quotes are gated on the ones NOT found on their page: removing a row that
# should never have existed is not a loss, but one more unfound quote is.
HIGHER_IS_WORSE = (
    "untrue",
    "irrelevant",
    "pass_on_deferred",
    "sent_away",
    "quotes_unverified",
)
LOWER_IS_WORSE = ("checklist_decided", "rules_decided", "pages_read")


def render_markdown(
    results: list[dict], truth: dict, *, title: str, baseline: list[dict] | None = None
) -> str:
    cols = []
    for r in results:
        cols.append((r["case"]["name"] + " stored", r["stored"]))
        if "replay" in r:
            cols.append((r["case"]["name"] + " replay", r["replay"]))
    lines = [f"# {title}", ""]
    lines.append("| measure | " + " | ".join(c[0] for c in cols) + " |")
    lines.append("|---|" + "---|" * len(cols))
    for label, fn in ROWS:
        lines.append(f"| {label} | " + " | ".join(fn(m) for _, m in cols) + " |")
    for label, cells in source_rows(cols):
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    for label, fn in PAIR_ROWS:
        cells = [_pair_cell(m, fn) for _, m in cols]
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    lines += pair_tables(cols)
    configs = sorted({r["config"] for r in results if r.get("config")})
    lines += [
        "",
        "Settings: as loaded, nothing forced off (" + ", ".join(configs) + ")",
    ]
    lines += ["", "Runs (model from the run record; blank = not recorded):", ""]
    for r in results:
        s = r["stored"]
        rp = r.get("replay") or {}
        lines.append(
            f"- {r['case']['name']}: run {s['run'][:8]}, document {s['document']},"
            f" model {s['model'] or '(not recorded)'}"
            + (
                f"; replay refused {rp.get('model_calls_refused')} model call(s)"
                if rp
                else ""
            )
            + (
                f"; replay errors: {'; '.join(rp['errors'])}"
                if rp.get("errors")
                else ""
            )
        )
    reasons = gate(results, baseline)
    lines += [
        "",
        "Gate: " + ("GREEN" if not reasons else "RED - " + "; ".join(reasons)),
        "",
        "Counting rule:",
        "",
    ]
    lines += [f"- {c}" for c in truth.get("counting_rule", [])]
    lines += [f"- {c}" for c in PAIR_RULE]
    lines += [f"- {c}" for c in SOURCE_RULE]
    return "\n".join(lines) + "\n"
