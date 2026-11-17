"""The app-path score driver and the done-gate (CONTRACT section F; DONE-MEANS checks 0 to 3).

The driver is tested against a FAKE app on 127.0.0.1 (invented ids and words, no document text): upload -> plan -> start -> poll ->
listing -> sheet, the money stop, resume, NOT MEASURED, the local-only and keys refusals, and that the token is never printed or
written. The gate is tested on forged score outputs: it fails on NOT MEASURED, on a mean of 6.9, on old >= new and on 11% WRONG."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


driver = _load("aim_app_score")
gate = _load("aim_done_gate")

TOKEN = "invented-test-token"


def _xlsx(sheets: dict[str, int]) -> bytes:
    import openpyxl

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        ws.append(
            ["AI, to be checked"]
        )  # the app's sheets: mark row, title row, a statement, then the table
        ws.append([f"{name}: invented title"])
        ws.append([f"{rows} points reviewed, {rows} in this file"])
        ws.append(["n", "field", "label"])
        for i in range(rows):
            ws.append([i + 1, f"field {i + 1}", "Question"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class FakeApp:
    """A tiny stand-in for the app's review routes. `comments` per upload; `method` for /api/reviews/method."""

    def __init__(
        self, method="general", comments=3, at_most=5.0, usd=0.5, plan_refused=None
    ):
        self.method, self.comments, self.at_most, self.usd, self.plan_refused = (
            method,
            comments,
            at_most,
            usd,
            plan_refused,
        )
        self.requests: list[tuple[str, str, str]] = []  # (method, path, authorization)
        self.starts: list[dict] = []
        self.fail_runs = False
        self.default_disc: list[str] = ["Invented-A"]
        self.upload_bodies: list[
            bytes
        ] = []  # a run that fails with nothing stored: the page stays 409, the history says failed
        self.uploads = 0
        self.polls: dict[str, int] = {}
        self.lock = threading.Lock()

    def lines(self, n):
        return [
            {
                "n": i + 1,
                "field": f"invented field {i}",
                "page": 1,
                "label": "Question",
                "shown_label": "Question",
                "comment": "invented comment",
                "quote": "invented quote",
            }
            for i in range(n)
        ]

    def handle(self, h: BaseHTTPRequestHandler, verb: str):
        url = urllib.parse.urlsplit(h.path)
        q = dict(urllib.parse.parse_qsl(url.query))
        p = url.path
        with self.lock:
            self.requests.append((verb, p, h.headers.get("Authorization", "")))
        if h.headers.get("Authorization") != f"Bearer {TOKEN}":
            return 401, {"detail": "no"}
        size = int(h.headers.get("Content-Length") or 0)
        body = h.rfile.read(size) if size else b""
        if p == "/api/reviews/method":
            if self.method is None:
                return 404, {"detail": "Not Found"}
            return 200, {
                "method": self.method,
                "old_engine": self.method == "earlier",
                "local_available": False,
                "mark": "AI, to be checked",
            }
        if p == "/api/documents/upload-disciplines":
            return 200, {
                "required": True,
                "choices": ["Invented-A", "Invented-B"],
                "default": self.default_disc,
            }
        if p == "/api/documents" and verb == "POST":
            assert b"filename=" in body
            self.upload_bodies.append(body[:400])
            if (
                b'name="disciplines"' not in body
            ):  # signed in: the app asks for at least one discipline
                return 422, {"detail": {"message": "choose at least one discipline"}}
            with self.lock:
                self.uploads += 1
                n = self.uploads
            return 200, {"document": {"id": f"doc_fake_{n}"}, "job_id": "job"}
        if p.startswith("/api/documents/"):
            return 200, {"status": "ready"}
        if p == "/api/reviews/plan":
            doc = q["submittal_document_id"]
            plan = {
                "choice": q.get("engine"),
                "text_leaves": True,
                "cost": {"at_most_usd": self.at_most},
                "documents": {"leaving": [{"id": doc}, {"id": "doc_book_invented"}]},
                "parts": [
                    {"name": "rule_check", "engine": "not_run"},
                    {"name": "ai_review", "engine": "claude"},
                ],
            }
            if self.method is not None:
                plan["method"] = self.method
            if self.plan_refused:
                plan["refused_code"], plan["refused"] = self.plan_refused
            return 200, plan
        if p == "/api/reviews/start" and verb == "POST":
            data = json.loads(body)
            self.starts.append(data)
            return 200, {"review_run_id": f"run_{data['submittal_document_id']}"}
        parts = p.split("/")
        if p.startswith("/api/reviews/papers/") and p.endswith("/general"):
            run = q.get("run_id")
            self.polls[run] = self.polls.get(run, 0) + 1
            if (
                self.fail_runs or self.polls[run] < 2
            ):  # the app's page: 409 "not finished" while queued or running
                return 409, {"detail": {"message": "not finished"}}
            lines = self.lines(self.comments)
            return 200, {
                "run_id": run,
                "status": "completed",
                "method": "aim-1",
                "mark": "AI, to be checked",
                "counts": {"points": len(lines) + 2, "comments": len(lines)},
                "comments": lines,
                "points": lines + self.lines(2),
                "cost": {"usd": self.usd},
                "completeness": {
                    "ok": True,
                    "page": len(lines) + 2,
                    "database": len(lines) + 2,
                    "file_rows": len(lines) + 2,
                    "sentence": None,
                },
                "unlisted_books": {"count": 0, "sentence": None},
                "books": [],
                "not_held": [],
            }
        if p.endswith("/history"):
            doc = parts[4]
            return 200, {
                "runs": [
                    {
                        "run_id": f"run_{doc}",
                        "version": "general",
                        "status": "failed" if self.fail_runs else "running",
                    }
                ]
            }
        if p.endswith("/general/sheet"):
            if q.get("copy") != "team":
                return 409, {"detail": {"message": "no contractor copy"}}
            return 200, _xlsx(
                {
                    "Summary": 1,
                    "Comments": self.comments,
                    "All points": self.comments + 2,
                }
            )
        # the old engine's routes
        if p.startswith("/api/reviews/runs/") and p.endswith("/agent/summary"):
            return 200, {"usd": 0.25}
        if p.startswith("/api/reviews/runs/"):
            return 200, {"status": "completed"}
        if p.endswith("/points"):
            doc = parts[4]
            started = any(s["submittal_document_id"] == doc for s in self.starts)
            pts = [{"name": "invented", "pill": "Question", "page": 1}] * self.comments
            return 200, {
                "points": pts,
                "of": len(pts),
                "comment_count": len(pts),
                "runs": {
                    "rule_check": f"run_{doc}" if started else None,
                    "ai_review": f"ai_{doc}" if started else None,
                },
            }
        if p.endswith("/crs"):
            return 200, _xlsx({"CRS": self.comments})
        if p.endswith("/crs/check"):
            return 200, {
                "team": {
                    "ok": True,
                    "page": self.comments,
                    "rows_in_file": self.comments,
                }
            }
        return 404, {"detail": "Not Found"}


