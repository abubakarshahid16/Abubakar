"""PF1 runner (#881, order 169): orchestration against a FAKE server.

No network, no model, no document text: the fake answers the routes the real
app has (`POST /api/documents`, `/api/documents/bulk/role`,
`/api/standards/{id}/requirements/extract-async`, `POST /api/reviews/run`,
`GET /api/jobs/{id}`, `POST /api/auth/login`). The tests prove the runner's own
rules: it refuses the live port and a non-local host, it never runs a held-out
sheet unless asked, one failing sheet does not hide the others, a job that never
finishes is an error and not a pass, and a record holds ids, states and
minutes only.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tools import pf1_run


class FakeServer:
    """The app's routes, enough for one sheet. `script` changes one answer."""

    def __init__(self, **script):
        self.script = script
        self.calls: list[tuple[str, str]] = []
        self.uploads: list[str] = []
        self.fields: list[dict | None] = []
        self.polls = 0
        self.puts: list[tuple[str, dict]] = []
        self.roles: list[dict] = []

    def request(self, method, path, json_body=None, file=None, fields=None):
        self.calls.append((method, path))
        if path == "/api/health":
            return 200, self.script.get(
                "health", {"ok": True, "database_live_shaped": False}
            )
        if path == "/api/admin/database-shape":
            return self.script.get("shape", (200, {"live_shaped": False}))
        if path == "/api/auth/login":
            ok = json_body["password"] == "right"
            return (200, {"token": "t"}) if ok else (401, None)
        if path == "/api/documents":
            self.uploads.append(Path(file).name)
            self.fields.append(fields)
            if Path(file).name in self.script.get("refused_uploads", ()):
                return 400, None
            n = len(self.uploads)
            return 200, {"document": {"id": f"doc{n}"}, "job_id": f"ing{n}"}
        if method == "PUT" and path.endswith("/classification"):
            self.puts.append((path, json_body))
            return self.script.get("put", (200, {"document_id": "x"}))
        if path == "/api/documents/bulk/role":
            self.roles.append(json_body)
            if json_body["document_role"] in self.script.get("refused_roles", ()):
                return 400, None
            return 200, {"updated": len(json_body["document_ids"])}
        if path.endswith("/requirements/extract-async"):
            return 200, {"job_id": "ext1", "state": "queued"}
        if path == "/api/reviews/run":
            return 200, {
                "review_run_id": "run1",
                "job": {"id": "rev1", "state": "queued"},
            }
        if path.startswith("/api/jobs/"):
            self.polls += 1
            job = path.rsplit("/", 1)[1]
            state = self.script.get("states", {}).get(job, "done")
            if state == "never":
                state = "running"
            return 200, {"state": state}
        return 404, None


def _entry(name="pf1-01", standard="pf1-01.standard.pdf", held_out=False):
    return {
        "id": name,
        "equipment_type": "Invented Pump",
        "group": "invented",
        "held_out": held_out,
        "datasheet": f"{name}.datasheet.pdf",
        "standard": standard,
        "standard_number": "STD-01" if standard else None,
    }


def _clock():
    t = [0.0]

    def now():
        t[0] += 30.0
        return t[0]

    return now


def _run(server, entry=None, **kw):
    return pf1_run.run_sheet(
        server,
        entry or _entry(),
        Path("/set"),
        sleep=lambda s: None,
        clock=_clock(),
        **kw,
    )


def test_a_sheet_runs_the_whole_path_in_order_and_the_record_holds_ids_only():
    server = FakeServer()
    record = _run(server)
    assert [c for c in server.calls if c[0] == "POST"] == [
        ("POST", "/api/documents"),
        ("POST", "/api/documents/bulk/role"),
        ("POST", "/api/standards/doc1/requirements/extract-async"),
        ("POST", "/api/documents"),
        ("POST", "/api/documents/bulk/role"),
        ("POST", "/api/reviews/run"),
    ]
    assert server.uploads == ["pf1-01.standard.pdf", "pf1-01.datasheet.pdf"]
    assert record["status"] == "completed"
    assert record["review_run_id"] == "run1"
    assert record["job_state"] == "done"
    assert record["error"] is None
    assert set(record) == {
        "format",
        "id",
        "equipment_type",
        "group",
        "held_out",
        "review_run_id",
        "job_state",
        "status",
        "minutes",
        "error",
    }


