"""Host telemetry on /api/metrics belongs to the ADMIN CAPABILITY (#77).

WHAT THIS FILE IS ABOUT, and what it is deliberately not about.

#75 scoped the corpus figures by the caller's grants. This is a different
disclosure and the grant scoping cannot reach it: the machine's CPU core
count, its total RAM, its disk size and this process's resident footprint are
not anybody's document, so there is no grant that could exclude them. They
were served to EVERY authenticated caller regardless of role - 14 fields of
fingerprinting material from a product whose stated boundary is "nothing
leaves this machine".

THE RULE UNDER TEST: a non-admin gets NO host block at all. Not zeros, not a
block of nulls. This module's own docstring says a value that has not been
measured is null and the screen says so; a block of zeros would go further and
STATE measurements that are false - 0 bytes of RAM, a 0-byte disk - which is
the exact failure the honesty audit was about, inverted. An absent block says
nothing. That is the only honest answer for a caller who may not be told.

WHY THE ADMIN CAPABILITY AND NOT A DOCUMENT GRANT: `roles.kind = 'capability'`
is the database's own answer to "is this person an administrator", resolved
once per request into `AccessScope.capabilities` and read through
`AccessScope.is_admin`. `admin.is_admin()` answers the same question from the
role NAME, and the two are only equal because `init_db` re-asserts
`kind = 'capability' WHERE name = 'admin'` on every start. These tests assert
against the CAPABILITY, so a database where the two ever diverge fails here
rather than quietly granting host telemetry to whoever is called "admin".

`data_dir_bytes` is included in the fourteen on purpose even though it
measures the corpus rather than the machine: it is a field of the host block
and it sizes the install. If it is ever wanted for a non-admin it has to move
out of the block, not be excepted from the rule.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import access, db, keyword, metrics, states
from app.config import settings
from app.db import connect
from app.main import app

NOW = "2026-09-06T00:00:00Z"

#: Every field `metrics.system()` emits. Named one by one rather than derived
#: from the function, so that ADDING a host field to `system()` does not
#: silently join the set this test claims to be guarding - a new field would
#: be leaked and the test would still pass. Fourteen, as measured on the
#: defect report.
HOST_FIELDS = (
    "cpu_percent_since_last_call",
    "cpu_window_seconds",
    "cpu_logical_cores",
    "cpu_physical_cores",
    "ram_total_bytes",
    "ram_used_bytes",
    "ram_free_bytes",
    "ram_percent",
    "process_rss_bytes",
    "disk_total_bytes",
    "disk_used_bytes",
    "disk_free_bytes",
    "disk_percent",
    "data_dir_bytes",
)


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "u")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    # `chunks_fts` is created by the keyword indexer rather than by `init_db`,
    # and `metrics.corpus()` counts it unconditionally. Without this the
    # endpoint raises "no such table: chunks_fts" and every assertion in this
    # file fails for a reason that has nothing to do with disclosure.
    connect().executescript(keyword.SCHEMA)
    yield
    access.set_user_resolver(None)
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    db.reset_connection()


def _document(doc_id: str, filename: str) -> str:
    """A finished document row. No ingestion: this file tests disclosure, and
    a real PDF would only make it slower without making it prove more."""
    with connect() as conn:
        conn.execute(
            """INSERT INTO documents (id, filename, sha256, size_bytes,
                    stored_path, page_count, pages_done, chunk_count,
                    chunk_count_total, status, uploaded_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (doc_id, filename, f"sha-{doc_id}", 1024, f"/nowhere/{filename}",
             3, 3, 5, 5, states.READY, NOW))
    return doc_id


