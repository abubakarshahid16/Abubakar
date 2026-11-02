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
import re
import shutil
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path

from app import deferred_pass, deferred_value

DECIDED = ("COMPLIANT", "NON_COMPLIANT")
DEFERRED = deferred_pass.DEFERRED  # one home with the audit (#1525)


# What a row CLAIMS, so a matcher survives a label change (#1569): `check` is the
# checklist item's id, `value` whether the row carries a value from the sheet
# ("absent"/"present": never the value itself, the truth file holds no document
# text), `page` the page it cites. `section` is the row's label: it can change
# while the claim stays, so the truth file does not use it. `value` tests only
# that the row has evidence text: a quote that defers the value is "present".
MATCH_KEYS = (
    "origin",
    "status",
    "requirement_id",
    "match_method",
    "section",
    "check",
    "value",
    "page",
    "deferred",
)
VALUE_STATES = ("absent", "present")


class ModelCallRefused(RuntimeError):
    """The bench never calls a model; the replay counts every attempt."""


# ----------------------------------------------------------------- matching


def _check_id(finding: dict) -> str | None:
    from app.datasheet_checks import LABEL

    source = finding.get("requirement_source_text") or ""
    found = re.match(rf"{re.escape(LABEL)} (\S+):", source)
    return found.group(1) if found else None


def _matches(finding: dict, matcher: dict) -> bool:
    if not set(matcher) & set(MATCH_KEYS):
        raise ValueError(f"a truth matcher must name at least one of {MATCH_KEYS}")
    # an unknown key used to be ignored, which quietly widened the matcher
    unknown = set(matcher) - set(MATCH_KEYS) - {"why"}
    if unknown:
        raise ValueError(f"a truth matcher has unknown keys: {sorted(unknown)}")
    if "value" in matcher and matcher["value"] not in VALUE_STATES:
        raise ValueError(f"a truth matcher's value must be one of {VALUE_STATES}")
    has_value = (finding.get("contractor_evidence_text") or "").strip()
    for key in MATCH_KEYS:
        if key not in matcher:
            continue
        want = matcher[key]
        got = {
            "status": finding.get("compliance_status"),
            "section": finding.get("contractor_section"),
            "check": _check_id(finding),
            "value": "present" if has_value else "absent",
            "page": finding.get("contractor_page"),
        }.get(key, finding.get(key))
        if (got or "") != want:
            return False
    return True


def _hits(findings: list[dict], matchers: list[dict]) -> list[dict]:
    return [f for f in findings if any(_matches(f, m) for m in matchers)]


_deferred_pass = deferred_pass.is_deferred_pass


def _value_is_deferred(conn: sqlite3.Connection, finding: dict) -> bool:
    """D2, whichever reading the row kept: its wording defers the value, or another
    current reading of the same field on the same page does."""
    if _deferred_pass(finding):
        return True
    rows = conn.execute(
        "SELECT o.value_note FROM submittal_facts f JOIN submittal_facts o"
        " ON o.submittal_document_id = f.submittal_document_id"
        " AND o.field_name = f.field_name AND o.page IS f.page"
        " AND o.equipment_tag IS f.equipment_tag"
        " WHERE f.id = ? AND o.superseded_at IS NULL",
        (finding.get("fact_id"),),
    ).fetchall()
    return any(deferred_value.note_of({"value_note": r[0]}) for r in rows)


