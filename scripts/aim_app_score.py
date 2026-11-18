"""Drive the ONE Review button over HTTP for planted copies, exactly as a user does (DONE-MEANS checks 1 and 2). It never scores.

    python scripts/aim_app_score.py run --base-url http://127.0.0.1:<port> --token-file <file> \\
        --copies-dir <AIM>/copies --orig-dir <AIM>/src --papers pump valve vessel hazop contract \\
        --copies A B C orig --out <order14>/BUILD/score/new [--max-usd-total 15]
    python scripts/aim_app_score.py run --old-engine ...  --out <order14>/BUILD/score/old     (copy started with the old engine on)

For each file, one after another: POST /api/documents (upload) -> wait until read -> GET /api/reviews/plan (engine: automatic, or
claude for the papers DONE-MEANS names, or --engine paper=choice) -> POST /api/reviews/start with shown_document_ids = the plan's
documents.leaving ids -> poll the run -> save the listing and the sheet.
  * new method: GET /api/reviews/papers/{id}/general?run_id= -> <paper>-<copy>-general.json (whole answer) and
    <paper>-<copy>-comments.json ({"comments": [...]}, the keys the score command reads); GET .../general/sheet -> <paper>-<copy>-sheet.xlsx
  * --old-engine: GET /api/reviews/papers/{id}/points -> <paper>-<copy>-comments.json; GET .../crs?copy=team -> <paper>-<copy>-team-crs.xlsx
  * always <paper>-<copy>-run.json: ids, counts, labels, seconds, USD and the app's own fixed words (never document text).
The original paper is the copy "orig": its file is <orig-dir>/<paper>.<ext>; the score command uses its review as the control.

Safety: HTTP only, to this machine only (127.0.0.1 or ::1), never through a proxy. The bearer token is read from a file; it is never
printed, logged or written. One review at a time. MONEY: before each start, the USD already spent by the reviews in --out (their
run files) plus the plan's worst case ("cost.at_most_usd", or --assume-usd when the plan gives none) must stay within
--max-usd-total, otherwise it stops (exit 3) before starting. Resumable: a copy whose run file exists is skipped (--redo to run it
again). It never opens a folder named "keys" and never writes inside this repository (the saved comments hold document text).
Exit: 0 every file reviewed and saved; 1 a file stopped, failed, was refused or could not be read (NOT MEASURED); 2 refused to
start; 3 stopped by the money cap.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parents[1]
LOCAL_HOSTS = {"127.0.0.1", "::1"}
PAPERS = ("pump", "valve", "vessel", "hazop", "contract")
COPIES = ("A", "B", "C", "orig")
#: DONE-MEANS check 1: automatic for datasheets, claude for the HAZOP and the contract.
ENGINE_BY_PAPER = {"hazop": "claude", "contract": "claude"}
EXTENSIONS = (".pdf", ".docx", ".doc", ".xlsx")
INGEST_DONE = (
    "ready",
    "partially_searchable",
    "no_searchable_content",
    "stored_not_indexed",
    "failed",
)
INGEST_OK = ("ready", "partially_searchable")
RUN_DONE = ("completed", "failed", "cancelled", "stopped", "done")
WORD_LIMIT = 300  # a sentence the app wrote is kept to this many characters


class Refused(Exception):
    """The driver will not start (bad input); exit 2."""


class Stop(Exception):
    """A step failed for one file: its words go to the run file (never document text)."""


def log(msg: str) -> None:
    now = datetime.now(ZoneInfo("Asia/Karachi")).strftime("%H:%M:%S PKT")
    print(f"{now} | {msg}", flush=True)


def words(value) -> str | None:
    return value[:WORD_LIMIT] if isinstance(value, str) and value else None


def app_sentence(body) -> str | None:
    """The app's own refusal sentence from an error body ({"detail": {"message": ...}} or {"detail": "..."})."""
    if not isinstance(body, dict):
        return None
    detail = body.get("detail")
    if isinstance(detail, dict):
        return words(detail.get("message") or detail.get("sentence"))
    return words(detail)


# ------------------------------------------------------------------------------------------------ HTTP