def _user(user_id: str, role_name: str, kind: str, documents: tuple[str, ...]):
    """A user holding one role of a stated KIND, with read grants.

    `kind` is passed explicitly rather than defaulted because it is the whole
    subject of these tests: 'capability' is an administrator, 'discipline' is
    an ordinary engineer, and the difference must be visible at every call
    site here rather than hidden in a default.
    """
    role_id = f"role_{role_name}"
    with connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, display_name,"
            " password_hash, created_at) VALUES (?,?,?,?,?)",
            (user_id, f"{user_id}@example.test", user_id, "hash", NOW))
        conn.execute(
            "INSERT OR IGNORE INTO roles (id, name, description, kind,"
            " created_at) VALUES (?,?,?,?,?)",
            (role_id, role_name, role_name, kind, NOW))
        conn.execute(
            "INSERT OR IGNORE INTO user_roles (user_id, role_id, granted_at)"
            " VALUES (?,?,?)", (user_id, role_id, NOW))
        for d in documents:
            conn.execute(
                "INSERT OR IGNORE INTO document_role_access (document_id,"
                " role_id, permission, granted_at) VALUES (?,?,'read',?)",
                (d, role_id, NOW))


@pytest.fixture
def corpus_and_identities(monkeypatch):
    """Two documents, an admin, an engineer granted one of them, and a client
    whose identity comes from a header - so one fixture drives every caller
    class without three copies of the setup.

    The admin holds the `admin` role with `kind = 'capability'` and NO
    document grant, which is the real shape of the thing: `access.py` gives an
    administrator no read bypass. Admin-ness here is a capability and nothing
    else, which is exactly what makes it the right gate for a disclosure that
    is not about documents.
    """
    first = _document("doc_first", "specification.pdf")
    second = _document("doc_second", "coating-schedule.pdf")
    _user("admin_user", "admin", "capability", ())
    _user("engineer", "Civil-Engineering", "discipline", (first,))
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    access.set_user_resolver(lambda req: req.headers.get("x-test-user") or None)
    return TestClient(app), first, second


def _metrics(client, user: str | None):
    headers = {"x-test-user": user} if user else {}
    response = client.get("/api/metrics", headers=headers)
    assert response.status_code == 200, (
        f"/api/metrics returned {response.status_code} for "
        f"{user or 'an unauthenticated caller'} - this file is about WHAT the "
        f"payload contains, so a non-200 means the endpoint broke rather than "
        f"that the disclosure was fixed:\n{response.text[:400]}")
    return response.json()


def _leaked(payload: dict) -> list[str]:
    """Every host field present ANYWHERE in the payload, by name.

    Searched recursively rather than by reading `payload['system']`, because
    "the block was renamed" and "the block was moved under another key" are
    both ways of continuing to serve the same fourteen numbers while a test
    that only knows one key path goes green.
    """
    found: list[str] = []

    def walk(node, path: str):
        if isinstance(node, dict):
            for key, value in node.items():
                here = f"{path}.{key}" if path else key
                if key in HOST_FIELDS:
                    found.append(here)
                walk(value, here)
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, f"{path}[{i}]")

    walk(payload, "")
    return found


# --------------------------------------------------------- the disclosure

def test_an_authenticated_non_admin_receives_no_host_telemetry(
        corpus_and_identities):
    """THE DEFECT. An engineer is authenticated and holds a real grant, and
    that grant is about a document - it says nothing about whether they may
    be told this machine's core count.

    ONE NULL, NOT FOURTEEN, AND NOT NECESSARILY AN ABSENT KEY. Pydantic
    serialises a `SystemMetrics | None` field as `"system": null` even when the
    route's dict omits the key entirely, so true absence on the wire would need
    `response_model_exclude_none=True` on the route - which would also strip
    `retrieval`, `cpu_percent_since_last_call`, `disk_percent` and
    `ollama_error`, every one of which the dashboard reads with an explicit
    `== null` check and renders as "not measured yet". Buying key-absence here
    would silently change four other fields from "measured as nothing" to "not
    sent", which is the exact confusion this module exists to prevent. A single
    null for the whole block discloses nothing about the machine and is the
    idiom `Metrics` already uses.
    """
    client, _, _ = corpus_and_identities
    payload = _metrics(client, "engineer")

    leaked = _leaked(payload)
    assert leaked == [], (
        "an authenticated non-admin was served host telemetry: "
        + ", ".join(leaked))
    assert payload.get("system") is None, (
        "the host block is populated for a non-admin. It must carry NOTHING - "
        "the key absent, or a single null standing for the whole block. What "
        "it must never be is a block of zeros or a block of per-field nulls: "
        "`ram_total_bytes: 0` is not a withheld measurement, it is a false "
        "one, and fourteen nulls is fourteen fields still describing the "
        "shape of what is being withheld.")