@pytest.fixture
def app():
    fake = FakeApp()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # quiet
            pass

        def _do(self, verb):
            code, body = fake.handle(self, verb)
            raw = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            self._do("GET")

        def do_POST(self):
            self._do("POST")

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    fake.base = f"http://127.0.0.1:{srv.server_address[1]}"
    yield fake
    srv.shutdown()


@pytest.fixture
def setup(tmp_path):
    copies = tmp_path / "copies"
    copies.mkdir()
    for name in ("pump-A.pdf", "hazop-A.docx"):
        (copies / name).write_bytes(b"%PDF-invented bytes")
    orig = tmp_path / "src"
    orig.mkdir()
    (orig / "pump.pdf").write_bytes(b"%PDF-invented original")
    tok = tmp_path / "token.txt"
    tok.write_text(TOKEN + "\n", encoding="utf-8")
    return {"copies": copies, "orig": orig, "token": tok, "out": tmp_path / "out"}


def _run(app, s, *extra, papers=("pump", "hazop"), copies=("A",)):
    argv = [
        "run",
        "--base-url",
        app.base,
        "--token-file",
        str(s["token"]),
        "--copies-dir",
        str(s["copies"]),
        "--orig-dir",
        str(s["orig"]),
        "--out",
        str(s["out"]),
        "--poll",
        "0.01",
        "--timeout",
        "5",
        "--ingest-timeout",
        "5",
        "--papers",
        *papers,
        "--copies",
        *copies,
        *extra,
    ]
    return driver.main(argv)