class Client:
    """The app's routes with a bearer token, to this machine only, never through a proxy. Errors name the route and the status."""

    def __init__(self, base_url: str, token: str, timeout: float = 600.0):
        parts = urllib.parse.urlsplit(base_url)
        if parts.scheme != "http" or (parts.hostname or "") not in LOCAL_HOSTS:
            raise Refused(
                "the base URL must be this machine: http://127.0.0.1:<port> (or http://[::1]:<port>)"
            )
        if not token:
            raise Refused("the token file is empty")
        self.base = base_url.rstrip("/")
        self._token = token
        self.timeout = timeout
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def __repr__(self) -> str:  # never the token
        return f"Client({self.base})"

    def call(
        self,
        method: str,
        path: str,
        *,
        params=None,
        body: bytes | None = None,
        content_type: str | None = None,
    ):
        """(status, raw bytes). A refused connection is status 0."""
        url = (
            self.base
            + path
            + (("?" + urllib.parse.urlencode(params, doseq=True)) if params else "")
        )
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }
        if content_type:
            headers["Content-Type"] = content_type
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()
        except (urllib.error.URLError, TimeoutError, OSError):
            return 0, b""

    def json(self, method: str, path: str, *, params=None, payload=None):
        body = json.dumps(payload).encode() if payload is not None else None
        code, raw = self.call(
            method,
            path,
            params=params,
            body=body,
            content_type="application/json" if body is not None else None,
        )
        try:
            data = json.loads(raw) if raw else None
        except ValueError:
            data = None
        return code, data

    def upload(self, path: Path, filename: str, disciplines: list[str] | None = None):
        """POST /api/documents as the upload screen does: the file and the disciplines it is visible to (signed in, the
        app asks for at least one; the screen offers the uploader's own as the default)."""
        boundary = "aimF" + uuid.uuid4().hex
        parts = b"".join(
            f'--{boundary}\r\nContent-Disposition: form-data; name="disciplines"\r\n\r\n{d}\r\n'.encode()
            for d in disciplines or []
        )
        head = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
        body = parts + head + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
        code, raw = self.call(
            "POST",
            "/api/documents",
            body=body,
            content_type=f"multipart/form-data; boundary={boundary}",
        )
        try:
            return code, json.loads(raw) if raw else {}
        except ValueError:
            return code, {}


# ------------------------------------------------------------------------------------------------ inputs and money