def test_a_library_group_sheet_has_no_standard_to_upload():
    server = FakeServer()
    record = _run(server, _entry(standard=None))
    assert server.uploads == ["pf1-01.datasheet.pdf"]
    assert record["status"] == "completed"


def test_the_disciplines_go_with_every_upload():
    server = FakeServer()
    _run(server, disciplines=["Mechanical"])
    assert server.fields == [{"disciplines": ["Mechanical"]}] * 2


def test_a_review_job_that_failed_is_not_completed():
    server = FakeServer(states={"rev1": "failed"})
    record = _run(server)
    assert record["status"] == "not_completed"
    assert record["job_state"] == "failed"
    assert record["review_run_id"] == "run1"


def test_a_job_that_never_finishes_is_an_error_not_a_pass():
    server = FakeServer(states={"rev1": "never"})
    record = _run(server, timeout=100.0)
    assert record["status"] == "error"
    assert "was not finished" in record["error"]
    assert server.polls > 3


def test_a_standard_whose_extraction_failed_stops_the_sheet_before_its_review():
    server = FakeServer(states={"ext1": "failed"})
    record = _run(server)
    assert record["status"] == "error"
    assert "extraction ended failed" in record["error"]
    assert ("POST", "/api/reviews/run") not in server.calls


def test_a_refused_upload_ends_the_sheet_with_a_plain_message():
    server = FakeServer(refused_uploads=("pf1-01.datasheet.pdf",))
    record = _run(server)
    assert record["status"] == "error"
    assert "upload of pf1-01.datasheet.pdf failed (HTTP 400)" in record["error"]


def test_the_minutes_are_the_clock_difference():
    record = _run(FakeServer())
    assert record["minutes"] > 0


def test_a_held_out_sheet_is_skipped_unless_asked_and_one_bad_sheet_does_not_hide_the_rest(
    tmp_path,
):
    index = {
        "documents": [
            _entry("a"),
            _entry("b", held_out=True),
            _entry("c"),
        ]
    }
    server = FakeServer(refused_uploads=("a.datasheet.pdf",))
    records = pf1_run.run_set(
        server, index, Path("/set"), tmp_path / "out", sleep=lambda s: None
    )
    assert [r["id"] for r in records] == ["a", "c"]
    assert [r["status"] for r in records] == ["error", "completed"]
    held = pf1_run.run_set(
        FakeServer(),
        index,
        Path("/set"),
        tmp_path / "held",
        include_held_out=True,
        only=["b"],
        sleep=lambda s: None,
    )
    assert [r["id"] for r in held] == ["b"]
    assert held[0]["held_out"] is True
    written = json.loads((tmp_path / "out" / "run-index.json").read_text())
    assert [r["id"] for r in written["runs"]] == ["a", "c"]
    assert (tmp_path / "out" / "c.run.json").exists()
    assert pf1_run.summary(records) == {
        "sheets": 2,
        "completed": 1,
        "not_completed": 0,
        "errors": 1,
        "minutes": pf1_run.summary(records)["minutes"],
    }


@pytest.mark.parametrize(
    "url, flag, message",
    [
        ("http://127.0.0.1:11435", False, "--test-server"),
        ("http://127.0.0.1:8000", True, "live app has run on"),
        ("http://127.0.0.1", True, None),
        ("http://example.com:11435", True, "on this machine"),
        ("ftp://127.0.0.1:11435", True, "must be an http"),
    ],
)
def test_the_server_must_be_a_local_test_server_not_the_live_app(url, flag, message):
    if message is None:
        assert pf1_run.check_server(url, flag) == url
        return
    with pytest.raises(pf1_run.RunError, match=message):
        pf1_run.check_server(url, flag)
    assert (
        pf1_run.check_server("http://localhost:11435/", True)
        == "http://localhost:11435"
    )