# ------------------------------------------------------------------------------------------------ the driver


def test_driver_walks_the_users_path_and_saves_the_listing(app, setup, capsys):
    rc = _run(app, setup)
    out = capsys.readouterr().out
    assert rc == 0, out
    o = setup["out"]
    for label in ("pump-A", "hazop-A"):
        comments = json.loads((o / f"{label}-comments.json").read_text())
        assert set(comments) == {
            "run_id",
            "paper_document_id",
            "comments",
        }  # no "points": the score reads the comments only
        assert len(comments["comments"]) == 3
        assert (o / f"{label}-sheet.xlsx").read_bytes()[:2] == b"PK"
        rec = json.loads((o / f"{label}-run.json").read_text())
        assert (
            rec["status"] == "completed"
            and rec["points"] == 5
            and rec["comments"] == 3
            and rec["rows_in_file"] == 5
        )
        assert rec["usd"] == 0.5 and rec["comment_rows_in_file"] == 3
    # the order a user follows, and the plan's list is the shown list
    seen = [p for _v, p, _a in app.requests if not p.endswith("/general")]
    assert (
        seen.index("/api/documents")
        < seen.index("/api/reviews/plan")
        < seen.index("/api/reviews/start")
    )
    assert app.starts[0]["shown_document_ids"] == ["doc_fake_1", "doc_book_invented"]
    assert [s["engine"] for s in app.starts] == [
        "automatic",
        "claude",
    ]  # DONE-MEANS: claude for the HAZOP
    assert all(auth == f"Bearer {TOKEN}" for _v, _p, auth in app.requests)


def test_token_is_never_printed_or_written(app, setup, capsys):
    _run(app, setup)
    out = capsys.readouterr()
    assert TOKEN not in out.out and TOKEN not in out.err
    for f in setup["out"].iterdir():
        assert TOKEN.encode() not in f.read_bytes(), f.name


def test_money_stop_before_a_start_that_could_pass_the_cap(app, setup, capsys):
    # first review: spent 0 + worst 5 <= 5.4 -> runs and costs 0.5; second: 0.5 + 5 > 5.4 -> never started
    rc = _run(app, setup, "--max-usd-total", "5.4")
    assert rc == 3
    assert len(app.starts) == 1
    assert "STOPPED" in capsys.readouterr().out
    assert not (setup["out"] / "hazop-A-run.json").exists()


def test_money_counts_earlier_runs_in_the_out_folder(app, setup):
    setup["out"].mkdir()
    (setup["out"] / "valve-A-run.json").write_text(
        json.dumps({"label": "valve-A", "usd": 10.5, "status": "completed"})
    )
    assert _run(app, setup, "--max-usd-total", "15") == 3
    assert app.starts == []


def test_a_started_run_without_a_cost_counts_its_worst_case(app, setup):
    setup["out"].mkdir()
    (setup["out"] / "valve-A-run.json").write_text(
        json.dumps(
            {
                "label": "valve-A",
                "usd": None,
                "started": True,
                "plan": {"at_most_usd": 9.8},
            }
        )
    )
    assert driver.spent_so_far(setup["out"]) == 9.8


