"""The test session's settings come from the code, never from the machine.

WHAT WAS WRONG. `conftest.py` had a session fixture called
`_the_suite_does_not_read_the_developers_env` whose docstring promised the
suite did not depend on `backend/.env`. It pinned ONE field, `auth_mode`.
Everything else in that file still reached the suite. On the owner's laptop
`backend/.env` holds `REASONING_PROVIDER=claude`, both `STANDARDS_READER_*`
egress flags and a real Anthropic key, so running the suite:

  - sent REAL, PAID requests to the Anthropic API (test_reports.py; one came
    back a real 400), with test fixture text in them;
  - read, and wrote, the REAL spend ledger and response cache under
    `backend/data/` (`claude_spend_log`, `claude_cache_dir` were never
    redirected), so test calls counted against the owner's USD 20 cap;
  - failed 83 tests that pass everywhere else.

The same name/claim mismatch the honesty audit keeps recording: a guard named
for the whole promise, implementing one line of it.

THE FIX IS NOT A LONGER LIST OF PINS. A list of pins is correct on the day it
is written and wrong the day somebody adds a setting. Instead, `isolate()`:

  1. stops the `Settings` class reading ANY env file (`env_file=None`), so a
     test that builds a fresh `Settings()` is also blind to `backend/.env`;
  2. removes from `os.environ` every variable that names a `Settings` field,
     plus the few the application reads from `os.environ` directly
     (`ANTHROPIC_API_KEY`, `STANDARDS_READER_*`, `RAG_LIVE_WRITER`);
  3. builds a fresh `Settings()` from that empty environment - which is the
     code's defaults - and copies EVERY field onto the live singleton.

`conftest.py` calls it at import time, before any test module imports the
application, so nothing is ever computed from the developer's values.

`EGRESS_SAFE` then states, field by field, what "safe" means for everything
that can open a socket, spend money, hold a secret, or read/write outside the
test's temp dirs, and `unsafe_fields()` checks the live settings against it.
`test_env_isolation.py` proves the list is COMPLETE (every field whose name
looks like a switch, key, host, URL, provider or path must be classified), so
a new egress flag added to config.py fails the suite until someone decides
what it is.

The network guard is defence in depth, not the control: the control is the
settings above. If a code path finds a way to a non-loopback address anyway,
the guard refuses the connection and the test that tried is failed by name.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from pathlib import Path

from app.config import BACKEND_DIR, Settings

#: Variables the application reads straight from `os.environ`, bypassing
#: `Settings` (reader_api._sources, reasoning_provider.claude_unavailable,
#: claude_budget.max_calls_per_run, live_guard). Prefixes end in "_".
DIRECT_ENV_NAMES = ("ANTHROPIC_API_KEY", "RAG_LIVE_WRITER")
DIRECT_ENV_PREFIXES = ("STANDARDS_READER_",)

class OneOf(tuple):
    """An EGRESS_SAFE entry with more than one safe value."""


#: The TestClient sends `Host: testserver`. Trusted in TEST configuration only
#: (here), never by a production default - see `config.trusted_host_names`.
TEST_ALLOWED_HOSTS = "testserver"

#: Fields whose PRODUCTION default is on but which a test session must not
#: run: `isolate()` sets these after copying the code's defaults. Only for a
#: switch the owner turned on by default; EGRESS_SAFE still checks the value.
TEST_PINS: dict[str, object] = {
    # On by default since #736 (owner decision 2026-10-10); in tests it would
    # be a model call per standard per review.
    "applicability_reasoning_enabled": False,
    # On by default since the owner order of 2026-10-11 ("AI reads every
    # datasheet box"); in tests it would be two model calls per page.
    "datasheet_ai_reader": "off",
    # On by default since the owner order of 2026-10-11 (item 4); in tests it
    # would be two model calls per unmatched requirement.
    "match_enabled": False,
    "pairing_subject_gate_enabled": False,  # owner order 3 Nov: off unless its own tests turn it on
    # #806 S3 is ON in production. The suite's Claude-lane tests run fake
    # transports over invented documents that are on no approved list; the
    # guard has its own tests (`test_806_claude_approved.py`), which turn it on.
    "claude_approved_list_enforced": False,
    # On by default since #763 R26 step 7 (owner rule "AI-first", 11 Oct);
    # in tests it would be a model call per review.
    "review_ai_check_enabled": False,
    # On by default since #763 R26 step 8 (owner rule "AI-first", 11 Oct);
    # in tests it would be a model call per CRS row per review.
    "crs_ai_wording_enabled": False,
    # On by default since #645 (owner rule "AI-first", 11 Oct); in tests it
    # would be a model call per undecided clause sentence per review.
    "ai_clause_checks_enabled": False,
    # On by default since #141 (owner rule "AI-first"); in tests it would be a
    # model call per division of a standard per review.
    "ai_division_scope_enabled": False,
    # #882 technique 2, on by default under `match_enabled`; in tests it would
    # be two model calls per requirement left without a value.
    "match_ask_max_per_run": 0,
}

#: Lock 3 (#1626): on by default. The suite stays on the off path these tests were written for
#: (126 of them assumed it); a switch's own tests turn it on. The nightly job
#: `.github/workflows/nightly-default-switches.yml` sets LIFT_ENV to run the code's real defaults.
LOCK3_PINNED: tuple[str, ...] = (
    "clause_review_enabled",
    "data_page_not_frontmatter_enabled",
    "datasheet_label_join_enabled",
    "datasheet_one_value_enabled",
    "deferred_value_is_query_enabled",
    "document_kind_enabled",
    "kind_chooses_rules_enabled",
    "nothing_read_fails_enabled",
    "page_read_by_reading_enabled",
    "playbook_presence_without_standard_enabled",
    "playbook_section_presence_enabled",
    "procedure_crs_fields_enabled",
    "procedure_path_enabled",
    "procedure_playbook_rows_enabled",
    "review_audit_report_enabled",
    "review_progress_bar_enabled",
    "transmittal_kit_enabled",
)
TEST_PINS.update(dict.fromkeys(LOCK3_PINNED, False))
LIFT_ENV = "RAG_TEST_LIFT_LOCK3_PINS"

#: The only values these fields may hold when a test session starts. A test
#: that needs one of them on sets it itself, with a fake transport - that is
#: the established pattern (monkeypatch.setattr / setenv, undone per test).
EGRESS_SAFE: dict[str, object] = {
    # --- the Claude lane (reader_transport): money and document text leave
    "reasoning_provider": "ollama",
    "standards_reader_enabled": False,
    "standards_reader_allow_public_egress": False,
    "anthropic_api_key": "",
    # Order 270.3: where the review reads the converter's draft files; empty = reads none.
    "standards_converter_dir": "",
    # #806 S3: the approved-document guard is off for the suite only (its
    # fakes carry invented documents); with no key and the egress flags off
    # above, nothing can leave either way.
    "claude_approved_list_enforced": False,
    "review_ai_check_enabled": False,
    "geometry_reader_enabled": False,  # also gates the Claude vision reader
    "field_naming_enabled": False,  # order 259.5: model-named fields in a review
    "vision_reader_engine": "ollama",  # #830: "claude" sends page images out under per_task
    "answer_judge_enabled": False,  # a model call per answer
    "applicability_reasoning_enabled": False,  # a model call per standard per review
    "crs_ai_wording_enabled": False,  # a model call per CRS row per review
    # --- the market lane (market_transport)
    "market_live_enabled": False,
    "market_allow_public_egress": False,
    "market_search_api_key": "",
    "market_search_provider": "",
    "market_search_endpoint": "",
    "market_openalex_contact_email": "",
    "market_allowed_hosts": ("api.openalex.org", "en.wikipedia.org"),
    "chat_web_enabled": False,
    "review_web_standards_enabled": False,
    # --- the model lane (model_transport): loopback Ollama only
    "ollama_url": "http://127.0.0.1:11434",
    "answer_model_allow_remote_host": False,
    "answer_model_allowed_hosts": (),
    "match_enabled": False,
    "match_ask_max_per_run": 0,  # #882: two local-model calls per question
    # the datasheet AI reader (`datasheet_ai`): local Ollama by default, or
    # Claude through reader_transport - two model calls per page
    "datasheet_ai_reader": "off",
    "match_engine": "ollama",  # "claude" sends clause text out
    "review_ai_check_engine": "ollama",  # #501: "claude" sends datasheet pages out
    "ai_clause_review_engine": "ollama",  # "claude" sends requirement text and small passages out
    "crs_ai_wording_engine": "ollama",  # #819: "claude" sends CRS rows (standard references) out
    # #645: one local model call per undecided clause sentence - off, like
    # the applicability tier; its own tests switch it on with a fake model.
    "ai_clause_checks_enabled": False,
    "ai_requirement_extraction_enabled": False,
    "ai_requirement_quote_page_enabled": False,
    "ai_requirement_extraction_resume_enabled": False,
    # #141: a local model call per division of a standard a review holds.
    "ai_division_scope_enabled": False,
    # Order 210 FIX 2: a code-only rule (skips a model call), draft, off.
    "scope_type_words_rule_enabled": False,
    # Order 205: a cache that only SKIPS a local model call; on is the code
    # default and the safe value (the suite stubs the model identity, so
    # nothing is reused until a test asks for it).
    "ai_answer_reuse_enabled": True,
    # --- notifications (SMTP)
    "smtp_enabled": False,
    "smtp_host": "",
    "smtp_username": "",
    "smtp_password": "",
    "smtp_from": "",
    "smtp_recipient": "",
    "smtp_port": 587,  # inert while smtp_enabled is off
    "smtp_starttls": True,
    "smtp_ssl": False,
    "smtp_timeout_seconds": 10.0,
    "summary_schedule": "disabled",
    # --- secrets and identity
    "auth_mode": "disabled",
    "auth_secret": "",
    "crs_company_name": "",
    # --- the process binds loopback only
    "host": "127.0.0.1",
    "allow_unauthenticated_network_bind": False,
    # Inbound, not egress, but it names hosts so it is classified here. The
    # code default is "" and `isolate()` sets the TestClient's name; both are
    # safe, and nothing else is.
    "allowed_hosts": OneOf(("", TEST_ALLOWED_HOSTS)),
    "api_docs_enabled": False,
    # --- reads outside the test's own dirs
    "watch_folder": "",
    "watch_owner_email": "",
    "applicability_taxonomy_path": None,
    # --- local only; listed so the completeness check has seen it
    "geometry_table_reader_enabled": True,
    # --- local only, no model or socket: records a text cell of a standards table with no value (off by default)
    "table_text_cells_enabled": False,
    # --- local only: reads an uploaded Word file with the standard library
    "docx_input_enabled": True,
    # --- local only, no model or socket: one intake layer for every file type (off by default)
    "one_intake_enabled": False,
    # --- local only, no model or socket: images and workbooks accepted through intake (off by default)
    "intake_images_xlsx_enabled": False,
    # --- local only, no model or socket: numbered blocks and hashes for every file (off by default)
    "intake_blocks_enabled": False,
    # --- local only, no model or socket: rule_trust's opt-in hook (off by default)
    "tested_cards_decide_enabled": False,
    "rule_auto_use_enabled": False,
    # --- local only, no model or socket: a recommendation is raised as a query (order 288.2, off by default)
    "recommendation_queries_enabled": False,
    # --- local only, no model or socket: a value marked By Contractor / TBA is a query, never a verdict (#1475, D2, off by default)
    "deferred_value_is_query_enabled": False,
    # --- local only, no model or socket: document kind from the title block (#1474, off by default)
    "document_kind_enabled": False,
    # --- local only, no model or socket: a page is read when a reading came back (#1473, off by default)
    "page_read_by_reading_enabled": False,
    # --- local only, no model or socket: a procedure is checked against its own text (#1476, off by default)
    "procedure_path_enabled": False,
    # --- Claude through reader_transport only, on a database copy, a script's switch (#1584, off by default)
    "standards_compiler_enabled": False,
    # --- local model only, no socket but model_transport (#1477, off by default)
    "clause_review_enabled": False,
    # --- local model only, no socket but model_transport: whole-document clause review (off by default)
    "clause_review_whole_document_enabled": False,
    # --- read-only display of the jobs row, no model or socket (#1494, off by default)
    "review_progress_bar_enabled": False,
    # --- local files only, no model or socket: a per-review audit report (#1525, off by default)
    "review_audit_report_enabled": False,
    "review_audit_dir": "",  # empty = the default audit folder outside the repo (#1525)
    # --- local only, no model or socket: a review that read nothing fails (#1495, off by default)
    "nothing_read_fails_enabled": False,
    # --- local only, no model or socket: a specification is checked against a must-contain list (#1479, off by default)
    "spec_kit_enabled": False,
    # --- local only, no model or socket: a range printed twice is one value; a combined label names its attributes (#1472, off by default)
    "datasheet_one_value_enabled": False,
    # --- local only, no socket: the bench also prints the planted-defect table (#1607, off by default)
    "planted_defects_bench_enabled": False,
    # --- local only, no model or socket: a split abbreviation is joined; a unit left off one copy is one value (off by default)
    "datasheet_label_join_enabled": False,
    # --- local only, no model or socket: a drawing is checked against a DRAFT must-contain list (#1484, off by default)
    "parked_kits_draft_enabled": False,
    # --- local only, no model or socket: a transmittal is checked against the held documents and a named list (#1482, off by default)
    "transmittal_kit_enabled": False,
    "transmittal_required_list_document_ids": "",
    # --- local only, no model or socket: the document kind chooses the rule set (#1474, off by default)
    "kind_chooses_rules_enabled": False,
    # --- local only, no model or socket: rules for another equipment type or kind are left out and counted (off by default)
    "rules_by_equipment_scope_enabled": False,
    # --- local only, no model or socket: extraction stores each rule's equipment scope (off by default)
    "rule_equipment_scope_extract_enabled": False,
    # --- local model only (model_transport), re-extraction script only: scope for clauses the code left unknown (off by default)
    "rule_equipment_scope_model_enabled": False,
    # --- local only, no model or socket: draft pump kit cards join the pump checklist (#1478, off by default)
    "pump_kit_draft_enabled": False,
    # --- local only, no model or socket: a value at a percent limit is at it in every unit (#1475, off by default)
    "at_limit_precision_enabled": False,
    "percent_kind_check_enabled": False,
    # --- local only, no model or socket: CRS export quality, export only (#1503, off by default)
    "crs_export_quality_enabled": False,
    "crs_export_quality_strict_enabled": False,
    "crs_one_row_per_problem_enabled": False,
    # --- local only, no model or socket: a row with no page says its section or field (#1591, off by default)
    "crs_page_cell_field_enabled": False,
    # --- local only, no model or socket: draft vessel kit cards join the vessel checklist (#1480, off by default)
    "vessel_kit_draft_enabled": False,
    # --- local only, no model or socket: a leading-dot decimal is read as the decimal (#1515, off by default)
    "leading_dot_decimal_enabled": False,
    "data_page_not_frontmatter_enabled": False,
    # --- local only, no model or socket: a repeated rights footer is not front-matter evidence (#1478, off by default)
    "running_footer_not_frontmatter_enabled": False,
    # --- local only, no model or socket: a drawing page with a header only is routed to recognition (off by default)
    "figure_page_ocr_enabled": False,
    # --- local only, no model or socket: duty-point style column rows and stacked labels (#1478, off by default)
    "page_column_rows_enabled": False,
    # --- local only, no model or socket: only the title block sets the equipment type (1 Nov, off by default)
    "equipment_from_title_block_enabled": False,
    # --- local only, no model or socket: PDF headings from font size and weight (#1522, off by default)
    "pdf_heading_detection_enabled": False,
    "word_page_markers_enabled": False,
    # --- read by the page only, one local /api/auth/me a minute, no model or socket (order 4b, off by default)
    "session_expired_notice_enabled": False,
    # --- local only, no model or socket: the CRS notice names its parts and says why rows await a tick (#1592, off by default)
    "crs_plain_notes_enabled": False,
    "run_record_enabled": False,
    # --- local only, no model or socket: one meaning of "checked" on screen and CRS (plan change 6 B, off by default)
    "one_checked_definition_enabled": False,
    # --- local only, no model or socket: a recognition file error holds the document (#1568, off by default)
    "ocr_file_error_hold_enabled": False,
    # --- local only, no model or socket: the rulebook tables on a database copy (plan change 6 A, off by default)
    "rulebook_v2_enabled": False,
    "owner_approved_rules_decide_enabled": False,
    "presence_not_pass_enabled": False,
    "rulebook_v2_review_enabled": False,
    "owner_note_lifts_context_flag_enabled": False,
    "material_reference_enabled": False,
    # --- local only, no model or socket: a procedure's CRS fields, equipment, page, Item No (order 4c, off by default)
    "procedure_crs_fields_enabled": False,
    # --- WIDENS what the Claude lane may carry (#1584, off by default); no socket of its own
    "claude_auto_approve_reviews_enabled": False,
    # --- local only, no socket of its own: a draft checklist leaves its standards in scope (Lock 2, off by default)
    "draft_checklist_keeps_standards_enabled": False,
    "claude_cost_controls_enabled": False,
    # --- local only, no model or socket: a playbook element is present only in its own section (#1522, off by default)
    "playbook_section_presence_enabled": False,
    # --- local only, no model or socket: presence check of a playbook whose standard is not held (#1522, off by default)
    "playbook_presence_without_standard_enabled": False,
    # --- local only, no model or socket: a procedure's CRS gets its playbook rows as engineer rows (#1522 b, off by default)
    "procedure_playbook_rows_enabled": False,
    # --- local only, no model or socket: draft exchanger kit cards join the heat exchanger checklist (#1481, off by default)
    "exchanger_kit_draft_enabled": False,
}

#: Path fields the suite WRITES through. They must point inside a temp dir,
#: never at `backend/data` (the live DB, the real spend ledger, the real
#: Claude response cache). Model directories are read-only and stay put.
WRITE_PATHS = ("data_dir", "upload_dir", "db_path", "claude_spend_log", "claude_cache_dir")
READ_ONLY_PATHS = ("embed_model_dir", "ocr_model_dir", "rule_trust_reference_path")

#: Name shapes that mean "this field might open a socket, hold a secret or
#: touch a path". Every field matching one must appear in EGRESS_SAFE,
#: WRITE_PATHS or READ_ONLY_PATHS - see test_env_isolation.py.
RISKY_NAME_PARTS = (
    "enabled", "egress", "api_key", "secret", "password", "username",
    "provider", "endpoint", "url", "host", "email", "smtp", "schedule",
    "folder", "_dir", "_path", "_log", "auth_mode", "allow_remote",
)

LIVE_DATA_DIR = BACKEND_DIR / "data"


def _field_names() -> set[str]:
    return set(Settings.model_fields)


def scrub_environment(env=None) -> list[str]:
    """Remove every variable that could configure the app. Returns the NAMES
    removed (never values: one of them may be a key)."""
    env = os.environ if env is None else env
    fields = _field_names()
    removed = []
    for name in list(env):
        if (name.lower() in fields or name in DIRECT_ENV_NAMES
                or name.startswith(DIRECT_ENV_PREFIXES)):
            del env[name]
            removed.append(name)
    return sorted(removed)


def isolate(target: Settings, env=None) -> list[str]:
    """Make `target` hold the code's defaults and nothing from this machine.

    Idempotent. Returns the names of environment variables removed.
    """
    Settings.model_config["env_file"] = None
    removed = scrub_environment(env)
    clean = Settings()
    for name in Settings.model_fields:
        setattr(target, name, getattr(clean, name))
    target.allowed_hosts = TEST_ALLOWED_HOSTS
    lifted = _lifted(env)
    for name, value in TEST_PINS.items():
        if name not in lifted:
            setattr(target, name, value)
    return removed


def _lifted(env=None) -> tuple[str, ...]:
    """The Lock 3 pins this session does not hold. Egress gates are never in the list."""
    return LOCK3_PINNED if (os.environ if env is None else env).get(LIFT_ENV) else ()


EGRESS_SAFE.update(dict.fromkeys(_lifted(), True))


def unsafe_fields(target: Settings) -> list[str]:
    """Fields of `target` not at their safe value. Names only, never values."""
    return sorted(n for n, safe in EGRESS_SAFE.items()
                  if (getattr(target, n) not in safe if isinstance(safe, OneOf)
                      else getattr(target, n) != safe))


def paths_outside(target: Settings, root: Path) -> list[str]:
    """WRITE_PATHS of `target` that do not lie under `root`."""
    root = Path(root).resolve()
    bad = []
    for name in WRITE_PATHS:
        p = Path(getattr(target, name)).resolve()
        if p != root and root not in p.parents:
            bad.append(name)
    return bad


# ------------------------------------------------------------ network guard


class EgressBlocked(ConnectionRefusedError):
    """A test tried to reach something other than this machine.

    An OSError, so the code under test sees exactly what an air-gapped
    machine would show it. It is ALSO recorded, because code that catches
    OSError and falls back quietly would otherwise hide the attempt - the
    autouse fixture in conftest fails the test by name.
    """


#: Attempts recorded since the last `take_attempts()`.
_attempts: list[str] = []
_installed = False


def _loopback_host(host) -> bool:
    if host is None or host == "":
        return True
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    host = str(host).strip("[]").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.split("%")[0]).is_loopback
    except ValueError:
        return False


def _ip_literal(host) -> bool:
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    try:
        ipaddress.ip_address(str(host).strip("[]").split("%")[0])
        return True
    except ValueError:
        return False


def _refuse(what: str):
    _attempts.append(what)
    raise EgressBlocked(f"test network guard: refused {what} (tests may reach loopback only)")


#: A proxy on loopback would carry a request anywhere while the socket this
#: guard sees goes only to 127.0.0.1 - measured: the sandbox that built this
#: guard exports HTTPS_PROXY=http://127.0.0.1:<port>, and corporate laptops
#: often run one too. httpx honours these (trust_env), so they are removed.
PROXY_ENV_NAMES = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "WS_PROXY", "WSS_PROXY")


def install_network_guard(env=None) -> list[str]:
    """Refuse DNS lookups of real names and connections to non-loopback
    addresses for the rest of the process. AF_UNIX and loopback are allowed,
    so TestClient, socketpair and a local fake Ollama keep working.

    Also removes proxy variables (see PROXY_ENV_NAMES). Returns the names
    removed."""
    global _installed
    env = os.environ if env is None else env
    removed = sorted(n for n in list(env) if n.upper() in PROXY_ENV_NAMES)
    for name in removed:
        del env[name]
    if _installed:
        return removed
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo

    def _check(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            host = address[0] if isinstance(address, tuple) else address
            if not _loopback_host(host):
                _refuse(f"connect to {host!r}")

    def connect(self, address):
        _check(self, address)
        return real_connect(self, address)

    def connect_ex(self, address):
        _check(self, address)
        return real_connect_ex(self, address)

    def getaddrinfo(host, *args, **kwargs):
        if not (_loopback_host(host) or _ip_literal(host)):
            _refuse(f"DNS lookup of {host!r}")
        return real_getaddrinfo(host, *args, **kwargs)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.getaddrinfo = getaddrinfo
    _installed = True
    return removed


def take_attempts() -> list[str]:
    """Blocked attempts since the last call, and reset."""
    out = list(_attempts)
    _attempts.clear()
    return out
