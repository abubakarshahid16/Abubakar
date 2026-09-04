"""The command the UI tells an operator to type must actually be correct.

The disconnected banner instructed them to run plain uvicorn, which
reinstates the `Server: uvicorn` header that run.py exists to suppress - the
UI was telling them to undo a fix. The command now lives in one place,
contracts/runtime.ts, and these tests assert that file still describes
reality.
"""
import inspect
import re
from pathlib import Path

import run
from app.config import settings

RUNTIME_TS = Path(__file__).resolve().parents[2] / "contracts" / "runtime.ts"


def read_const(name: str) -> str:
    text = RUNTIME_TS.read_text(encoding="utf-8")
    m = re.search(rf'export const {name} = "([^"]*)"', text)
    assert m, f"{name} not found in contracts/runtime.ts"
    return m.group(1)


def test_the_runtime_contract_exists():
    assert RUNTIME_TS.exists(), "contracts/runtime.ts is the single source for this"


def test_the_documented_entrypoint_is_run_py_not_bare_uvicorn():
    entrypoint = read_const("BACKEND_ENTRYPOINT")
    assert entrypoint == "run.py", (
        f"the UI tells the operator to start the backend with {entrypoint!r}; "
        "plain uvicorn reinstates the server banner run.py suppresses"
    )
    assert (Path(run.__file__).name) == "run.py"


def test_the_documented_entrypoint_actually_suppresses_the_banner():
    source = inspect.getsource(run.main)
    assert "server_header=False" in source


def test_the_documented_api_origin_matches_the_configured_bind():
    text = RUNTIME_TS.read_text(encoding="utf-8")
    m = re.search(r'export const API_ORIGIN = "([^"]*)"', text)
    assert m
    assert m.group(1) == f"http://{settings.host}:{settings.port}", (
        "the UI points at a different address than the API binds to"
    )


def test_the_documented_python_path_is_the_project_root_venv():
    python = read_const("PYTHON")
    assert python.endswith("python.exe")
    assert "\.venv\\" in python
    assert r"backend\.venv" not in python, "the venv is at the project root"