def test_resume_skips_copies_already_in_out(app, setup):
    assert _run(app, setup) == 0
    uploads = app.uploads
    assert _run(app, setup) == 0
    assert app.uploads == uploads  # nothing uploaded or started again
    assert _run(app, setup, "--redo", "pump-A") == 0
    assert app.uploads == uploads + 1


def test_original_paper_is_the_orig_copy(app, setup):
    assert _run(app, setup, papers=("pump",), copies=("orig",)) == 0
    assert (setup["out"] / "pump-orig-comments.json").exists()


@pytest.mark.parametrize(
    "url",
    [
        "http://10.0.0.5:8000",
        "http://example.com",
        "https://127.0.0.1:8000",
        "http://localhost.example.org:80",
    ],
)
def test_refuses_a_base_url_that_is_not_this_machine(app, setup, url, capsys):
    argv = [
        "run",
        "--base-url",
        url,
        "--token-file",
        str(setup["token"]),
        "--copies-dir",
        str(setup["copies"]),
        "--out",
        str(setup["out"]),
    ]
    assert driver.main(argv) == 2
    assert "REFUSED: the base URL must be this machine" in capsys.readouterr().out
    assert app.requests == []
    with pytest.raises(driver.Refused, match="this machine"):
        driver.Client(url, TOKEN)


def test_refuses_an_out_folder_inside_the_repository(
    app, setup, tmp_path, monkeypatch, capsys
):
    fake_repo = (
        tmp_path / "repo"
    )  # a stand-in: a broken check can never write into the real repository
    fake_repo.mkdir()
    monkeypatch.setattr(driver, "REPO", fake_repo)
    setup["out"] = fake_repo / "score"
    assert _run(app, setup) == 2
    assert "outside this repository" in capsys.readouterr().out
    assert not setup["out"].exists()
    assert driver.REPO != REPO and (REPO / "scripts" / "aim_app_score.py").exists()


def test_never_opens_a_keys_folder(app, setup, tmp_path):
    keys = tmp_path / "keys"
    keys.mkdir()
    setup["copies"] = keys
    assert _run(app, setup) == 2
    assert app.requests == []


def test_zero_comments_is_not_measured(app, setup, capsys):
    app.comments = 0
    assert _run(app, setup, papers=("pump",)) == 1
    assert "NOT MEASURED" in capsys.readouterr().out


def test_missing_file_is_not_measured(app, setup, capsys):
    assert _run(app, setup, papers=("vessel",)) == 1
    assert "NOT MEASURED: no file for this copy" in capsys.readouterr().out


def test_new_mode_refuses_an_app_that_runs_the_old_engine(app, setup):
    app.method = "earlier"
    assert _run(app, setup) == 2
    assert app.starts == []


def test_old_mode_refuses_an_app_that_runs_the_general_review(app, setup):
    assert _run(app, setup, "--old-engine") == 2
    assert app.starts == []


def test_old_engine_mode_reads_the_points_route(app, setup):
    app.method = None  # today's code: no method route, no method in the plan
    assert _run(app, setup, "--old-engine", papers=("pump",)) == 0
    o = setup["out"]
    listing = json.loads((o / "pump-A-comments.json").read_text())
    assert "points" in listing  # the score command reads the points JSON
    rec = json.loads((o / "pump-A-run.json").read_text())
    assert (
        rec["ai_run_id"] == "ai_doc_fake_1"
        and rec["usd"] == 0.25
        and rec["rows_in_file"] == 3
    )
    assert (o / "pump-A-team-crs.xlsx").exists()


def test_a_refused_plan_is_written_with_the_apps_sentence_and_starts_nothing(
    app, setup
):
    app.plan_refused = ("GENERAL_NOT_ON_LOCAL", "invented refusal sentence")
    assert _run(app, setup, papers=("pump",)) == 1
    rec = json.loads((setup["out"] / "pump-A-run.json").read_text())
    assert rec["status"] == "refused" and rec["words"] == "invented refusal sentence"
    assert app.starts == []


