"""Local-only trace, live log, LIVE.md and resume state for the agent proof test (#1690, part of #805).

Everything here is written under ONE local root (default `~/project/mirror/proof/agent-test/`, override with the env
variable `AGENT_TEST_DIR`). A root inside the git repository is refused: these files are never committed, never in CI,
never in chat.

WHAT IS WRITTEN. Page numbers, clause numbers, tool names, ok/refused, counts, seconds, a reason of at most 20 words.
NEVER a quote of document or standard text: tool arguments are reduced to a whitelist of reference keys whose values
must look like a number or id (`_ref`); anything else is recorded as its key name only; every free text is cut to
`MAX_WORDS` words and `MAX_CHARS` characters.

RESUME. `state.json` holds the completed item ids and the spend so far; one `<item>.ckpt.json` per unfinished item
holds the calls made so far (tool, arguments, reason, usd) and is rewritten after every step, BEFORE the next model
call. A killed run therefore resumes at the saved step: read-only tools are re-run to rebuild the conversation, the
two tools with side effects (record_finding, ask_engineer) keep their saved result and are not run again.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = Path.home() / "project" / "mirror" / "proof" / "agent-test"
ENV_NAME = "AGENT_TEST_DIR"
MAX_WORDS = 20
MAX_CHARS = 160
REF_KEYS = ("page", "clause", "standard", "doc")
SIDE_EFFECT_TOOLS = ("record_finding", "ask_engineer")
VERDICT_WORDS = ("accepted", "refused", "decided", "cannot decide")
COLOURS = ("GREEN", "YELLOW", "RED")

_REF = re.compile(r"^[A-Za-z]{0,6}[\d][\d.\-]{0,20}[A-Za-z]?$")
_ID = re.compile(r"^[\w\-]{1,40}$")


class UnsafeRoot(ValueError):
    """The trace root is inside the git repository."""


def resolve_root(root: str | os.PathLike | None = None) -> Path:
    """The trace root. Refuses a path inside the repository or inside any git work tree."""
    chosen = root if root is not None else (os.environ.get(ENV_NAME) or DEFAULT_ROOT)
    path = Path(chosen).expanduser().resolve()
    if path == REPO_ROOT or REPO_ROOT in path.parents:
        raise UnsafeRoot("the agent test directory must be outside the git repository")
    for parent in (path, *path.parents):
        if (parent / ".git").exists():
            raise UnsafeRoot(
                "the agent test directory must be outside any git work tree"
            )
    return path


def words(text: Any, limit: int = MAX_WORDS) -> str:
    """At most `limit` words and MAX_CHARS characters, one line, no quote marks."""
    s = " ".join(str(text or "").replace('"', "").replace("'", "").split())
    s = " ".join(s.split(" ")[:limit])
    return s[:MAX_CHARS]


def _ref(key: str, value: Any) -> Any:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        v = value.strip()
        if key == "page" or key == "clause" or key == "standard":
            return v if _REF.match(v) else None
        return v if _ID.match(v) else None
    return None


def safe_args(args: Any) -> dict:
    """Tool arguments reduced to reference numbers; other keys are named, never valued."""
    out: dict[str, Any] = {}
    other: list[str] = []
    for key, value in (args or {}).items() if isinstance(args, dict) else []:
        if key in REF_KEYS:
            ref = _ref(key, value)
            if ref is not None:
                out[key] = ref
                continue
        other.append(str(key)[:30])
    if other:
        out["other_keys"] = sorted(other)[:8]
    return out


def safe_result(result: Any) -> dict:
    """Result summary: ok, cites as page/clause numbers, a fixed verdict word, a refusal reason of code origin."""
    if not isinstance(result, dict):
        return {"ok": False}
    out: dict[str, Any] = {"ok": bool(result.get("ok"))}
    cites = []
    for cite in result.get("cites") or []:
        if isinstance(cite, dict):
            one = {k: _ref(k, cite[k]) for k in REF_KEYS if k in cite}
            one = {k: v for k, v in one.items() if v is not None}
            if one:
                cites.append(one)
    out["cites"] = cites[:20]
    inner = result.get("result") if isinstance(result.get("result"), dict) else {}
    verdict = str(inner.get("verdict") or inner.get("status") or "").lower()
    if verdict in VERDICT_WORDS:
        out["verdict"] = verdict
    if verdict == "refused" and inner.get("reason"):
        out["refusal_reason"] = words(inner.get("reason"))
    return out


_QUOTE_MARKS = "\"'\u201c\u201d\u2018\u2019\u00ab\u00bb"
_TOKEN = re.compile(r"\w+")
COPY_RUN = 13  # more than 12 consecutive words


def _strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def _grams(text: str) -> set[tuple[str, ...]]:
    toks = _TOKEN.findall(text.lower())
    return {tuple(toks[i : i + COPY_RUN]) for i in range(len(toks) - COPY_RUN + 1)}


def reason_is_safe(reason: Any, sources: set) -> bool:
    """False if the reason has a quote mark or 13+ consecutive words copied from a tool result."""
    text = str(reason or "")
    if any(ch in text for ch in _QUOTE_MARKS):
        return False
    return not (_grams(text) & sources)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    tmp.replace(path)


def _file_id(item_id: Any) -> str:
    """File-name slug plus a short hash of the raw id, so 'a/b' and 'a_b' never share a file."""
    raw = str(item_id)
    slug = re.sub(r"[^\w\-]", "_", raw)[:60] or "item"
    return f"{slug}-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:8]}"


class TraceWriter:
    """One run's local files: item traces, live.log, LIVE.md, state.json, checkpoints."""

    def __init__(
        self,
        root: str | os.PathLike | None = None,
        *,
        total: int = 0,
        model: str = "",
        step_name: str = "",
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.root = resolve_root(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self.started = clock()
        self.total = total
        self.live = {
            "STEP": step_name,
            "DONE": "",
            "PROOF": "agent proof test (#1690)",
            "RUNNING": "",
            "MODEL": model,
            "NEXT": "",
        }
        self.problems: list[str] = []
        #: ONE source for the problems text and the headline note (set by the runner): (run problems) -> (lines, note)
        self.stats_view: Callable[[list[str]], tuple[list[str], str]] | None = None
        self.recent: deque[str] = deque(maxlen=5)
        self.counts = {"GREEN": 0, "YELLOW": 0, "RED": 0, "not sure": 0}
        # wrong verdicts are only known after the answer-key score; None = not measured
        self.wrong: int | None = None
        self.completed: dict[str, str] = {}
        self._sources: dict[str, set] = {}
        self._sink: FindingSink | None = None
        self.spend = 0.0
        self._load_state()

    # state and resume -------------------------------------------------------------------------------------------
    @property
    def state_path(self) -> Path:
        return self.root / "state.json"

    def _load_state(self) -> None:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except OSError:
            return
        except ValueError:
            data = None
        done = data.get("completed") if isinstance(data, dict) else None
        spend = data.get("spend") if isinstance(data, dict) else None
        numeric = isinstance(spend, (int, float)) and not isinstance(spend, bool)
        if not (isinstance(done, (dict, list)) and numeric and spend >= 0):
            self._corrupt_state()
            return
        if isinstance(done, dict):
            self.completed = {str(k): str(v) for k, v in done.items()}
        else:
            self.completed = {str(k): "" for k in done}
        self.spend = float(spend)
        for colour in self.completed.values():
            if colour in self.counts:
                self.counts[colour] += 1

    def _corrupt_state(self) -> None:
        """A state.json of the wrong shape is kept as state.json.corrupt; the run starts fresh."""
        with contextlib.suppress(OSError):
            self.state_path.replace(self.state_path.with_name("state.json.corrupt"))
        self.problem(
            "state.json was corrupt: kept as state.json.corrupt, starting fresh"
        )

    def _save_state(self) -> None:
        _atomic_write(
            self.state_path,
            json.dumps(
                {"completed": self.completed, "spend": round(self.spend, 6)},
                sort_keys=True,
            ),
        )

    def is_done(self, item_id: Any) -> bool:
        return str(item_id) in self.completed

    def add_spend(self, usd: float) -> None:
        self.spend += max(0.0, float(usd or 0.0))
        self._save_state()

    def mark_done(self, item_id: Any, colour: str) -> None:
        if str(item_id) in self.completed:
            return  # counted once, whatever is called twice
        self.completed[str(item_id)] = colour if colour in COLOURS else "not sure"
        key = colour if colour in self.counts else "not sure"
        self.counts[key] += 1
        self._save_state()
        with contextlib.suppress(OSError):
            self._ckpt_path(item_id).unlink()
        done = len(self.completed)
        if done % 10 == 0:
            self.refresh_live()

    def unmark_done(self, item_id: Any) -> None:
        """Take an item back out of the finished set, so a resume runs it again (the failure breaker uses this)."""
        colour = self.completed.pop(str(item_id), None)
        if colour is None:
            return
        self.counts[colour if colour in self.counts else "not sure"] -= 1
        self._save_state()

    def _ckpt_path(self, item_id: Any) -> Path:
        return self.root / f"{_file_id(item_id)}.ckpt.json"

    def load_checkpoint(self, item_id: Any) -> list[dict]:
        try:
            data = json.loads(self._ckpt_path(item_id).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [c for c in data.get("calls", []) if isinstance(c, dict)]

    def save_checkpoint(self, item_id: Any, calls: list[dict]) -> None:
        _atomic_write(self._ckpt_path(item_id), json.dumps({"calls": calls}))

    # item trace and live.log ------------------------------------------------------------------------------------
    def _append(self, path: Path, line: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    @property
    def sink(self) -> FindingSink:
        """The run's persistent finding sink (one per run directory)."""
        if self._sink is None:
            self._sink = FindingSink(self.root)
        return self._sink

    def clean_reason(self, item_id: Any, reason: Any) -> str:
        """The reason that may be written: capped, and withheld if it quotes or copies a tool result."""
        if not reason:
            return ""
        if not reason_is_safe(reason, self._sources.get(str(item_id), set())):
            return "reason withheld"
        return words(reason)

    def _remember(self, item_id: Any, result: Any) -> None:
        keep = self._sources.setdefault(str(item_id), set())
        for text in _strings(result):
            keep |= _grams(text)

    def step(
        self,
        *,
        doc: Any,
        item_id: Any,
        step: int,
        tool: str,
        args: Any,
        result: Any,
        verified: Any = "",
        seconds: float = 0.0,
        reason: Any = "",
        replayed: bool = False,
    ) -> None:
        self._remember(item_id, result)
        reason = self.clean_reason(item_id, reason)
        summary = safe_result(result)
        record = {
            "item": str(item_id),
            "step": step,
            "tool": str(tool)[:40],
            "args": safe_args(args),
            "result": summary,
            "verified": words(verified),
            "seconds": round(seconds, 3),
            "reason": words(reason),
            "replayed": replayed,
        }
        self._append(
            self.root / f"{_file_id(item_id)}.trace.jsonl",
            json.dumps(record, sort_keys=True),
        )
        cite = summary["cites"][0] if summary["cites"] else {}
        where = cite.get("page", cite.get("clause", ""))
        self.log(
            doc=doc,
            item_id=item_id,
            step=step,
            tool=tool,
            where=where,
            result="ok" if summary["ok"] else "failed",
            seconds=seconds,
            reason=reason,
        )
        self.recent.append(f"{item_id} step {step} {words(tool, 3)}")

    def log(
        self,
        *,
        doc: Any,
        item_id: Any,
        step: Any,
        tool: Any,
        where: Any = "",
        result: Any = "",
        seconds: float = 0.0,
        reason: Any = "",
    ) -> None:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.clock()))
        ref = _ref("page", where) if where != "" else ""
        parts = [
            stamp,
            f"doc={_ref('doc', str(doc)) or '-'}",
            f"item={_file_id(item_id)}",
            f"step={step}",
            f"tool={words(tool, 2)}",
            f"at={ref if ref is not None else '-'}",
            f"result={words(result, 3)}",
            f"s={seconds:.1f}",
            f"reason={words(reason)}",
        ]
        self._append(self.root / "live.log", " | ".join(parts))

    def finish_item(
        self, *, doc: Any, item_id: Any, finding: dict, why: Any, usd: float, steps: int
    ) -> None:
        colour = finding.get("color") if isinstance(finding, dict) else None
        why = self.clean_reason(item_id, why)
        with contextlib.suppress(OSError):
            self._ckpt_path(item_id).unlink()
        record = {
            "item": str(item_id),
            "final": True,
            "color": colour if colour in COLOURS else None,
            "why": words(why),
            "usd": round(float(usd or 0.0), 6),
            "steps": steps,
        }
        self._append(
            self.root / f"{_file_id(item_id)}.trace.jsonl",
            json.dumps(record, sort_keys=True),
        )
        self.log(
            doc=doc,
            item_id=item_id,
            step=steps,
            tool="final",
            result=colour or "none",
            reason=why,
        )
        self.recent.append(f"{item_id} {colour or 'no verdict'}")

    # LIVE.md ----------------------------------------------------------------------------------------------------
    def problem(self, text: Any, *, doc: Any = "-", item_id: Any = "-") -> None:
        """A PROBLEM: shown in LIVE.md and written to live.log as its own line."""
        self.problems.append(words(text))
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.clock()))
        self._append(
            self.root / "live.log",
            f"{stamp} | PROBLEM | doc={_ref('doc', str(doc)) or '-'} "
            f"| item={_file_id(item_id)} | {words(text)}",
        )
        self.problems = self.problems[-10:]

    def note_problem(self, text: Any) -> None:
        """A PROBLEM line in live.log only (the count and LIVE.md come from `stats_view`)."""
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.clock()))
        self._append(self.root / "live.log", f"{stamp} | PROBLEM | {words(text)}")

    def set_live(self, **fields: str) -> None:
        for key, value in fields.items():
            self.live[key.upper()] = words(value, 40)

    def progress(self) -> str:
        done = len(self.completed)
        total = max(self.total, done)
        width = 20
        filled = int(width * done / total) if total else 0
        bar = "#" * filled + "-" * (width - filled)
        elapsed = max(0.0, self.clock() - self.started)
        if done and total > done:
            left = f"{int(elapsed / done * (total - done) / 60)} min left"
        else:
            left = "0 min left" if total and done >= total else "time left unknown"
        return f"[{bar}] {done}/{total} items, {left}"

    def set_wrong(self, wrong: int | None) -> None:
        """Record the measured count of wrong verdicts (from the answer-key score)."""
        self.wrong = wrong

    def refresh_live(self, wrong: int | None = None) -> Path:
        """Rewrite LIVE.md. `wrong` is shown only when measured (passed here or via set_wrong)."""
        c = self.counts
        measured = wrong if wrong is not None else self.wrong
        wrong = "not measured (needs the key score)" if measured is None else measured
        shown, note = (
            self.stats_view(self.problems) if self.stats_view else (self.problems, "")
        )
        lines = ["# LIVE", ""]
        for key in ("STEP", "DONE", "PROOF", "RUNNING"):
            lines.append(f"- **{key}**: {self.live.get(key, '')}")
        lines.append(f"- **PROGRESS**: {self.progress()}")
        lines.append(f"- **MODEL**: {self.live.get('MODEL', '')}")
        lines.append(
            f"- **RESULTS**: GREEN {c['GREEN']}, YELLOW {c['YELLOW']}, RED {c['RED']}, "
            f"not sure {c['not sure']}, wrong {wrong}{note}"
        )
        lines.append(f"- **SPEND**: USD {self.spend:.2f}")
        lines.append(f"- **PROBLEMS**: {'; '.join(shown) if shown else 'none'}")
        lines.append(f"- **NEXT**: {self.live.get('NEXT', '')}")
        lines += ["", "## Last 5 things done", ""]
        lines += [f"- {r}" for r in self.recent] or ["- nothing yet"]
        path = self.root / "LIVE.md"
        _atomic_write(path, "\n".join(lines) + "\n")
        return path

    def piece_done(self, text: Any = "") -> None:
        """A piece of work finished: LIVE.md is rewritten now."""
        if text:
            self.recent.append(words(text, 12))
        self.refresh_live()


