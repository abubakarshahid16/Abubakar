"""V2: the suite cannot reach a real local model (the conftest guard). It fails on a Mac that runs Ollama if the guard goes."""

import httpx
import pytest


def test_a_request_to_the_real_ollama_port_is_refused():
    with pytest.raises(httpx.ConnectError, match="conftest guard"):
        httpx.Client(trust_env=False).get("http://127.0.0.1:11434/api/tags")


def test_a_fake_transport_on_the_same_address_still_works():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"ok": True})))
    assert client.get("http://127.0.0.1:11434/api/tags").json() == {"ok": True}


def test_a_child_process_started_by_a_test_cannot_reach_the_real_model_port():
    """V3: the in-process guard cannot reach a child. The session exports a closed model port as OLLAMA_URL, so a script or
    app a test starts dials that instead of 11434. The child must see the closed port and get a refusal from the transport."""
    import subprocess
    import sys
    from pathlib import Path

    from tests import env_isolation

    code = (
        "import sys\n"
        "from app.config import settings\n"
        "from app import model_transport\n"
        "print('URL', settings.ollama_url)\n"
        "try:\n"
        "    model_transport.post_json('/api/tags', {}, timeout=3)\n"
        "    print('REACHED')\n"
        "except Exception as exc:\n"
        "    print('REFUSED', type(exc).__name__)\n"
    )
    backend = Path(__file__).resolve().parents[1]
    done = subprocess.run([sys.executable, "-c", code], cwd=backend, capture_output=True, text=True, timeout=120)
    out = done.stdout
    if env_isolation.real_model_allowed():
        return  # the owner asked for the real model on purpose
    assert f"URL {env_isolation.DEAD_MODEL_URL}" in out, (out, done.stderr[-400:])
    assert "REFUSED" in out and "REACHED" not in out, out