# ------------------------------------------------------------------------------------------------ the gate: found


TABLE_HEAD = (
    "paper    copy found by code   +confirmed possible   chance hits comments             false alarms "
    "KEEP/WEAK/WRONG"
)


def _row(paper, copy, found, chance="0 of 10", comments=30):
    f = "NOT MEASURED" if found is None else f"{found} of 10"
    return f"{paper:8} {copy:4} {f:>13} {'NOT MEASURED':>12} {0:>8} {chance:>13} {comments:>8} {'NOT MEASURED':>24} {'-':>16}"


def _score(tmp_path, name, rows):
    p = tmp_path / name
    p.write_text(
        "\n".join([TABLE_HEAD, *rows, "per-paper averages:"]) + "\n", encoding="utf-8"
    )
    return str(p)


def _found(tmp_path, new_rows, old_rows, *extra):
    return gate.main(
        [
            "found",
            "--score",
            _score(tmp_path, "new.txt", new_rows),
            "--old",
            _score(tmp_path, "old.txt", old_rows),
            "--papers",
            "pump",
            *extra,
        ]
    )


def test_found_passes_at_seven_and_above_the_old_engine(tmp_path, capsys):
    rc = _found(
        tmp_path,
        [_row("pump", c, 7) for c in "ABC"],
        [_row("pump", "A", 0), _row("pump", "B", 1)],
    )
    assert rc == 0, capsys.readouterr().out


def test_found_fails_below_seven(tmp_path):
    assert (
        _found(
            tmp_path,
            [_row("pump", "A", 7), _row("pump", "B", 7), _row("pump", "C", 6)],
            [_row("pump", "A", 0)],
        )
        == 1
    )


def test_found_fails_on_a_mean_of_six_point_nine():
    ok, _why = gate.paper_verdict([7] * 9 + [6], [0], 7.0)
    assert not ok
    ok, _why = gate.paper_verdict([7] * 10, [0], 7.0)
    assert ok


def test_found_subtracts_chance_hits(tmp_path):
    rows = [
        _row("pump", "A", 7),
        _row("pump", "B", 7),
        _row("pump", "C", 7, chance="1 of 10"),
    ]
    assert _found(tmp_path, rows, [_row("pump", "A", 0)]) == 1


def test_found_fails_when_old_equals_new(tmp_path, capsys):
    assert (
        _found(tmp_path, [_row("pump", c, 8) for c in "ABC"], [_row("pump", "A", 8)])
        == 1
    )
    assert "not strictly better" in capsys.readouterr().out


@pytest.mark.parametrize(
    "bad", ["no comments", "no chance", "missing copy", "found not measured"]
)
def test_found_fails_on_not_measured(tmp_path, bad, capsys):
    rows = [_row("pump", "A", 9), _row("pump", "B", 9), _row("pump", "C", 9)]
    if bad == "no comments":
        rows[2] = _row("pump", "C", 9, comments=0)
    elif bad == "no chance":
        rows[2] = _row("pump", "C", 9, chance="NOT MEASURED")
    elif bad == "missing copy":
        rows = rows[:2]
    else:
        rows[2] = _row("pump", "C", None)
    assert _found(tmp_path, rows, [_row("pump", "A", 0)]) == 1
    assert "NOT MEASURED" in capsys.readouterr().out


def test_found_fails_when_the_old_engine_was_not_measured(tmp_path):
    assert _found(tmp_path, [_row("pump", c, 9) for c in "ABC"], []) == 1