def _fold(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().casefold()


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

    checklist = [f for f in findings if f.get("origin") == "datasheet_check"]
    with_req = [f for f in findings if f.get("requirement_id")]
    in_scope = {
        f["requirement_id"]
        for f in with_req
        if f.get("compliance_status") != "NOT_IN_DOCUMENT_SCOPE"
    }
    decided_req = {
        f["requirement_id"] for f in with_req if f.get("compliance_status") in DECIDED
    }

    page_text = {
        r["page_no"]: _fold(r["text"])
        for r in conn.execute(
            "SELECT page_no, text FROM pages WHERE document_id = ?", (doc,)
        )
    }
    quoted = [
        f
        for f in findings
        if (f.get("contractor_evidence_text") or "").strip()
        and f.get("contractor_page")
    ]
    verified = [
        f
        for f in quoted
        if _fold(f["contractor_evidence_text"])
        in page_text.get(f["contractor_page"], "")
    ]

    outcome = json.loads(run["outcome_json"] or "{}")
    if coverage is None:
        coverage = outcome.get("page_coverage") or {}
    split = outcome.get("requirement_split") or {}
    if isinstance(split.get("applies_not_checked"), int):
        # the headline's own boundary: the rules that apply to this submittal
        applies = (split.get("checked") or 0) + split["applies_not_checked"]
    else:
        applies = len(in_scope)
    total = coverage.get("pages_total")
    # #1473: with PAGE_READ_BY_READING_ENABLED the ledger names the pages no
    # reading came back for; without it, the pages no field was read from.
    unread = (
        coverage.get("pages_not_read", coverage.get("pages_not_read_into_fields")) or []
    )

    if kind is None:
        kind = system_kind(conn, doc)

    matchers = case.get("wrong", []) + (
        case.get("wrong_replay", []) if replayed else []
    )
    if any(m.get("deferred") for m in matchers):
        for f in findings:
            f["deferred"] = f.get(
                "compliance_status"
            ) == "COMPLIANT" and _value_is_deferred(conn, f)
    wrong = [
        f for f in _hits(findings, matchers) if f.get("compliance_status") in DECIDED
    ]
    return {
        "run": run_id,
        "document": doc,
        "model": run["model_name"] or (outcome.get("ai_matcher") or {}).get("model"),
        "findings": len(findings),
        "wrong": len(wrong),
        "untrue": len(_hits(findings, case.get("untrue", []))),
        "irrelevant": len(_hits(findings, case.get("irrelevant", []))),
        # D2 (owner): a value marked 'By Contractor'/TBA is a Query, so a Pass
        # on one is not a decision the bench credits; it is shown on its own row.
        "checklist_decided": sum(
            f.get("compliance_status") in DECIDED and not _deferred_pass(f)
            for f in checklist
        ),
        "checklist_total": len(checklist),
        "fails": sum(f.get("compliance_status") == "NON_COMPLIANT" for f in findings),
        "rules_decided": len(decided_req),
        "rules_in_scope": applies,
        "sent_away": sum(
            f.get("compliance_status") == "NOT_IN_DOCUMENT_SCOPE" for f in findings
        ),
        "quotes_verified": len(verified),
        "quotes_unverified": len(quoted) - len(verified),
        "quotes_total": len(quoted),
        "pages_read": None if total is None else total - len(unread),
        "pages_total": total,
        "kind": kind,
        "kind_ok": kind == case.get("kind"),
        "pass_on_deferred": sum(_deferred_pass(f) for f in findings),
    }


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
def _on_copy(db_path: Path):
    """Point the app at a throw-away copy of `db_path` for the block."""
    from app import db
    from app.config import settings

    with tempfile.TemporaryDirectory(prefix="crs-bench-") as tmp:
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
        crs_lines = None
        try:
            main.number_crs_rows(case["run"], scope)
            rows, *_ = main._crs_content(case["run"], scope)
            crs_lines = len(rows)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"crs: {type(exc).__name__}: {exc}"[:200])
        raw = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
        try:
            result = score(
                raw, case["run"], case, coverage=coverage, kind=kind, replayed=True
            )
        finally:
            raw.close()
    result.update(crs_lines=crs_lines, model_calls_refused=refused[0], errors=errors)
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
            return len(rows)
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


BENCH_SWITCHES = ("datasheet_one_value_enabled",)


def fingerprint() -> str:
    """`config.config_version()`, the hash of the answer-affecting settings, plus the
    review switches that hash leaves out and a replay's rows depend on, by name."""
    from app import config

    switches = " ".join(f"{n}={getattr(config.settings, n)}" for n in BENCH_SWITCHES)
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
            entry["stored"]["crs_lines"] = stored_crs_lines(db_path, case["run"])
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
    return "\n".join(lines) + "\n"
