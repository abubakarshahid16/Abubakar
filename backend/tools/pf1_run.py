"""Run a PF1 set through a TEST server, one sheet at a time (#881, order 169).

For each sheet of the builder's `index.json`: upload the sheet (and, for the
invented group, the invented standard it cites, set as a company standard and
extracted), start the review, wait for its job, and write a small run record.
The record holds the run id, the job's final state and the minutes: ids,
states and counts only, never a document's text. Scoring is not done here:
`review_score export` (from a COPY of the test server's database) turns the
run id into a findings file, and `review_score score` reads that.

Safety, in code:
* the server must be named with `--test-server`, must be on this machine, is
  refused on the live app's usual port (`LIVE_PORT`), and above all must say
  itself that its database is not live-shaped (`/api/health`): the port proves
  nothing, the live app has run on 8001 too. This runner writes documents and
  review runs;
* a held-out sheet is skipped unless `include_held_out` is set: held-out
  sheets are never run by the builders, only by the merger session;
* the login password is read from the environment, never an argument, never
  written to a record or a message.

Pure orchestration over a `transport` with one method, `request(method, path,
json_body=None, file=None, fields=None)` returning `(status, parsed JSON or None)`, so the
tests use a fake and the command uses `HttpTransport` (standard library only).
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from app import live_guard

RECORD_FORMAT = "pf1-run/1"
#: The ports the live app has run on (`python run.py`: 8000 by default, 8001 on
#: the owner's laptop). The runner never talks to them. A port proves nothing
#: either way (the live app's port is a setting): this is a backstop, and the
#: server's own statement of what database it holds is not available yet.
LIVE_PORTS = (8000, 8001)
#: A job in one of these states will not change. Anything else is still going.
#: `poisoned` is how a job really fails now (failed `job_max_retries + 1` times);
#: `failed` is only the pre-#177 legacy value. Held to `app.job_queue` by a test.
TERMINAL = frozenset({"done", "failed", "poisoned", "cancelled", "canceled", "dead"})
#: This many answers in a row that are not a job (404, 5xx) end the wait.
UNANSWERED_LIMIT = 3
#: What a finished job must say for the sheet to count as run.
OK_STATES = frozenset({"done"})


class RunError(RuntimeError):
    """A step of a sheet's run could not be done; the message has no document text."""


class Transport(Protocol):
    def request(
        self,
        method: str,
        path: str,
        json_body: dict | None = None,
        file: Path | None = None,
        fields: dict[str, list[str]] | None = None,
    ) -> tuple[int, dict | None]: ...


def check_server(base_url: str, test_server: bool) -> str:
    """The base URL, or a refusal: the flag must be given and the port must not
    be the live app's."""
    if not test_server:
        raise RunError(
            "name the server as a test server with --test-server; this runner writes documents and runs"
        )
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise RunError("the server address must be an http(s) URL")
    if parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise RunError(
            "the test server must be on this machine (127.0.0.1 or localhost)"
        )
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if port in LIVE_PORTS:
        raise RunError(
            f"port {port} is a port the live app has run on: use a test server on another port"
        )
    return base_url.rstrip("/")


def check_db_copy(path: str | None) -> str:
    """The diagnostic copy the run will be exported from: it must exist and
    must not have the live database's shape. The operator names it, so the run
    is never started without a copy in mind; the runner cannot see which
    database the server holds, and says so."""
    if not path:
        raise RunError("name the diagnostic copy of the database with --db-copy")
    if live_guard.is_live_shaped(path):
        raise RunError("--db-copy has the live database's shape: use a diagnostic copy")
    if not Path(path).is_file():
        raise RunError("--db-copy is not a file")
    return str(path)


