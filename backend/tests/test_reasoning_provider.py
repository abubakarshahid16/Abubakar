"""Feature 1 section 5a: one interface, and provenance on every response.

The point of these tests is B54: before this interface, nothing in the system
could say WHICH model produced an answer. `review_runs.model_name` is NULL on
every row, there is no provider or digest column anywhere, and the local path
threw away the tag Ollama reports in every response. So the tests that matter
here are the ones that make a response without provenance IMPOSSIBLE to build,
not the ones that check it is usually present.

No network: `model_transport.post_json` is monkeypatched throughout. No client
content: every prompt and answer below is invented.
"""
from __future__ import annotations

import hashlib

import pytest

from app import model_transport, reasoning_provider, synthesis
from app.reasoning_provider import OllamaProvider, Packet, ProviderRefused, Response

PACKET = Packet(prompt="Does 0 mm satisfy a 1.6 mm minimum?",
                num_ctx=8192, num_predict=1200)

REPLY = {
    "model": "qwen3.5:9b",
    "response": "  NEEDS_ENGINEER_REVIEW  ",
    "done_reason": "stop",
    "prompt_eval_count": 577,
    "eval_count": 281,
}


def _fake_post(reply, seen=None):
    def post_json(path, body, **kwargs):
        if seen is not None:
            seen["path"] = path
            seen["body"] = body
        return reply
    return post_json


def test_a_response_carries_the_provider_the_tag_and_a_digest(monkeypatch):
    monkeypatch.setattr(model_transport, "post_json", _fake_post(REPLY))

    out = OllamaProvider(model="qwen3.5:9b").reason(PACKET)

    assert out.provider == reasoning_provider.OLLAMA
    assert out.model_tag == "qwen3.5:9b"
    assert out.digest == hashlib.sha256(b"NEEDS_ENGINEER_REVIEW").hexdigest()
    assert out.prompt_sha256 == PACKET.sha256
    assert out.text == "NEEDS_ENGINEER_REVIEW"
    assert out.tokens_in == 577 and out.tokens_out == 281


def test_a_response_with_no_model_tag_cannot_be_built():
    """THE GUARANTEE. Provenance is enforced by the type, not by a convention
    a later caller can forget - the same discipline `CitedSentence` uses to
    make an uncited sentence unrepresentable."""
    with pytest.raises(ValueError, match="provenance"):
        Response(text="x", provider=reasoning_provider.OLLAMA, model_tag="",
                 digest="d", finish_reason="stop", prompt_sha256="p")


def test_an_unknown_provider_cannot_be_built():
    with pytest.raises(ValueError, match="unknown provider"):
        Response(text="x", provider="something-else", model_tag="t",
                 digest="d", finish_reason="stop", prompt_sha256="p")


def test_the_tag_recorded_is_the_one_the_engine_reported_not_the_one_asked_for(monkeypatch):
    """A floating tag can resolve to something else under a running system,
    and that is exactly the case worth recording. Configuration asks for one
    thing; the response says what actually answered, and the response wins."""
    monkeypatch.setattr(model_transport, "post_json",
                        _fake_post({**REPLY, "model": "qwen3.5:9b-q4_K_M"}))

    out = OllamaProvider(model="qwen3.5:9b").reason(PACKET)

    assert out.model_tag == "qwen3.5:9b-q4_K_M", "the engine's answer was overwritten"
    assert OllamaProvider(model="qwen3.5:9b").requested_model == "qwen3.5:9b"


def test_an_engine_that_reports_no_tag_is_marked_not_papered_over(monkeypatch):
    """Falling back silently to the requested tag would claim provenance the
    response did not supply. The fallback says so in the value itself."""
    monkeypatch.setattr(model_transport, "post_json",
                        _fake_post({k: v for k, v in REPLY.items() if k != "model"}))

    out = OllamaProvider(model="qwen3.5:4b").reason(PACKET)

    assert out.model_tag == "qwen3.5:4b (unreported)"


def test_num_ctx_and_num_predict_are_sent_explicitly(monkeypatch):
    """Pinned, never defaulted. A defaulted context window silently changes
    what the model saw between two runs compared as if they were one test -
    the confound the Phase A matrix was designed to remove."""
    seen: dict = {}
    monkeypatch.setattr(model_transport, "post_json", _fake_post(REPLY, seen))

    OllamaProvider().reason(Packet(prompt="q", num_ctx=4096, num_predict=300,
                                   temperature=0.0, seed=42))

    assert seen["path"] == "/api/generate"
    assert seen["body"]["options"]["num_ctx"] == 4096
    assert seen["body"]["options"]["num_predict"] == 300
    assert seen["body"]["options"]["temperature"] == 0.0
    assert seen["body"]["options"]["seed"] == 42
    assert seen["body"]["think"] is False, "thinking is off by default"
    assert seen["body"]["stream"] is False