def test_login_returns_the_token_and_a_wrong_password_is_refused_without_echoing_it():
    server = FakeServer()
    assert pf1_run.login(server, "e@x", "right") == "t"
    with pytest.raises(pf1_run.RunError) as raised:
        pf1_run.login(server, "e@x", "wrong")
    assert "wrong" not in str(raised.value)
    assert "HTTP 401" in str(raised.value)


def test_a_duplicate_upload_uses_the_existing_document_and_waits_for_nothing():
    class Duplicate(FakeServer):
        def request(self, method, path, json_body=None, file=None, fields=None):
            if path == "/api/documents":
                return 200, {"document": None, "duplicate_of": "old1", "job_id": ""}
            return super().request(method, path, json_body, file, fields)

    assert pf1_run.upload(Duplicate(), Path("/set/x.pdf")) == ("old1", "")
    assert pf1_run.wait_job(Duplicate(), "", timeout=1.0) == "done"


def test_a_sheet_whose_ingestion_failed_never_starts_a_review():
    server = FakeServer(states={"ing2": "failed"})  # the sheet is the second upload
    record = _run(server)
    assert record["status"] == "error"
    assert "ingestion ended failed" in record["error"]
    assert ("POST", "/api/reviews/run") not in server.calls


@pytest.mark.parametrize("port", [8000, 8001])
def test_the_ports_the_live_app_has_run_on_are_refused(port):
    # The owner's laptop app has run on 8001 as well as the default 8000.
    with pytest.raises(pf1_run.RunError, match="live app has run on"):
        pf1_run.check_server(f"http://127.0.0.1:{port}", True)
    assert pf1_run.check_server("http://127.0.0.1:11435", True)


def test_a_diagnostic_copy_must_be_named_and_must_not_be_live_shaped(tmp_path):
    copy = tmp_path / "copy.sqlite"
    copy.write_bytes(b"")
    assert pf1_run.check_db_copy(str(copy)) == str(copy)
    with pytest.raises(pf1_run.RunError, match="name the diagnostic copy"):
        pf1_run.check_db_copy(None)
    live_dir = tmp_path / "backend" / "data"
    live_dir.mkdir(parents=True)
    live = live_dir / "rag_intelligence.sqlite"
    live.write_bytes(b"")
    with pytest.raises(pf1_run.RunError, match="live database's shape"):
        pf1_run.check_db_copy(str(live))
    with pytest.raises(pf1_run.RunError, match="not a file"):
        pf1_run.check_db_copy(str(tmp_path / "missing.sqlite"))


def test_a_poisoned_review_job_is_final_at_once_not_after_the_timeout():
    # `poisoned` is how a job really fails now; `failed` is only the legacy value.
    server = FakeServer(states={"rev1": "poisoned"})
    record = _run(server, timeout=3600.0)
    assert record["status"] == "not_completed"
    assert record["job_state"] == "poisoned"
    assert record["error"] is None
    assert server.polls == 4  # one poll per job: it did not poll on to the timeout


def test_a_poisoned_ingestion_stops_the_sheet_with_the_state_named():
    server = FakeServer(states={"ing2": "poisoned"})
    record = _run(server)
    assert record["status"] == "error"
    assert "ingestion ended poisoned" in record["error"]


def test_every_final_state_the_server_writes_ends_the_wait():
    from app import job_queue

    going = {job_queue.QUEUED, job_queue.RUNNING, job_queue.RETRYING}
    final = {job_queue.DONE, job_queue.POISONED, job_queue.CANCELLED}
    assert final <= pf1_run.TERMINAL
    assert not going & pf1_run.TERMINAL