def test_an_old_review_the_app_refused_counts_as_zero_with_its_sentence(
    tmp_path, capsys
):
    runs = tmp_path / "old-runs"
    runs.mkdir()
    (runs / "pump-A-run.json").write_text(
        json.dumps(
            {
                "paper": "pump",
                "copy": "A",
                "status": "refused",
                "words": "invented refusal",
            }
        )
    )
    rc = _found(
        tmp_path, [_row("pump", c, 7) for c in "ABC"], [], "--old-runs-dir", str(runs)
    )
    out = capsys.readouterr().out
    assert rc == 0 and "invented refusal" in out


def test_found_reads_the_one_copy_report_layout():
    text = "\n".join(
        [
            "key: pump-B (10 planted mistakes)   comments read: 40   file: x.json",
            "found (proven by code): 3 of 10: A1 A2 A3",
            "chance hits (original paper's review against this key): 1 of 10 (A4)",
            "key: valve-A (10 planted mistakes)   comments read: 0   file: y.json",
            "found: NOT MEASURED (no comments were read from this file)",
            "chance hits (original paper's review against this key): NOT MEASURED (no control: give ...)",
        ]
    )
    got = gate.parse_score(text)
    assert got[("pump", "B")] == {"found": 3, "chance": 1, "comments": 40}
    assert got[("valve", "A")] == {"found": None, "chance": None, "comments": 0}


# ------------------------------------------------------------------------------------------------ the gate: alarms


def _alarm_files(tmp_path, wrong_per_copy, comments=(34, 33, 33), skip_mark=None):
    sd, jd = tmp_path / "score", tmp_path / "judge"
    sd.mkdir(exist_ok=True)
    jd.mkdir(exist_ok=True)
    for c, n, w in zip("ABC", comments, wrong_per_copy, strict=True):
        (sd / f"pump-{c}-comments.json").write_text(
            json.dumps({"comments": [{"field": "x"}] * n})
        )
        marks = {str(i): ("WRONG" if i <= w else "KEEP") for i in range(1, n + 1)}
        if skip_mark and skip_mark[0] == c:
            marks.pop(str(skip_mark[1]))
        (jd / f"pump-{c}.json").write_text(json.dumps(marks))
    return [
        "alarms",
        "--score-dir",
        str(sd),
        "--judge-dir",
        str(jd),
        "--papers",
        "pump",
    ]


def test_alarms_pass_at_ten_percent(tmp_path):
    assert gate.main(_alarm_files(tmp_path, (4, 3, 3))) == 0  # 10 of 100


def test_alarms_fail_at_eleven_percent(tmp_path, capsys):
    assert gate.main(_alarm_files(tmp_path, (4, 4, 3))) == 1  # 11 of 100
    assert "11 of 100" in capsys.readouterr().out


def test_alarms_not_measured_when_one_comment_is_not_judged(tmp_path, capsys):
    assert gate.main(_alarm_files(tmp_path, (0, 0, 0), skip_mark=("B", 7))) == 1
    assert "judged 32 of 33" in capsys.readouterr().out


def test_alarms_not_measured_without_a_judge_file(tmp_path):
    argv = _alarm_files(tmp_path, (0, 0, 0))
    (tmp_path / "judge" / "pump-C.json").unlink()
    assert gate.main(argv) == 1


# ------------------------------------------------------------------------------------------------ the gate: switches


def test_switches_pass_when_the_app_runs_the_general_review(app, setup):
    assert (
        gate.main(
            [
                "switches",
                "--base-url",
                app.base,
                "--token-file",
                str(setup["token"]),
                "--datasheet-id",
                "doc_fake_9",
            ]
        )
        == 0
    )


@pytest.mark.parametrize("method", ["earlier", None])
def test_switches_fail_otherwise(app, setup, method, capsys):
    app.method = method
    assert (
        gate.main(
            [
                "switches",
                "--base-url",
                app.base,
                "--token-file",
                str(setup["token"]),
                "--datasheet-id",
                "doc_fake_9",
            ]
        )
        == 1
    )
    assert "SWITCHES GATE: FAIL" in capsys.readouterr().out