def read_token(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise Refused(f"the token file cannot be read ({type(exc).__name__})") from exc


def no_keys(*paths: Path) -> None:
    for p in paths:
        if any(part.lower() == "keys" for part in p.resolve().parts):
            raise Refused(
                "this driver never opens a folder named 'keys' (the answer keys are the test owner's)"
            )


def outside_repo(out: Path) -> None:
    out = out.resolve()
    if out == REPO or REPO in out.parents:
        raise Refused(
            "--out must be outside this repository: the saved comments hold document text"
        )


def find_file(
    copies_dir: Path, orig_dir: Path | None, paper: str, copy: str
) -> Path | None:
    folder, stem = (
        (orig_dir, paper) if copy == "orig" else (copies_dir, f"{paper}-{copy}")
    )
    if folder is None:
        return None
    for ext in EXTENSIONS:
        p = folder / f"{stem}{ext}"
        if p.is_file():
            return p
    return None


def parse_engines(items: list[str]) -> dict[str, str]:
    out = dict(ENGINE_BY_PAPER)
    for item in items or []:
        paper, sep, engine = item.partition("=")
        if not sep or engine not in ("automatic", "claude", "local"):
            raise Refused(
                f"--engine must be <paper>=automatic|claude|local, got {item!r}"
            )
        out[paper.strip()] = engine
    return out


def spent_so_far(out: Path) -> float:
    """USD of the reviews already in --out: each run file's USD, or its plan's worst case when the app gave none."""
    total = 0.0
    for f in sorted(out.glob("*-run.json")):
        with contextlib.suppress(OSError, ValueError, TypeError, AttributeError):
            rec = json.loads(f.read_text(encoding="utf-8"))
            usd = rec.get("usd")
            if usd is None and rec.get("started"):
                usd = (rec.get("plan") or {}).get("at_most_usd")
            total += float(usd or 0)
    return round(total, 6)


# ------------------------------------------------------------------------------------------------ one file


def upload_disciplines(c: Client, chosen: list[str]) -> list[str]:
    """The disciplines the upload is made visible to: --discipline when given, else the upload screen's default
    (GET /api/documents/upload-disciplines). Signed in with no default and none given: Stop (NOT MEASURED), never a guess."""
    if chosen:
        return list(chosen)
    code, body = c.json("GET", "/api/documents/upload-disciplines")
    if code != 200 or not isinstance(body, dict):
        raise Stop(f"GET /api/documents/upload-disciplines: HTTP {code}")
    default = [str(d) for d in body.get("default") or []]
    if body.get("required") and not default:
        raise Stop(
            "the upload needs a discipline and the uploader has none of its own: give --discipline"
        )
    return default


def wait_read(c: Client, doc: str, timeout: float, poll: float) -> str:
    end, status = time.time() + timeout, "unknown"
    while time.time() < end:
        code, body = c.json("GET", f"/api/documents/{urllib.parse.quote(doc, safe='')}")
        if code == 200 and isinstance(body, dict):
            status = str(body.get("status"))
            if status in INGEST_DONE:
                return status
        time.sleep(poll)
    return f"timeout (last status {status})"


def wait_run(
    c: Client,
    path: str,
    params: dict | None,
    timeout: float,
    poll: float,
    history: tuple[str, str] | None = None,
    on_poll=None,
) -> tuple[str, dict | None]:
    """Poll a route whose answer has a 'status' until it is final; any other answer (404, the general page's 409 "not
    finished") means 'not there yet'. With `history` = (paper id, run id): while the route is not there, the paper's history
    is read too, and a run it lists as failed or cancelled ends the wait at once (a failed run with nothing stored never
    gets a page). `on_poll(status)` is called at every poll with the status THE APP gives (the route's, else the history's),
    so the caller's run file always shows the app's state, never a local guess."""
    end, status = time.time() + timeout, "unknown"
    while time.time() < end:
        code, body = c.json("GET", path, params=params)
        app = history_status(c, *history) if history else None
        if code == 200 and isinstance(body, dict):
            status = str(body.get("status"))
        elif app:
            status = app
        if on_poll is not None:
            on_poll(status)
        if code == 200 and isinstance(body, dict) and status in RUN_DONE:
            return status, body
        if app in ("failed", "cancelled"):
            return app, None
        time.sleep(poll)
    return f"timeout (last status {status})", None


def history_status(c: Client, doc: str, run_id: str) -> str | None:
    """The status word GET /api/reviews/papers/{id}/history gives this run, or None."""
    code, body = c.json(
        "GET", f"/api/reviews/papers/{urllib.parse.quote(doc, safe='')}/history"
    )
    if code != 200 or not isinstance(body, dict):
        return None
    for r in body.get("runs") or []:
        if isinstance(r, dict) and r.get("run_id") == run_id:
            return str(r.get("status") or "")
    return None


def xlsx_rows(blob: bytes, sheet: str | None) -> int | None:
    """Rows under the table's header row of one sheet. The header row is the first row with three or more filled cells
    (the mark and title rows above it fill one cell each). None when it cannot be read or has no such row."""
    try:
        import io

        import openpyxl

        wb = openpyxl.load_workbook(io.BytesIO(blob), read_only=True, data_only=True)
        if sheet is None:
            ws = wb.worksheets[0]
        elif sheet in wb.sheetnames:
            ws = wb[sheet]
        else:
            return None
        rows = [
            sum(1 for v in row if v not in (None, ""))
            for row in ws.iter_rows(values_only=True)
        ]
        head = next((i for i, n in enumerate(rows) if n >= 3), None)
        if head is None:
            return None
        return sum(1 for n in rows[head + 1 :] if n > 0)
    except Exception:  # noqa: BLE001 - an unreadable file is NOT MEASURED, said in the record
        return None


def by_label(lines) -> dict[str, int]:
    out: dict[str, int] = {}
    for line in lines or []:
        if isinstance(line, dict):
            key = str(
                line.get("shown_label") or line.get("label") or line.get("pill") or ""
            )
            out[key] = out.get(key, 0) + 1
    return out


def fetch_general(
    c: Client, out: Path, label: str, doc: str, run_id: str, rec: dict
) -> None:
    q = urllib.parse.quote(doc, safe="")
    code, page = c.json(
        "GET", f"/api/reviews/papers/{q}/general", params={"run_id": run_id}
    )
    if code != 200 or not isinstance(page, dict):
        raise Stop(f"GET /api/reviews/papers/{{id}}/general: HTTP {code}")
    comments = page.get("comments") if isinstance(page.get("comments"), list) else None
    points = page.get("points") if isinstance(page.get("points"), list) else None
    (out / f"{label}-general.json").write_text(
        json.dumps(page, indent=1), encoding="utf-8"
    )
    if (
        comments is not None
    ):  # only the comments: the score command reads {"comments": [{field, page, label, comment, quote}]}
        (out / f"{label}-comments.json").write_text(
            json.dumps(
                {"run_id": run_id, "paper_document_id": doc, "comments": comments},
                indent=1,
            ),
            encoding="utf-8",
        )
    counts = page.get("counts") or {}
    rec.update(
        {
            "points": len(points) if points is not None else None,
            "comments": len(comments) if comments is not None else None,
            "points_counted_by_app": counts.get("points"),
            "comments_counted_by_app": counts.get("comments"),
            "by_label": by_label(points),
            "by_label_comments": by_label(comments),
            "mark": words(page.get("mark")),
            "method": words(page.get("method")),
            "completeness": {
                k: (page.get("completeness") or {}).get(k)
                for k in ("ok", "page", "database", "file_rows")
            },
            "completeness_sentence": words(
                (page.get("completeness") or {}).get("sentence")
            ),
            "unlisted_books": (page.get("unlisted_books") or {}).get("count"),
            "unlisted_sentence": words(
                (page.get("unlisted_books") or {}).get("sentence")
            ),
            "books": len(page.get("books") or []),
            "not_held": len(page.get("not_held") or []),
        }
    )
    usd = (page.get("cost") or {}).get("usd")
    rec["usd"], rec["usd_basis"] = (
        (float(usd), "the run's own stored cost (general page)")
        if usd is not None
        else (None, "not given")
    )
    code, blob = c.call(
        "GET",
        f"/api/reviews/papers/{q}/general/sheet",
        params={"run_id": run_id, "copy": "team"},
    )
    if code == 200 and blob[:2] == b"PK":
        (out / f"{label}-sheet.xlsx").write_bytes(blob)
        rec["rows_in_file"] = xlsx_rows(blob, "All points")
        rec["comment_rows_in_file"] = xlsx_rows(blob, "Comments")
    else:
        rec["rows_in_file"] = None
        rec["sheet_refused"] = {"http": code}


def fetch_old(
    c: Client, out: Path, label: str, doc: str, ai_run: str | None, rec: dict
) -> None:
    q = urllib.parse.quote(doc, safe="")
    code, listing = c.json("GET", f"/api/reviews/papers/{q}/points")
    if code != 200 or not isinstance(listing, dict):
        raise Stop(f"GET /api/reviews/papers/{{id}}/points: HTTP {code}")
    (out / f"{label}-comments.json").write_text(
        json.dumps(listing, indent=1), encoding="utf-8"
    )
    points = listing.get("points") if isinstance(listing.get("points"), list) else None
    rec.update(
        {
            "points": listing.get("of")
            if isinstance(listing.get("of"), int)
            else (len(points) if points is not None else None),
            "comments": listing.get("comment_count"),
            "by_label": by_label(points),
            "runs_on_page": listing.get("runs"),
        }
    )
    code, blob = c.call("GET", f"/api/reviews/papers/{q}/crs", params={"copy": "team"})
    if code == 200 and blob[:2] == b"PK":
        (out / f"{label}-team-crs.xlsx").write_bytes(blob)
    code, check = c.json("GET", f"/api/reviews/papers/{q}/crs/check")
    team = (
        (check or {}).get("team") if code == 200 and isinstance(check, dict) else None
    )
    rec["rows_in_file"] = (team or {}).get("rows_in_file")
    rec["completeness"] = {
        k: (team or {}).get(k) for k in ("ok", "page", "rows_in_file")
    }
    rec["usd"], rec["usd_basis"] = None, "not given"
    if ai_run:
        code, summary = c.json(
            "GET",
            f"/api/reviews/runs/{urllib.parse.quote(ai_run, safe='')}/agent/summary",
        )
        if code == 200 and isinstance(summary, dict) and summary.get("usd") is not None:
            rec["usd"] = float(summary["usd"])
            rec["usd_basis"] = (
                "the AI review's stored cost only (the rule check's Claude steps are in the copy's ledger)"
            )


def review_one(c: Client, a, paper: str, copy: str, path: Path, engine: str) -> dict:
    label = f"{paper}-{copy}"
    out = Path(a.out)
    rec: dict = {
        "label": label,
        "paper": paper,
        "copy": copy,
        "mode": "old engine" if a.old_engine else "general",
        "engine": engine,
        "status": "not started",
        "started": False,
        "usd": None,
    }
    t0 = time.time()
    try:
        disciplines = upload_disciplines(c, a.discipline)
        rec["disciplines"] = len(disciplines)
        code, up = c.upload(path, path.name, disciplines)
        doc = ((up.get("document") or {}).get("id")) or up.get("duplicate_of")
        if code != 200 or not doc:
            raise Stop(
                f"upload: HTTP {code}"
                + (f" ({app_sentence(up)})" if app_sentence(up) else "")
            )
        rec["document_id"], rec["duplicate_of_held"] = doc, bool(up.get("duplicate_of"))
        read = wait_read(c, doc, a.ingest_timeout, a.poll)
        rec["read_status"] = read
        if read not in INGEST_OK:
            raise Stop(f"the paper was not read ({read})")
        code, plan = c.json(
            "GET",
            "/api/reviews/plan",
            params={"submittal_document_id": doc, "engine": engine},
        )
        if code != 200 or not isinstance(plan, dict):
            raise Stop(f"GET /api/reviews/plan: HTTP {code}")
        leaving = [
            d.get("id")
            for d in ((plan.get("documents") or {}).get("leaving") or [])
            if isinstance(d, dict)
        ]
        rec["plan"] = {
            "method": plan.get("method"),
            "text_leaves": plan.get("text_leaves"),
            "at_most_usd": (plan.get("cost") or {}).get("at_most_usd"),
            "documents_leaving": len(leaving),
            "paper_on_list": doc in leaving,
            "refused_code": plan.get("refused_code"),
            "parts": {
                p.get("name"): p.get("engine")
                for p in plan.get("parts") or []
                if isinstance(p, dict)
            },
        }
        want = "earlier" if a.old_engine else "general"
        if plan.get("method", "earlier") != want:
            raise Stop(
                f"the plan names the method {plan.get('method')!r}, this run measures {want!r}"
            )
        if plan.get("refused_code"):
            rec.update(
                status="refused",
                words=words(
                    plan.get("refused")
                    or plan.get("refused_words")
                    or plan.get("sentence")
                ),
            )
            return rec
        worst = rec["plan"]["at_most_usd"]
        worst = (
            float(worst)
            if worst is not None
            else (a.assume_usd if plan.get("text_leaves", True) else 0.0)
        )
        spent = spent_so_far(out)
        if spent + worst > a.max_usd_total + 1e-9:
            rec["status"] = "money stop"
            raise MoneyStop(
                f"spent USD {spent:.2f} + this review's worst case USD {worst:.2f} would pass the cap USD "
                f"{a.max_usd_total:.2f}: stopped before starting {label}"
            )
        before = None
        if a.old_engine:
            _code, listing = c.json(
                "GET", f"/api/reviews/papers/{urllib.parse.quote(doc, safe='')}/points"
            )
            before = (
                ((listing or {}).get("runs") or {}).get("ai_review")
                if isinstance(listing, dict)
                else None
            )
        code, started = c.json(
            "POST",
            "/api/reviews/start",
            payload={
                "submittal_document_id": doc,
                "engine": engine,
                "shown_document_ids": leaving,
            },
        )
        if code != 200 or not isinstance(started, dict):
            if code == 409:
                rec.update(
                    status="refused",
                    words=app_sentence(started),
                    refused_code=(started or {}).get("detail", {}).get("code")
                    if isinstance((started or {}).get("detail"), dict)
                    else None,
                )
                return rec
            raise Stop(f"POST /api/reviews/start: HTTP {code}")
        run_id = started.get("review_run_id") or started.get("run_id")
        rec["run_id"], rec["started"] = run_id, True

        def app_says(status: str) -> None:
            """The run file shows the state the APP gives (its run row, read through its routes), with the time it was read."""
            rec["status"] = status
            rec["status_source"] = (
                "the app (run status route / the paper's history route)"
            )
            rec["status_read_at"] = datetime.now(ZoneInfo("Asia/Karachi")).strftime(
                "%H:%M:%S PKT"
            )
            _write(out, rec)

        if a.old_engine:
            app_says("started (the app's run status is read at the next poll)")
        else:
            app_says(
                history_status(c, doc, run_id)
                or "started (the app does not list it in the history yet)"
            )
        # a crash after this point still counts this review's worst case in the money check (the run file says started)
        q = urllib.parse.quote(doc, safe="")
        if a.old_engine:
            status, _ = wait_run(
                c,
                f"/api/reviews/runs/{urllib.parse.quote(run_id, safe='')}",
                None,
                a.timeout,
                a.poll,
                on_poll=app_says,
            )
            rec["rule_check_status"] = status
            ai_run = None
            if (
                rec["plan"]["parts"].get("ai_review", "not_run") != "not_run"
                and status == "completed"
            ):
                end = time.time() + a.timeout
                while time.time() < end and ai_run is None:
                    _code, listing = c.json("GET", f"/api/reviews/papers/{q}/points")
                    now = (
                        ((listing or {}).get("runs") or {}).get("ai_review")
                        if isinstance(listing, dict)
                        else None
                    )
                    ai_run = now if now and now != before else None
                    if ai_run is None:
                        time.sleep(a.poll)
                rec["ai_run_id"] = ai_run
                status = (
                    wait_run(
                        c,
                        f"/api/reviews/runs/{urllib.parse.quote(ai_run, safe='')}",
                        None,
                        a.timeout,
                        a.poll,
                    )[0]
                    if ai_run
                    else "no AI review followed"
                )
            rec["status"] = status
            fetch_old(c, out, label, doc, ai_run, rec)
        else:
            status, _ = wait_run(
                c,
                f"/api/reviews/papers/{q}/general",
                {"run_id": run_id},
                a.timeout,
                a.poll,
                history=(doc, run_id),
                on_poll=app_says,
            )
            rec["status"] = status
            rec["app_status_final"] = history_status(
                c, doc, run_id
            )  # the app's run row at the end, kept beside the page's word
            if status in ("failed", "cancelled"):
                raise Stop(f"the review {status} (the paper's history says so)")
            fetch_general(c, out, label, doc, run_id, rec)
    except Stop as exc:
        rec["status"] = (
            rec["status"] if rec["status"] not in ("not started",) else "not measured"
        )
        rec["words"] = str(exc)
    finally:
        rec["seconds"] = round(time.time() - t0, 1)
    return rec


class MoneyStop(Exception):
    """The next review could pass --max-usd-total: stop before starting it (exit 3)."""


def _write(out: Path, rec: dict) -> None:
    (out / f"{rec['label']}-run.json").write_text(
        json.dumps(rec, indent=1, sort_keys=True), encoding="utf-8"
    )


def _show(v) -> str:
    return "NOT MEASURED" if v is None else str(v)


def measured(rec: dict) -> bool:
    """A review counts only when it finished and its comments could be read. 0 comments is NOT MEASURED, never 0 found."""
    return (
        rec.get("status") in ("completed", "done")
        and isinstance(rec.get("comments"), int)
        and rec["comments"] > 0
    )


def line_of(rec: dict) -> str:
    usd = rec.get("usd")
    return (
        f"{rec['label']:12} run {_show(rec.get('run_id'))}  {rec.get('status')}  {rec.get('seconds', 0)} s  "
        f"USD {_show(None if usd is None else round(usd, 4))}  points {_show(rec.get('points'))}  "
        f"comments {_show(rec.get('comments'))}  rows in file {_show(rec.get('rows_in_file'))}"
        + (
            ""
            if measured(rec)
            else f"  NOT MEASURED{': ' + rec['words'] if rec.get('words') else ''}"
        )
    )


# ------------------------------------------------------------------------------------------------ the command


def cmd_run(a) -> int:
    out = Path(a.out)
    copies_dir = Path(a.copies_dir)
    orig_dir = Path(a.orig_dir) if a.orig_dir else None
    no_keys(copies_dir, out, *([orig_dir] if orig_dir else []))
    outside_repo(out)
    engines = parse_engines(a.engine)
    c = Client(a.base_url, read_token(a.token_file))
    out.mkdir(parents=True, exist_ok=True)
    code, method = c.json("GET", "/api/reviews/method")
    said = (
        (method or {}).get("method")
        if code == 200 and isinstance(method, dict)
        else None
    )
    if a.old_engine and said == "general":
        raise Refused(
            "the app runs the general review: start the copy with REVIEW_OLD_ENGINE_ENABLED=true to measure the old engine"
        )
    if not a.old_engine and said != "general":
        raise Refused(
            f"the app does not say it runs the general review (GET /api/reviews/method: HTTP {code}, method {said!r})"
        )
    log(
        f"mode {'old engine' if a.old_engine else 'general'}; cap USD {a.max_usd_total:.2f}; already spent in --out USD "
        f"{spent_so_far(out):.2f}"
    )
    records, rc = [], 0
    for paper in a.papers:
        for copy in a.copies:
            label = f"{paper}-{copy}"
            done = out / f"{label}-run.json"
            if done.exists() and label not in (a.redo or []):
                with contextlib.suppress(OSError, ValueError):
                    rec = json.loads(done.read_text(encoding="utf-8"))
                    # a review that started (it may have cost money) or that the app refused is kept; one that never
                    # started (an upload or a read that failed: nothing was spent) is tried again
                    if rec.get("started") or rec.get("status") == "refused":
                        records.append(rec)
                        log(f"skip (already in --out): {line_of(rec)}")
                        continue
                    log(
                        f"again (it never started: {rec.get('words') or rec.get('status')}): {label}"
                    )
            path = find_file(copies_dir, orig_dir, paper, copy)
            if path is None:
                rec = {
                    "label": label,
                    "paper": paper,
                    "copy": copy,
                    "status": "not measured",
                    "words": "no file for this copy",
                }
                records.append(rec)
                log(line_of(rec))
                continue
            try:
                rec = review_one(
                    c, a, paper, copy, path, engines.get(paper, "automatic")
                )
            except MoneyStop as exc:
                log(f"STOPPED: {exc}")
                rc = 3
                break
            _write(out, rec)
            records.append(rec)
            log(line_of(rec))
        if rc == 3:
            break
    summary = {
        "mode": "old engine" if a.old_engine else "general",
        "cap_usd": a.max_usd_total,
        "spent_usd": spent_so_far(out),
        "files": [
            {
                k: r.get(k)
                for k in (
                    "label",
                    "run_id",
                    "status",
                    "seconds",
                    "usd",
                    "points",
                    "comments",
                    "rows_in_file",
                )
            }
            for r in records
        ],
    }
    (out / "RUNS.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    log(
        f"spent in --out: USD {summary['spent_usd']:.2f} of cap {a.max_usd_total:.2f}; ready to score: "
        f"{sum(1 for r in records if measured(r))} of {len(records)} files"
    )
    if rc:
        return rc
    return 0 if records and all(measured(r) for r in records) else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser(
        "run",
        help="review each copy through the app's HTTP routes and save the listings",
    )
    r.add_argument("--base-url", required=True)
    r.add_argument(
        "--token-file",
        required=True,
        help="a file holding a bearer token (never a password)",
    )
    r.add_argument("--copies-dir", required=True, help="<paper>-<copy>.pdf|docx")
    r.add_argument(
        "--orig-dir",
        default=None,
        help="<paper>.pdf|docx: the original papers (copy 'orig')",
    )
    r.add_argument("--papers", nargs="+", default=list(PAPERS))
    r.add_argument("--copies", nargs="+", default=list(COPIES))
    r.add_argument("--out", required=True)
    r.add_argument(
        "--old-engine",
        action="store_true",
        help="measure the old engine (the copy runs with it on)",
    )
    r.add_argument(
        "--engine",
        action="append",
        default=[],
        metavar="PAPER=CHOICE",
        help="override the Review button choice for one paper (default: automatic; claude for hazop and contract)",
    )
    r.add_argument("--max-usd-total", type=float, default=15.0)
    r.add_argument(
        "--assume-usd",
        type=float,
        default=5.0,
        help="worst case of a review whose plan gives no cost",
    )
    r.add_argument("--redo", nargs="*", default=[], metavar="PAPER-COPY")
    r.add_argument(
        "--discipline",
        action="append",
        default=[],
        metavar="NAME",
        help="who may read the upload (default: what the upload screen offers, the uploader's own disciplines)",
    )
    r.add_argument("--timeout", type=float, default=3600.0, help="per review")
    r.add_argument("--ingest-timeout", type=float, default=1800.0)
    r.add_argument("--poll", type=float, default=5.0)
    a = ap.parse_args(argv)
    try:
        return cmd_run(a)
    except Refused as exc:
        print(f"REFUSED: {exc}", flush=True)
        return 2


if __name__ == "__main__":
    sys.exit(main())