def test_the_host_block_is_omitted_rather_than_blanked(corpus_and_identities):
    """A separate assertion from the one above, because the two failures are
    different bugs with the same symptom on screen. Zeros are the tempting
    fix - the response model's ints are not nullable - and they would be a
    worse defect than the leak: `ram_total_bytes: 0` is not a withheld value,
    it is a false one, and the dashboard would render "0 B free of 0 B" as a
    measurement."""
    client, _, _ = corpus_and_identities
    payload = _metrics(client, "engineer")
    assert payload.get("system", None) is None, (
        f"host block served to a non-admin as {payload['system']!r}. The rule "
        f"is omission: a value this endpoint may not state renders as nothing, "
        f"and a zero here would be a stated measurement that is false.")


def test_an_admin_still_receives_every_host_field(corpus_and_identities):
    """The operator need is real and this fix must not remove it. All
    fourteen, present, for the capability that is allowed to see them."""
    client, _, _ = corpus_and_identities
    payload = _metrics(client, "admin_user")

    assert "system" in payload, "the admin lost the host block entirely"
    missing = [f for f in HOST_FIELDS if f not in payload["system"]]
    assert missing == [], f"admin is missing host fields: {missing}"
    assert payload["system"]["ram_total_bytes"] > 0, (
        "the admin's host block is present but not measured - a gate that "
        "returns an empty shell to the one caller allowed to see it has "
        "removed the feature rather than scoped it")


def test_an_unauthenticated_caller_receives_no_host_telemetry(
        corpus_and_identities):
    """Confirmed rather than assumed. Under AUTH_REQUIRED an unidentified
    caller resolves to `empty_scope()`, which is not an error and not
    everything - and it is certainly not an administrator."""
    client, _, _ = corpus_and_identities
    payload = _metrics(client, None)

    leaked = _leaked(payload)
    assert leaked == [], (
        "an UNAUTHENTICATED caller was served host telemetry: "
        + ", ".join(leaked))


# ------------------------------------------- the corpus figures are untouched

@pytest.mark.parametrize("user,expected_allowed", [
    ("admin_user", None),
    ("engineer", ["doc_first"]),
    (None, []),
])
def test_the_corpus_figures_are_unchanged_for_every_caller_class(
        corpus_and_identities, user, expected_allowed):
    """#75's scoping is the thing this change must not disturb.

    Compared against `metrics.corpus()` computed directly for the same
    allow-list rather than against hard-coded counts, so this asserts "the
    route still reports what the scoped query reports" - which is the claim -
    instead of re-stating the fixture's document count in a second place where
    it would need editing whenever the fixture changes.

    The admin's `None` and the unauthenticated caller's `[]` are the two ends
    that must never be conflated: corpus-wide versus granted nothing.
    """
    client, _, _ = corpus_and_identities
    payload = _metrics(client, user)

    assert payload["corpus"] == metrics.corpus(expected_allowed), (
        f"the corpus block for {user or 'an unauthenticated caller'} no longer "
        f"matches the scoped query for allowed={expected_allowed!r}")
    assert payload["corpus_wide"] is (expected_allowed is None), (
        "corpus_wide no longer states which kind of number the payload holds")


