"""What the PF1 CPU workflow may run (#881, order 171).

The workflow (`.github/workflows/pf1-cpu.yml`) runs on GitHub's machines, so it
may only ever see INVENTED TUNING sheets: the folder it reads is exactly
`backend/tests/fixtures/synthetic/pf1/`; a sheet marked `held_out`, a sheet of the library group
(which carries text from the standards) and any file that is not a plain name
inside that folder are refused, and the whole run with them. The decision
lives here, not in YAML, so it is tested.

`plan` prints the job matrix (`{"include": [{"id": ...}]}`) for the sheets the
guard allows, or refuses with a plain message and exit 2.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

INDEX_FORMAT = "pf1-index/1"
#: The only folder the workflow reads, relative to the repository root.
SET_DIR = Path("backend") / "tests" / "fixtures" / "synthetic" / "pf1"


#: A sheet id goes into a job name and a shell command: lower case, digits, dashes.
ID = re.compile(r"[a-z0-9][a-z0-9-]*")


class Refused(ValueError):
    """The set may not go to a runner; the message names the sheet and the rule."""


def _inside(folder: Path, name: object) -> Path:
    if (
        not isinstance(name, str)
        or not name
        or Path(name).name != name
        or name.startswith(".")
    ):
        raise Refused(f"a file name that is not a plain name inside the set: {name!r}")
    path = (folder / name).resolve()
    if folder.resolve() not in path.parents or not path.is_file():
        raise Refused(f"{name}: not a file inside the set folder")
    return path


def check_folder(repo: Path, folder: str | Path) -> Path:
    """The set folder, only when it is exactly `<repo>/backend/tests/fixtures/synthetic/pf1`."""
    path = Path(folder).resolve()
    if path != (Path(repo) / SET_DIR).resolve():
        raise Refused(
            f"the set folder must be {SET_DIR.as_posix()}; no other folder goes to a runner"
        )
    if not path.is_dir():
        raise Refused(f"{SET_DIR.as_posix()} does not exist")
    return path


def allowed(index: dict, folder: Path, only: list[str] | None = None) -> list[dict]:
    """The sheets of `index` the workflow may run. Raises `Refused` on the
    first sheet that breaks a rule, because one held-out sheet in the set means
    the set is not the tuning set."""
    if index.get("format") != INDEX_FORMAT or index.get("source") != "invented":
        raise Refused("the index is not an invented pf1-index/1")
    docs = index.get("documents")
    if not isinstance(docs, list) or not docs:
        raise Refused("the index lists no sheets")
    out = []
    for doc in docs:
        name = doc.get("id", "?")
        if not isinstance(name, str) or not ID.fullmatch(name):
            raise Refused(
                f"a sheet id that is not lower case, digits and dashes: {name!r}"
            )
        if doc.get("held_out") is not False:
            raise Refused(
                f"{name}: held out (or not stated): held-out sheets never go to a runner"
            )
        if doc.get("group") != "invented":
            raise Refused(
                f"{name}: not the invented group: library sheets carry standard text"
            )
        for field in ("datasheet", "standard", "key"):
            _inside(folder, doc.get(field))
        out.append(doc)
    if only:
        known = {d["id"] for d in out}
        unknown = sorted(set(only) - known)
        if unknown:
            raise Refused(f"not in the set: {', '.join(unknown)}")
        out = [d for d in out if d["id"] in only]
    return out


def plan(repo: str | Path, folder: str | Path, only: list[str] | None = None) -> dict:
    """The job matrix for the allowed sheets."""
    base = check_folder(Path(repo), folder)
    try:
        index = json.loads((base / "index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Refused(f"index.json could not be read ({type(exc).__name__})") from exc
    return {"include": [{"id": d["id"]} for d in allowed(index, base, only)]}