def test_a_failed_run_ends_the_wait_at_once_and_is_not_measured(app, setup, capsys):
    app.fail_runs = True
    argv_timeout = "60"  # a long timeout: the history, not the clock, must end the wait
    rc = driver.main(
        [
            "run",
            "--base-url",
            app.base,
            "--token-file",
            str(setup["token"]),
            "--copies-dir",
            str(setup["copies"]),
            "--out",
            str(setup["out"]),
            "--poll",
            "0.01",
            "--timeout",
            argv_timeout,
            "--papers",
            "pump",
            "--copies",
            "A",
        ]
    )
    assert rc == 1
    rec = json.loads((setup["out"] / "pump-A-run.json").read_text())
    assert rec["status"] == "failed" and rec["seconds"] < 30
    assert "NOT MEASURED" in capsys.readouterr().out


def test_sheet_rows_are_counted_under_the_tables_header_row():
    assert driver.xlsx_rows(_xlsx({"All points": 7}), "All points") == 7
    assert driver.xlsx_rows(_xlsx({"All points": 0}), "All points") == 0
    assert driver.xlsx_rows(_xlsx({"All points": 7}), "Comments") is None


def test_upload_sends_the_screens_default_discipline(app, setup):
    assert _run(app, setup, papers=("pump",)) == 0
    assert (
        b'name="disciplines"' in app.upload_bodies[0]
        and b"Invented-A" in app.upload_bodies[0]
    )


def test_upload_with_no_default_discipline_is_not_measured_and_retried_later(
    app, setup, capsys
):
    app.default_disc = []
    assert _run(app, setup, papers=("pump",)) == 1
    assert "give --discipline" in capsys.readouterr().out
    assert app.uploads == 0 and app.starts == []
    # it never started, so the next run tries it again (here with a chosen discipline)
    assert _run(app, setup, "--discipline", "Invented-B", papers=("pump",)) == 0
    assert b"Invented-B" in app.upload_bodies[-1]


# ------------------------------------------------------------------------------------------------ the gate: report


def _report_setup(
    tmp_path,
    found=(8, 8, 8),
    chance=("0 of 10",) * 3,
    wrong=(0, 0, 0),
    n=10,
    old=2,
    blocked=None,
    judge_skip=None,
):
    """A forged score folder for the valve: run files, comments, sheets, judge files, a new and an old score output."""
    sd, jd = tmp_path / "new", tmp_path / "judge"
    sd.mkdir()
    jd.mkdir()
    for c in ("A", "B", "C", "orig"):
        rec = {
            "label": f"valve-{c}",
            "paper": "valve",
            "copy": c,
            "status": "completed",
            "started": True,
            "comments": n,
        }
        if blocked and blocked[0] == c:
            rec = {
                "label": f"valve-{c}",
                "paper": "valve",
                "copy": c,
                "status": "not measured",
                "started": False,
                "words": blocked[1],
            }
        (sd / f"valve-{c}-run.json").write_text(json.dumps(rec))
        (sd / f"valve-{c}-comments.json").write_text(
            json.dumps({"comments": [{"field": "x"}] * n})
        )
        (sd / f"valve-{c}-sheet.xlsx").write_bytes(b"PK-invented")
    for c, w in zip("ABC", wrong, strict=True):
        marks = {str(i): ("WRONG" if i <= w else "KEEP") for i in range(1, n + 1)}
        if judge_skip == c:
            marks.pop("1")
        (jd / f"valve-{c}.json").write_text(json.dumps(marks))
    rows = [
        _row("valve", c, f, chance=ch)
        for c, f, ch in zip("ABC", found, chance, strict=True)
        if not (blocked and blocked[0] == c)
    ]
    argv = [
        "report",
        "--score",
        _score(tmp_path, "new.txt", rows),
        "--score-dir",
        str(sd),
        "--judge-dir",
        str(jd),
        "--papers",
        "valve",
    ]
    if old is not None:
        argv += ["--old", _score(tmp_path, "old.txt", [_row("valve", "A", old)])]
    return argv, sd