def test_a_truncated_answer_is_not_reported_as_a_complete_one(monkeypatch):
    """`length` means the cap ended it, not the model. Two Phase A runs ended
    this way and returned nothing at all; an answer that simply stops must not
    read as a finished one."""
    monkeypatch.setattr(model_transport, "post_json",
                        _fake_post({**REPLY, "done_reason": "length"}))

    out = OllamaProvider().reason(PACKET)

    assert out.finish_reason == "length"
    assert out.truncated is True


def test_a_transport_failure_is_a_named_refusal_not_an_empty_answer(monkeypatch):
    """"It did not happen, here is why" and "it happened and produced nothing"
    are different facts - B44's distinction, applied to the model."""
    def boom(path, body, **kwargs):
        raise TimeoutError("no route to the model host")
    monkeypatch.setattr(model_transport, "post_json", boom)

    with pytest.raises(ProviderRefused, match="TimeoutError"):
        OllamaProvider().reason(PACKET)


def test_the_thinking_channel_is_kept_separate_from_the_answer(monkeypatch):
    """Phase A's pivotal evidence came from the thinking channel while the
    response channel was empty. They are never merged."""
    monkeypatch.setattr(model_transport, "post_json",
                        _fake_post({**REPLY, "thinking": "weighing the options"}))

    out = OllamaProvider().reason(PACKET)

    assert out.thinking == "weighing the options"
    assert "weighing" not in out.text


# ================================================= #180: images and timeout


def test_180_the_provider_passes_a_timeout_the_real_transport_requires(monkeypatch):
    """THE LATENT DEFECT. `model_transport.post_json` takes a KEYWORD-ONLY
    `timeout` with no default, and `OllamaProvider.reason` never passed one,
    so every real call raised TypeError and came back as ProviderRefused. The
    fakes above accept `**kwargs`, which is why nothing noticed: this fake has
    the real signature."""
    seen: dict = {}

    def post_json(path, body, *, timeout):
        seen["timeout"] = timeout
        return REPLY
    monkeypatch.setattr(model_transport, "post_json", post_json)

    OllamaProvider().reason(Packet(prompt="q", num_ctx=4096, num_predict=10,
                                   timeout_s=42.0))

    assert seen["timeout"] == 42.0


def test_180_images_are_sent_and_are_part_of_what_the_packet_hash_names(monkeypatch):
    """A vision packet sends its images in Ollama's `images` field, and the
    packet's sha256 covers them: two packets with one prompt and different
    page images are different inputs, and a result tied to "the prompt"
    alone could not say which page it read."""
    seen: dict = {}
    monkeypatch.setattr(model_transport, "post_json", _fake_post(REPLY, seen))
    with_image = Packet(prompt="q", num_ctx=4096, num_predict=10, images=("aGVsbG8=",))
    other_image = Packet(prompt="q", num_ctx=4096, num_predict=10, images=("d29ybGQ=",))

    out = OllamaProvider().reason(with_image)

    assert seen["body"]["images"] == ["aGVsbG8="]
    assert with_image.sha256 != other_image.sha256
    assert with_image.sha256 != Packet(prompt="q", num_ctx=4096, num_predict=10).sha256
    assert out.prompt_sha256 == with_image.sha256


def test_180_a_text_packet_sends_no_images_field(monkeypatch):
    """The control: a text packet's body is unchanged by the vision work."""
    seen: dict = {}
    monkeypatch.setattr(model_transport, "post_json", _fake_post(REPLY, seen))
    OllamaProvider().reason(PACKET)
    assert "images" not in seen["body"]


# ============================================== B54 on the pre-existing path


def test_generation_no_longer_discards_the_model_ollama_reported():
    """It kept two fields, so `review_runs.model_name` could never be written
    from it. The tag was in the response the whole time."""
    gen = synthesis.Generation.from_ollama(REPLY)

    assert gen.model == "qwen3.5:9b"
    assert gen.text == "NEEDS_ENGINEER_REVIEW"
    assert gen.truncated is False


def test_generation_still_works_for_a_caller_that_has_no_tag():
    """An injected test double has no tag and should not invent one. What
    matters is that the real path stopped throwing it away."""
    assert synthesis.Generation(text="t", truncated=False).model == ""
