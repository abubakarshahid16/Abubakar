"""V2: the suite cannot reach a real local model (the conftest guard). It fails on a Mac that runs Ollama if the guard goes."""

import httpx
import pytest


def test_a_request_to_the_real_ollama_port_is_refused():
    with pytest.raises(httpx.ConnectError, match="conftest guard"):
        httpx.Client(trust_env=False).get("http://127.0.0.1:11434/api/tags")


def test_a_fake_transport_on_the_same_address_still_works():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"ok": True})))
    assert client.get("http://127.0.0.1:11434/api/tags").json() == {"ok": True}