def test_a_job_that_cannot_be_read_three_times_in_a_row_ends_the_wait_with_the_status():
    class NoJob(FakeServer):
        def request(self, method, path, json_body=None, file=None, fields=None):
            if path.startswith("/api/jobs/"):
                return 404, None
            return super().request(method, path, json_body, file, fields)

    record = _run(NoJob(), timeout=3600.0)
    assert record["status"] == "error"
    assert "could not be read (HTTP 404, 3 times)" in record["error"]


def test_a_server_that_says_its_database_is_live_shaped_is_refused_before_any_write(
    tmp_path,
):
    # A port proves nothing (the live app has run on 8000 and 8001): the server
    # is asked, and nothing is written when it says live.
    server = FakeServer(shape=(200, {"live_shaped": True}))
    with pytest.raises(pf1_run.RunError, match="live app's shape"):
        pf1_run.run_set(
            server, {"documents": [_entry()]}, Path("/set"), tmp_path / "out"
        )
    assert [c for c in server.calls if c[0] == "POST"] == []
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize(
    "shape",
    [
        (404, None),
        (500, None),
        (200, {}),
        (200, {"live_shaped": None}),
        (200, {"live_shaped": "no"}),
    ],
)
def test_a_server_that_cannot_say_whether_its_database_is_live_is_refused(
    shape, tmp_path
):
    server = FakeServer(shape=shape)
    with pytest.raises(pf1_run.RunError, match="does not say"):
        pf1_run.run_set(
            server, {"documents": [_entry()]}, Path("/set"), tmp_path / "out"
        )
    assert [c for c in server.calls if c[0] == "POST"] == []


def test_a_server_that_says_its_database_is_a_copy_is_accepted(tmp_path):
    server = FakeServer()
    pf1_run.assert_test_database(server)
    records = pf1_run.run_set(
        server,
        {"documents": [_entry()]},
        Path("/set"),
        tmp_path / "out",
        sleep=lambda s: None,
    )
    assert records[0]["status"] == "completed"


def test_the_standards_number_is_recorded_so_the_review_applies_it_to_its_sheet():
    """Found by the first PF1 run: an uploaded standard has no recorded number,
    the review includes a standard only by its recorded number, so 0 of 23 keyed
    items were checked. The number goes in right after the role, before the
    requirements are extracted."""
    server = FakeServer()
    record = _run(server)
    assert record["status"] == "completed"
    assert server.puts == [
        (
            "/api/documents/doc1/classification",
            {"document_role": "COMPANY_STANDARD", "document_number": "STD-01"},
        )
    ]
    order = [c for c in server.calls if c[0] in ("POST", "PUT")]
    assert order.index(("PUT", "/api/documents/doc1/classification")) < order.index(
        ("POST", "/api/standards/doc1/requirements/extract-async")
    )


def test_a_refused_number_ends_the_sheet_with_a_plain_error_not_a_silent_skip():
    record = _run(FakeServer(put=(403, None)))
    assert record["status"] == "error"
    assert "document number" in record["error"]


def test_a_standard_with_no_number_in_the_index_records_none():
    server = FakeServer()
    entry = {**_entry(), "standard_number": None}
    _run(server, entry)
    assert server.puts == []


def test_the_sheet_is_marked_as_a_contractor_submittal_before_its_review():
    """Order 206.1: the client workflow marks the file; the READY and role-change
    hooks then fill its equipment type and title. Without the mark a sheet was
    reviewed with empty fields and the part-scope step held every clause."""
    server = FakeServer()
    _run(server)
    assert server.roles == [
        {"document_ids": ["doc1"], "document_role": "COMPANY_STANDARD"},
        {"document_ids": ["doc2"], "document_role": "CONTRACTOR_SUBMITTAL"},
    ]
    posts = [c for c in server.calls if c[0] == "POST"]
    assert posts.index(("POST", "/api/reviews/run")) > len(posts) - 2


def test_a_refused_submittal_mark_ends_the_sheet_before_any_review():
    server = FakeServer(refused_roles=("CONTRACTOR_SUBMITTAL",))
    record = _run(server)
    assert record["status"] != "completed" and record["error"]
    assert ("POST", "/api/reviews/run") not in server.calls