class HttpTransport:
    """The real transport: JSON over HTTP with a bearer token, multipart for a file."""

    def __init__(self, base_url: str, token: str | None = None, timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def request(self, method, path, json_body=None, file=None, fields=None):
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        data = None
        if file is not None:
            boundary = uuid.uuid4().hex
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
            parts = b""
            for name, values in (fields or {}).items():
                for value in values:
                    parts += (
                        f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'
                    ).encode()
            data = (
                parts
                + (
                    f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                    f'filename="{Path(file).name}"\r\nContent-Type: application/pdf\r\n\r\n'
                ).encode()
                + Path(file).read_bytes()
                + f"\r\n--{boundary}--\r\n".encode()
            )
        elif json_body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(json_body).encode()
        req = urllib.request.Request(
            self.base_url + path, data=data, method=method, headers=headers
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                return exc.code, json.loads(raw) if raw else None
            except ValueError:
                return exc.code, None


def assert_test_database(transport: Transport) -> None:
    """Refuse a server that is not known to hold a test database. A PORT proves
    nothing (the live app has run on 8000 and 8001): the server says whether
    its database path has the live app's shape, on an admin route (the
    unauthenticated `/api/health` is not widened). A server that says true, or
    cannot say (an older build, a login that is not an admin's), is refused
    before any write."""
    status, body = transport.request("GET", "/api/admin/database-shape")
    if (
        status != 200
        or not isinstance(body, dict)
        or not isinstance(body.get("live_shaped"), bool)
    ):
        raise RunError(
            f"the server does not say whether its database is the live one (HTTP {status}): "
            "refused; log in as an admin of a build that has /api/admin/database-shape"
        )
    if body["live_shaped"]:
        raise RunError(
            "the server's database has the live app's shape: refused; use a diagnostic copy"
        )


def login(transport: Transport, email: str, password: str) -> str:
    status, body = transport.request(
        "POST", "/api/auth/login", {"email": email, "password": password}
    )
    if status != 200 or not body or not body.get("token"):
        raise RunError(f"login was refused (HTTP {status})")
    return body["token"]


def _expect(status: int, body: dict | None, what: str, ok=(200, 201, 202)) -> dict:
    if status not in ok or body is None:
        raise RunError(f"{what} failed (HTTP {status})")
    return body


def wait_job(
    transport: Transport,
    job_id: str,
    *,
    timeout: float,
    poll: float = 5.0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> str:
    """The job's final state, or a RunError when it is not final in `timeout`
    seconds. An empty job id (a duplicate upload) has nothing to wait for."""
    if not job_id:
        return "done"
    start = clock()
    unanswered = 0
    while True:
        status, body = transport.request("GET", f"/api/jobs/{job_id}")
        unanswered = unanswered + 1 if status != 200 else 0
        if unanswered >= UNANSWERED_LIMIT:
            raise RunError(
                f"job {job_id} could not be read (HTTP {status}, {unanswered} times)"
            )
        state = str((body or {}).get("state") or "") if status == 200 else ""
        if state in TERMINAL:
            return state
        if clock() - start > timeout:
            raise RunError(
                f"job {job_id} was not finished after {int(timeout)} s (state {state or 'unknown'})"
            )
        sleep(poll)


def upload(
    transport: Transport, path: Path, disciplines: list[str] | None = None
) -> tuple[str, str]:
    """(document id, ingestion job id) of an uploaded file. A duplicate answers
    with the existing document; its job id is empty."""
    body = _expect(
        *transport.request(
            "POST",
            "/api/documents",
            file=path,
            fields={"disciplines": disciplines} if disciplines else None,
        ),
        f"upload of {path.name}",
    )
    doc = body.get("document") or {}
    doc_id = doc.get("id") or body.get("duplicate_of")
    if not doc_id:
        raise RunError(f"upload of {path.name} gave no document (awaiting a grant?)")
    return doc_id, body.get("job_id") or ""


def prepare_standard(
    transport: Transport,
    path: Path,
    *,
    timeout: float,
    disciplines: list[str] | None = None,
    number: str | None = None,
    **wait,
) -> str:
    """Upload a standard, set it as a company standard, record its document
    number, and wait for its ingestion and its requirement extraction. Returns
    the document id.

    The number is the engineer's step of confirming what the standard is. The
    review includes a standard a sheet names only by the standard's RECORDED
    number: a number found in the file name or the title is "possible match,
    engineer to confirm" and is not included, so without it the standard is
    never applied to its sheet and nothing is checked."""
    doc_id, job_id = upload(transport, path, disciplines)
    state = wait_job(transport, job_id, timeout=timeout, **wait)
    if state not in OK_STATES:
        raise RunError(f"the standard's ingestion ended {state}")
    _expect(
        *transport.request(
            "POST",
            "/api/documents/bulk/role",
            {"document_ids": [doc_id], "document_role": "COMPANY_STANDARD"},
        ),
        "setting the standard's role",
        ok=(200, 207),
    )
    if number:
        _expect(
            *transport.request(
                "PUT",
                f"/api/documents/{doc_id}/classification",
                {"document_role": "COMPANY_STANDARD", "document_number": number},
            ),
            "recording the standard's document number",
        )
    queued = _expect(
        *transport.request(
            "POST", f"/api/standards/{doc_id}/requirements/extract-async"
        ),
        "queueing extraction",
    )
    state = wait_job(transport, queued.get("job_id") or "", timeout=timeout, **wait)
    if state not in OK_STATES:
        raise RunError(f"the standard's extraction ended {state}")
    return doc_id


def run_sheet(
    transport: Transport,
    entry: dict,
    folder: Path,
    *,
    timeout: float = 3600.0,
    with_standard: bool = True,
    disciplines: list[str] | None = None,
    clock: Callable[[], float] = time.monotonic,
    **wait,
) -> dict:
    """Run one sheet of the index. Always returns a record: a step that fails
    ends the sheet with `status: "error"` and the step's plain message, never
    raising past the sheet (one bad sheet must not hide the others)."""
    record = {
        "format": RECORD_FORMAT,
        "id": entry["id"],
        "equipment_type": entry.get("equipment_type"),
        "group": entry.get("group"),
        "held_out": bool(entry.get("held_out")),
        "review_run_id": None,
        "job_state": None,
        "status": "error",
        "minutes": None,
        "error": None,
    }
    started = clock()
    wait = {**wait, "clock": clock}
    try:
        if with_standard and entry.get("standard"):
            prepare_standard(
                transport,
                folder / entry["standard"],
                timeout=timeout,
                disciplines=disciplines,
                number=entry.get("standard_number"),
                **wait,
            )
        sheet_id, job_id = upload(transport, folder / entry["datasheet"], disciplines)
        state = wait_job(transport, job_id, timeout=timeout, **wait)
        if state not in OK_STATES:
            raise RunError(f"the sheet's ingestion ended {state}")
        # The client workflow marks the file as a contractor submittal (the
        # app's own step); the READY and role-change hooks then fill its
        # equipment type, title and discipline. Without it a review reads a
        # sheet that does not say what it is (order 206.1).
        _expect(
            *transport.request(
                "POST",
                "/api/documents/bulk/role",
                {"document_ids": [sheet_id], "document_role": "CONTRACTOR_SUBMITTAL"},
            ),
            "marking the sheet as a contractor submittal",
            ok=(200, 207),
        )
        run = _expect(
            *transport.request(
                "POST", "/api/reviews/run", {"submittal_document_id": sheet_id}
            ),
            "starting the review",
        )
        record["review_run_id"] = run.get("review_run_id")
        review_job = (run.get("job") or {}).get("id") or ""
        record["job_state"] = wait_job(transport, review_job, timeout=timeout, **wait)
        record["status"] = (
            "completed" if record["job_state"] in OK_STATES else "not_completed"
        )
    except RunError as exc:
        record["error"] = str(exc)
    except (OSError, urllib.error.URLError) as exc:
        record["error"] = f"the server could not be reached ({type(exc).__name__})"
    record["minutes"] = round((clock() - started) / 60, 2)
    return record


def run_set(
    transport: Transport,
    index: dict,
    folder: Path,
    out: Path,
    *,
    include_held_out: bool = False,
    only: list[str] | None = None,
    **options,
) -> list[dict]:
    """Run the sheets of `index` (not the held-out ones unless asked) and write
    `<id>.run.json` and `run-index.json` under `out`. Returns the records."""
    assert_test_database(transport)
    out.mkdir(parents=True, exist_ok=True)
    records = []
    for entry in index["documents"]:
        if entry.get("held_out") and not include_held_out:
            continue
        if only and entry["id"] not in only:
            continue
        record = run_sheet(transport, entry, folder, **options)
        (out / f"{entry['id']}.run.json").write_text(
            json.dumps(record, indent=2) + "\n", encoding="utf-8"
        )
        records.append(record)
    (out / "run-index.json").write_text(
        json.dumps({"format": RECORD_FORMAT, "runs": records}, indent=2) + "\n",
        encoding="utf-8",
    )
    return records


def summary(records: list[dict]) -> dict:
    """Counts only: what may be posted."""
    return {
        "sheets": len(records),
        "completed": sum(1 for r in records if r["status"] == "completed"),
        "not_completed": sum(1 for r in records if r["status"] == "not_completed"),
        "errors": sum(1 for r in records if r["status"] == "error"),
        "minutes": round(sum(r["minutes"] or 0 for r in records), 1),
    }