class FindingSink:
    """Accepted findings, persisted to `<run_dir>/findings.jsonl`, reloaded on resume.

    PRIVACY: this file DOES hold the verified document and clause quotes, because the contractor
    comment needs them. It is LOCAL (same trace root rule: a path in a git tree is refused) and is
    never read into live.log, LIVE.md or the trace summaries. The last finding added for an item wins.

    The tools helper receives it as `ToolBox(ctx)` with `ctx.findings = sink`; `run_items` sets that
    attribute on the toolbox's ctx (or on the toolbox itself when it has no ctx).
    """

    def __init__(self, run_dir: str | os.PathLike) -> None:
        self.dir = resolve_root(run_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "findings.jsonl"
        self._by_item: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError:
            return
        if text and not text.endswith("\n"):
            # a kill mid-write left a torn tail: end that line so the next add() starts a new one
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write("\n")
        lines = text.splitlines()
        for line in lines:
            try:
                rec = json.loads(line)
            except ValueError:
                continue  # recorded: a torn last line from a kill is skipped
            if isinstance(rec, dict) and isinstance(rec.get("finding"), dict):
                self._by_item[str(rec.get("item"))] = rec["finding"]

    def add(self, item_id: Any, finding: dict) -> None:
        line = json.dumps({"item": str(item_id), "finding": finding}, sort_keys=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        self._by_item[str(item_id)] = dict(finding)

    def get(self, item_id: Any) -> dict | None:
        found = self._by_item.get(str(item_id))
        return dict(found) if found is not None else None

    def has(self, item_id: Any) -> bool:
        return str(item_id) in self._by_item

    def all(self) -> list[dict]:
        return [dict(f) for f in self._by_item.values()]


class RunLocked(RuntimeError):
    """Another live run already uses this run directory."""


class RunLock:
    """One writer per run directory: `run.lock` created with O_EXCL, holding the pid.

    A lock whose pid is gone (or an empty one older than 10 seconds) is stale and is taken over.
    Use as a context manager: released at the end and on an exception.
    """

    def __init__(self, run_dir: str | os.PathLike) -> None:
        self.path = resolve_root(run_dir) / "run.lock"
        self.mine = False

    @staticmethod
    def _alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def _stale(self) -> bool:
        try:
            text = self.path.read_text(encoding="utf-8").strip()
            age = time.time() - self.path.stat().st_mtime
        except OSError:
            return True
        try:
            return not self._alive(int(text.split()[0]))
        except (ValueError, IndexError):
            return age > 10

    def acquire(self) -> RunLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                if self._stale():
                    with contextlib.suppress(OSError):
                        self.path.unlink()
                    continue
                raise RunLocked(
                    f"another run is using {self.path.parent} (see {self.path.name})"
                ) from None
            with os.fdopen(fd, "w") as fh:
                fh.write(f"{os.getpid()} {int(time.time())}\n")
            self.mine = True
            return self
        raise RunLocked(f"could not take {self.path}")

    def release(self) -> None:
        if self.mine:
            with contextlib.suppress(OSError):
                self.path.unlink()
            self.mine = False

    def __enter__(self) -> RunLock:
        return self.acquire()

    def __exit__(self, *exc: object) -> None:
        self.release()