def test_report_pass_shows_every_copy_its_sheet_and_the_numbers(tmp_path, capsys):
    argv, sd = _report_setup(tmp_path)
    assert gate.main(argv) == 0
    out = capsys.readouterr().out
    assert "== valve: PASS" in out and "DONE GATE: PASS (1 of 1 papers PASS)" in out
    for c in ("A", "B", "C", "orig"):
        assert str(sd / f"valve-{c}-sheet.xlsx") in out
    assert "mean 8.00 of 10 | target 7.0 | old engine 2.00 (1 copies)" in out
    assert "0 WRONG of 30 comments = 0.0%" in out


def test_report_below_target_names_the_gap_and_never_rounds_up(tmp_path, capsys):
    argv, _ = _report_setup(tmp_path, found=(7, 7, 6))
    assert gate.main(argv) == 1
    out = capsys.readouterr().out
    assert "== valve: BELOW TARGET" in out
    assert (
        "valve: mean 6.66 (20/3) of 10, target 7.0, short by 0.34" in out
    )  # 6.666.. shown as 6.66, never 6.67
    assert "PASS" not in out.split("DONE GATE")[0].replace("NOT PASSED", "")


def test_report_below_target_on_false_alarms(tmp_path, capsys):
    argv, _ = _report_setup(tmp_path, wrong=(2, 1, 1))  # 4 of 30 = 13.3%
    assert gate.main(argv) == 1
    out = capsys.readouterr().out
    assert (
        "== valve: BELOW TARGET" in out
        and "valve: 4 WRONG of 30 comments = 13.3%, limit 10%" in out
    )


def test_report_below_target_when_not_above_the_old_engine(tmp_path, capsys):
    argv, _ = _report_setup(tmp_path, found=(8, 8, 8), old=8)
    assert gate.main(argv) == 1
    assert (
        "not above the old engine: new mean 8.00, old 8.00" in capsys.readouterr().out
    )


def test_report_not_measured_names_the_step_and_the_apps_sentence(tmp_path, capsys):
    argv, _ = _report_setup(
        tmp_path, blocked=("B", "upload: HTTP 422 (invented app sentence)")
    )
    assert gate.main(argv) == 1
    out = capsys.readouterr().out
    assert "== valve: NOT MEASURED" in out
    assert (
        "valve-B: upload: HTTP 422 (invented app sentence) (status not measured)" in out
    )


@pytest.mark.parametrize(
    "case,words",
    [
        (
            "no judge mark",
            "valve-C: false alarms NOT MEASURED (the reader judged 9 of 10 comments)",
        ),
        ("no old", "the old engine's number NOT MEASURED"),
        ("no chance", "valve-A: chance hits NOT MEASURED"),
        ("no score", "valve-A: no row in the score output"),
    ],
)
def test_report_not_measured_cases(tmp_path, capsys, case, words):
    kw = {
        "no judge mark": {"judge_skip": "C"},
        "no old": {"old": None},
        "no chance": {"chance": ("NOT MEASURED", "0 of 10", "0 of 10")},
    }.get(case, {})
    argv, _ = _report_setup(tmp_path, **kw)
    if case == "no score":
        argv[argv.index("--score") + 1] = _score(tmp_path, "empty.txt", [])
    assert gate.main(argv) == 1
    out = capsys.readouterr().out
    assert "== valve: NOT MEASURED" in out and words in out


def test_report_exit_is_zero_only_when_every_paper_passes(tmp_path, capsys):
    argv, _ = _report_setup(tmp_path)
    argv.insert(argv.index("--papers") + 2, "pump")  # pump has nothing: NOT MEASURED
    assert gate.main(argv) == 1
    out = capsys.readouterr().out
    assert (
        "== valve: PASS" in out
        and "== pump: NOT MEASURED" in out
        and "1 of 2 papers PASS" in out
    )