def test_gating_the_host_block_did_not_silently_widen_the_corpus(
        corpus_and_identities):
    """The engineer holds one of two documents. If the admin gate were ever
    implemented by handing non-admins a corpus-wide snapshot minus the host
    block, this is what would catch it."""
    client, first, second = corpus_and_identities
    engineer = _metrics(client, "engineer")
    admin = _metrics(client, "admin_user")

    assert engineer["corpus"]["documents"] == 1, (
        "the engineer is granted one of two documents and the corpus block "
        "must say one")
    assert admin["corpus"]["documents"] == 2, (
        "the admin reads corpus-wide aggregate counts")


# ------------------------------------------------- the warning a reader needs

def test_the_low_memory_warning_still_reaches_a_non_admin(
        corpus_and_identities, monkeypatch):
    """DECIDED: the warning STAYS for everyone, the numbers inside it do not.

    `low_memory_for_answer_model` is not host telemetry, it is a statement
    about what the product is about to fail to do - Tier 2 may swap hard or
    fail, quoted answers are unaffected. Dropping it with the host block would
    make the warning disappear for exactly the users who are about to press
    Explain, and a warning that vanishes silently is worse than one a reader
    cannot fully act on. What it must NOT do is smuggle the fourteen fields
    back in as prose: "0.6 GB of RAM free" is `ram_free_bytes` rounded, and
    `answer_model_ram_bytes` is configuration rather than a measurement of
    this machine, so the free figure is the part that has to go for a
    non-admin while the consequence and the remedy stay.
    """
    import psutil

    class Tight:
        total = 16_000_000_000
        available = 600_000_000
        percent = 96.0

    monkeypatch.setattr(psutil, "virtual_memory", lambda: Tight)
    monkeypatch.setattr(settings, "answer_model_ram_bytes", 5_000_000_000)
    # AND the model's residency, which is the other half of the condition:
    # `warnings()` raises this only when the model is NOT already loaded,
    # because a resident model has already paid the memory it needs. `models()`
    # answers that by asking the real Ollama over HTTP, so without this pin the
    # test passes or fails on whether the developer happens to have run a query
    # recently - it was green in isolation and red in the full suite for
    # exactly that reason, with no code change between the two runs. Pinned to
    # "reachable but not resident", the state in which the warning is the
    # actionable thing it exists to be.
    monkeypatch.setattr(metrics, "models", lambda: {
        "embed_model": "e5-small", "embed_model_present": True,
        "reranker_model": "reranker", "reranker_present": True,
        "answer_model": settings.answer_model,
        "answer_model_reachable": True, "answer_model_installed": True,
        "answer_model_loaded": False, "ollama_error": None,
    })

    client, _, _ = corpus_and_identities
    payload = _metrics(client, "engineer")

    codes = [w["code"] for w in payload["warnings"]]
    assert "low_memory_for_answer_model" in codes, (
        "the low-memory warning was dropped for a non-admin. It is the "
        "product telling a user that Explain may fail, not a host "
        "measurement, and it must not disappear with the host block.")

    message = next(w["message"] for w in payload["warnings"]
                   if w["code"] == "low_memory_for_answer_model")
    assert "0.6 GB" not in message, (
        "the non-admin's warning restates free RAM in prose - the same "
        "measurement the host block was gated to withhold, rounded. Gating a "
        "block and then printing its contents in a sentence is not a gate.")
    assert "Explain" in message or "Tier 2" in message, (
        "the warning no longer says WHAT may fail, which is the only part a "
        "non-admin can act on")


def test_the_admin_low_memory_warning_still_states_the_figure(
        corpus_and_identities, monkeypatch):
    """The operator need the defect report names: the warning is actionable
    for an operator BECAUSE free RAM is known. An admin keeps the number."""
    import psutil

    class Tight:
        total = 16_000_000_000
        available = 600_000_000
        percent = 96.0

    monkeypatch.setattr(psutil, "virtual_memory", lambda: Tight)
    monkeypatch.setattr(settings, "answer_model_ram_bytes", 5_000_000_000)
    # AND the model's residency, which is the other half of the condition:
    # `warnings()` raises this only when the model is NOT already loaded,
    # because a resident model has already paid the memory it needs. `models()`
    # answers that by asking the real Ollama over HTTP, so without this pin the
    # test passes or fails on whether the developer happens to have run a query
    # recently - it was green in isolation and red in the full suite for
    # exactly that reason, with no code change between the two runs. Pinned to
    # "reachable but not resident", the state in which the warning is the
    # actionable thing it exists to be.
    monkeypatch.setattr(metrics, "models", lambda: {
        "embed_model": "e5-small", "embed_model_present": True,
        "reranker_model": "reranker", "reranker_present": True,
        "answer_model": settings.answer_model,
        "answer_model_reachable": True, "answer_model_installed": True,
        "answer_model_loaded": False, "ollama_error": None,
    })

    client, _, _ = corpus_and_identities
    payload = _metrics(client, "admin_user")

    message = next((w["message"] for w in payload["warnings"]
                    if w["code"] == "low_memory_for_answer_model"), None)
    assert message is not None, "the admin lost the low-memory warning"
    assert "0.6 GB" in message, (
        "the admin's warning no longer states free RAM, which is the figure "
        "that makes it actionable")


# ------------------------------------ the gate reads the KIND, not the name

def test_a_role_merely_NAMED_admin_is_not_the_admin_capability(
        corpus_and_identities):
    """The two predicates that answer "is this an administrator" are not the
    same question, and this file's own docstring claimed to be asserting the
    stronger one while every other test here is satisfied by either.

    `admin.is_admin()` reads the role NAME. `AccessScope.is_admin` reads
    `roles.kind = 'capability'`. The fixture above gives its admin BOTH - the
    name `admin` and the kind `capability` - so it cannot tell them apart, and
    the route shipped reading the name while its own comment said capability.

    This user holds a role NAMED admin whose kind is `discipline`. Under the
    name predicate they are an administrator and are served the machine's
    specifications. Under the capability predicate they are an engineer who
    happens to sit in a badly named role. `init_db` re-asserting the kind for
    the role literally called `admin` is what keeps the two agreeing today; it
    is not a guarantee, and a disclosure this size should not rest on a
    re-assertion running.

    The corpus figures are asserted alongside deliberately: this is one flag
    governing two disclosures, so a fix that moved the host gate to the
    capability and left the corpus gate on the name would leave the same
    confusion in place one line down.
    """
    client, _, _ = corpus_and_identities
    with connect() as conn:
        # The genuine capability role gives up the NAME first. `roles.name` is
        # unique, so without this the rename below collides instead of
        # proving anything - and the point is precisely that the name is a
        # movable label while the kind is the fact.
        conn.execute("UPDATE roles SET name = 'admin_capability'"
                     " WHERE id = 'role_admin'")
        conn.execute(
            "INSERT INTO users (id, email, display_name, password_hash,"
            " created_at) VALUES (?,?,?,?,?)",
            ("named_admin", "named_admin@example.test", "named_admin",
             "hash", NOW))
        # A role NAMED admin whose kind is `discipline`: an administrator to
        # the name predicate, an engineer to the capability predicate.
        conn.execute(
            "INSERT INTO roles (id, name, description, kind, created_at)"
            " VALUES (?,?,?,?,?)",
            ("role_fake_admin", "admin", "named, not empowered", "discipline",
             NOW))
        conn.execute(
            "INSERT INTO user_roles (user_id, role_id, granted_at)"
            " VALUES (?,?,?)", ("named_admin", "role_fake_admin", NOW))

    payload = _metrics(client, "named_admin")

    leaked = _leaked(payload)
    assert leaked == [], (
        "a role NAMED admin, whose kind is 'discipline', was served host "
        "telemetry: " + ", ".join(leaked) + ". The gate must read "
        "roles.kind = 'capability' through AccessScope.is_admin, not the "
        "role's name through admin.is_admin - a name is a label anybody with "
        "the admin screen can type.")
    assert payload["corpus_wide"] is False, (
        "the same misread name also handed corpus-wide figures to a "
        "non-capability role")
