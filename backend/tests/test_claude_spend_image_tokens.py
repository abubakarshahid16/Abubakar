"""Owner answer 4 (11 Nov 2026): a page image is counted by the published image rule, not as its base64 text.

Before: `claude_spend.metered` (and `agent_claude`'s own run meter, and the chat tool loop's reservation) counted
every character of an image block's base64 data at ~3 characters a token, about 13 times what the API bills, so a
run with page images met the USD 5 step cap at once. Now an image block counts width x height / 750 tokens after the
long-edge scale-down (at most one image's maximum), from the size in its PNG/JPEG header; an image whose size cannot
be read counts the maximum, never 0. Text counting, the caps and the settle-from-usage path are unchanged.
All images here are invented headers; no document, no network.
"""

from __future__ import annotations

import base64
import json
import struct
import zlib

import pytest

from app import agent_claude, claude_spend
from app import claude_image_tokens as cit
from app import reasoning_provider as rp
from app.config import settings

MODEL = "claude-sonnet-4-5"


def _png(width: int, height: int, pad: int = 0) -> bytes:
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    chunk = (
        struct.pack(">I", len(ihdr))
        + b"IHDR"
        + ihdr
        + struct.pack(">I", zlib.crc32(b"IHDR" + ihdr))
    )
    return b"\x89PNG\r\n\x1a\n" + chunk + b"\x00" * pad


def _jpeg(width: int, height: int, pad: int = 0) -> bytes:
    app0 = (
        b"\xff\xe0"
        + struct.pack(">H", 16)
        + b"JFIF\x00"
        + b"\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    )
    sof = (
        b"\xff\xc0"
        + struct.pack(">HBHHB", 17, 8, height, width, 3)
        + b"\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    )
    return b"\xff\xd8" + app0 + b"\xff\xff" + sof + b"\x00" * pad + b"\xff\xd9"


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _block(raw: bytes, media: str = "image/png") -> dict:
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": media, "data": _b64(raw)},
    }


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "claude_spend_log", tmp_path / "spend.jsonl")
    monkeypatch.setattr(settings, "claude_budget_usd_per_step", 5.0)
    monkeypatch.setattr(settings, "claude_budget_usd_total", 20.0)


# ------------------------------------------------------------------ the published rule


def test_an_image_costs_width_times_height_over_750():
    assert cit.image_tokens(1000, 1000) == 1_000_000 // 750 + 1
    assert cit.image_tokens(200, 150) == 41


def test_a_large_image_is_scaled_to_the_long_edge_limit_first():
    # 4000 x 2000 scales to 2576 x 1288 before it is counted (not 10 667 tokens, not the maximum)
    assert cit.image_tokens(4000, 2000) == 2576 * 1288 // 750 + 1
    assert cit.image_tokens(2000, 4000) == 1288 * 2576 // 750 + 1
    assert cit.image_tokens(4000, 2000) < cit.IMAGE_MAX_TOKENS


def test_one_image_never_counts_more_than_the_maximum():
    assert cit.image_tokens(2576, 2576) == cit.IMAGE_MAX_TOKENS
    assert cit.image_tokens(9000, 9000) == cit.IMAGE_MAX_TOKENS


@pytest.mark.parametrize(
    "size",
    [(0, 100), (100, 0), (-5, 10), (None, 10), ("100", "100"), (True, 10), (1.5, 2)],
)
def test_a_size_that_is_not_two_positive_whole_numbers_counts_the_maximum(size):
    assert cit.image_tokens(*size) == cit.IMAGE_MAX_TOKENS


def test_the_limits_are_the_published_largest():
    assert (
        cit.IMAGE_LONG_EDGE_PX,
        cit.IMAGE_MAX_TOKENS,
        cit.IMAGE_PIXELS_PER_TOKEN,
    ) == (2576, 4784, 750)


# ------------------------------------------------------------------ the size from the header


def test_the_size_is_read_from_a_png_header():
    assert cit.image_size(_b64(_png(1240, 1754, pad=500))) == (1240, 1754)
    assert cit.image_size(_png(7, 3)) == (7, 3)


def test_the_size_is_read_from_a_jpeg_header_width_first():
    assert cit.image_size(_b64(_jpeg(1700, 2200, pad=300))) == (1700, 2200)
    assert cit.image_size(_jpeg(3, 7)) == (3, 7)


@pytest.mark.parametrize(
    "data",
    [
        "",
        "not base64 at all !!",
        _b64(b"RIFF\x00\x00\x00\x00WEBPVP8 "),
        _b64(b"\x89PNG\r\n\x1a\n" + b"\x00" * 4),
        _b64(b"\xff\xd8\xff\xd9"),
        _b64(b"\xff\xd8\xff\xe0\x00\x10JFIF"),
        _b64(b"\xff\xd8\x00\x00"),
        None,
        12,
    ],
)
def test_a_header_that_cannot_be_read_gives_no_size(data):
    assert cit.image_size(data) is None


@pytest.mark.parametrize(
    "block",
    [
        _block(b"GIF89a\x10\x00\x10\x00", "image/gif"),
        {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": "@@@@"},
        },
        {
            "type": "image",
            "source": {"type": "url", "url": "https://example.invalid/x.png"},
        },
        {"type": "image", "source": {"type": "file", "file_id": "file_x"}},
        {"type": "image", "source": None},
    ],
)
def test_an_image_whose_size_cannot_be_read_counts_the_maximum_never_zero(block):
    assert cit.image_block_tokens(block) == cit.IMAGE_MAX_TOKENS


def test_a_readable_image_block_counts_by_its_size():
    assert cit.image_block_tokens(_block(_png(600, 900))) == cit.image_tokens(600, 900)


# ------------------------------------------------------------------ split_images


def test_with_no_image_the_count_is_exactly_as_before():
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "invented ünïcode text"},
                {"type": "tool_result", "tool_use_id": "t", "content": "x"},
            ],
        },
        {"role": "assistant", "content": "y"},
    ]
    stripped, tokens = cit.split_images(messages)
    assert tokens == 0
    for ascii_ in (True, False):
        assert json.dumps(stripped, ensure_ascii=ascii_) == json.dumps(
            messages, ensure_ascii=ascii_
        )
    assert cit.split_images("system words") == ("system words", 0)
    assert cit.split_images(None) == (None, 0)


def test_an_image_inside_a_tool_result_is_counted_once_by_its_size_not_its_text():
    image = _block(_png(1500, 2000, pad=200_000))
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "t",
                    "content": [{"type": "text", "text": "page"}, image],
                }
            ],
        }
    ]
    stripped, tokens = cit.split_images(messages)
    assert tokens == cit.image_tokens(1500, 2000)
    text = json.dumps(stripped)
    assert image["source"]["data"] not in text and len(text) < 300
    assert messages[0]["content"][0]["content"][1]["source"][
        "data"
    ]  # the request itself is not changed


# ------------------------------------------------------------------ metered (the three claude_api routes, the agent)


def _worst_reserved(monkeypatch, body: dict) -> float:
    seen: list[float] = []

    class _Stop(Exception):
        pass

    def fake_reserve(step, worst, **kw):
        seen.append(worst)
        raise _Stop

    monkeypatch.setattr(claude_spend, "reserve", fake_reserve)
    metered = claude_spend.metered(
        lambda *a, **k: {}, "image-step", keep_if=lambda _a: False
    )
    with pytest.raises(_Stop):
        metered("u", headers={}, body=body, timeout=1)
    return seen[0]


def _body(*content) -> dict:
    return {
        "model": MODEL,
        "max_tokens": 100,
        "system": "invented system words",
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": "invented question"}, *content],
            }
        ],
    }


def test_metered_counts_a_page_image_by_the_image_rule(monkeypatch):
    image = _block(
        _png(1700, 2200, pad=400_000)
    )  # a page-sized image, ~530 000 base64 characters
    with_image = _worst_reserved(monkeypatch, _body(image))
    text_only = _body()
    chars = len(json.dumps(text_only["messages"] + [], ensure_ascii=False)) + len(
        json.dumps(text_only["system"], ensure_ascii=False)
    )
    chars += (
        len(json.dumps({"type": "image"})) + 2
    )  # the image block without its source, and its ", "
    expected = claude_spend.worst_case_usd(
        MODEL, chars, 100, image_tokens=cit.image_tokens(1700, 2200)
    )
    assert with_image == pytest.approx(expected)
    as_text = claude_spend.worst_case_usd(
        MODEL, len(json.dumps(_body(image)["messages"])), 100
    )
    assert with_image < as_text / 10  # was about 13 times over the image rule


def test_metered_counts_an_unreadable_image_at_the_maximum(monkeypatch):
    image = {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/webp",
            "data": _b64(b"x" * 90),
        },
    }
    worst = _worst_reserved(monkeypatch, _body(image))
    no_image = _worst_reserved(monkeypatch, _body({"type": "image"}))
    assert worst - no_image == pytest.approx(
        claude_spend.worst_case_usd(MODEL, 0, 0, image_tokens=cit.IMAGE_MAX_TOKENS)
        - claude_spend.worst_case_usd(MODEL, 0, 0),
        rel=1e-3,
    )


def test_metered_counts_an_image_in_the_system_list(monkeypatch):
    body = {
        "model": MODEL,
        "max_tokens": 10,
        "messages": [],
        "system": [{"type": "text", "text": "s"}, _block(_jpeg(800, 600))],
    }
    worst = _worst_reserved(monkeypatch, body)
    stripped, tokens = cit.split_images(body["system"])
    chars = len(json.dumps([])) + len(json.dumps(stripped, ensure_ascii=False))
    assert tokens == cit.image_tokens(800, 600)
    assert worst == pytest.approx(
        claude_spend.worst_case_usd(MODEL, chars, 10, image_tokens=tokens)
    )


def test_metered_text_only_worst_case_is_unchanged(monkeypatch):
    body = _body()
    old = claude_spend.worst_case_usd(
        MODEL,
        len(json.dumps(body["messages"], ensure_ascii=False))
        + len(json.dumps(body["system"], ensure_ascii=False)),
        100,
    )
    assert _worst_reserved(monkeypatch, body) == old


def test_a_run_of_page_images_now_fits_under_the_unchanged_step_cap(monkeypatch):
    """The 11 Nov failure: three page-image calls each reserved ~USD 2 and crossed USD 5 before any was sent."""
    images = [_block(_png(1700, 2200, pad=400_000)) for _ in range(3)]
    body = _body(*images)
    body["max_tokens"] = 4000
    worst = _worst_reserved(monkeypatch, body)
    assert settings.claude_budget_usd_per_step == 5.0
    assert 3 * worst < 5.0
    assert (
        3 * claude_spend.worst_case_usd(MODEL, len(json.dumps(body["messages"])), 4000)
        > 5.0
    )


def test_settled_cost_still_comes_from_usage():
    usage = {"input_tokens": 1000, "output_tokens": 100}
    assert claude_spend.cost_usd(MODEL, usage) == pytest.approx(
        (1000 * 3.0 + 100 * 15.0) / 1_000_000
    )


# ------------------------------------------------------------------ agent_claude (its own run meter)


def test_the_agent_run_meter_counts_a_page_image_by_the_image_rule(monkeypatch):
    seen: list[float] = []

    class _Stop(Exception):
        pass

    class Meter:
        def check(self, worst):
            seen.append(worst)
            raise _Stop

    monkeypatch.setattr("app.claude_approved.carried", lambda: ("doc",))
    image = _block(_png(1700, 2200, pad=400_000))
    parts = {
        "messages": [{"role": "user", "content": [image]}],
        "system": "s",
        "tools": [],
    }
    with pytest.raises(_Stop):
        agent_claude._call(MODEL, parts, 100, None, None, meter=Meter())
    stripped, tokens = cit.split_images(parts["messages"])
    chars = len(json.dumps(stripped)) + len(json.dumps("s")) + len(json.dumps([]))
    assert seen == [
        pytest.approx(
            claude_spend.worst_case_usd(MODEL, chars, 100, image_tokens=tokens)
        )
    ]
    assert tokens == cit.image_tokens(1700, 2200)


def test_the_agent_fallback_cost_without_usage_counts_the_image_by_the_rule():
    image = _block(_png(1000, 1000, pad=300_000))
    body = {
        "messages": [{"role": "user", "content": [image]}],
        "system": None,
        "max_tokens": 50,
    }
    got = agent_claude._usd(MODEL, {}, body)
    stripped, _ = cit.split_images(body["messages"])
    chars = len(json.dumps(stripped)) + len(json.dumps(None))
    assert got == pytest.approx(
        claude_spend.worst_case_usd(
            MODEL, chars, 50, image_tokens=cit.image_tokens(1000, 1000)
        )
    )
    assert agent_claude._usd(
        MODEL, {"usage": {"input_tokens": 10, "output_tokens": 1}}, body
    ) == pytest.approx(
        claude_spend.cost_usd(MODEL, {"input_tokens": 10, "output_tokens": 1})
    )


# ------------------------------------------------------------------ reasoning_provider (chat tool loop, stream)


def test_a_page_image_part_counts_by_the_same_rule():
    assert rp.PageImage("image/png", "", 4000, 2000).tokens == cit.image_tokens(
        4000, 2000
    )
    assert rp.PageImage("image/png", "", 0, 10).tokens == cit.IMAGE_MAX_TOKENS


def test_the_chat_tool_loop_counts_images_in_messages_by_the_rule_and_never_fewer():
    image = _block(_png(1500, 1500, pad=200_000))
    messages = (
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "t", "content": [image]}
            ],
        },
    )
    placeholder = rp.PageImage("image/png", "", 100, 100)
    packet = rp.Packet(
        prompt="p", num_ctx=1, num_predict=1, messages=messages, images=(placeholder,)
    )
    chars, tokens = cit.packet_counts(packet, "p")
    assert tokens == cit.image_tokens(
        1500, 1500
    )  # the real image, not the small placeholder
    assert chars < 400  # its base64 text is not counted as characters
    big = rp.PageImage("image/png", "", 2576, 2576)
    packet = rp.Packet(
        prompt="p", num_ctx=1, num_predict=1, messages=messages, images=(big,)
    )
    assert cit.packet_counts(packet, "p")[1] == cit.IMAGE_MAX_TOKENS


def test_a_streamed_call_counts_its_images():
    image = rp.PageImage("image/png", _b64(_png(800, 800)), 800, 800)
    packet = rp.Packet(prompt="p", num_ctx=1, num_predict=1, images=(image,))
    assert cit.packet_counts(packet, "p") == (
        len(packet.system) + len("p"),
        cit.image_tokens(800, 800),
    )


def _provider_reserved(monkeypatch, call) -> list[float]:
    seen: list[float] = []

    class _Stop(Exception):
        pass

    def fake_reserve(step, worst, **kw):
        seen.append(worst)
        raise _Stop

    monkeypatch.setattr(settings, "claude_cache_dir", settings.data_dir / "cache")
    monkeypatch.setattr(settings, "reasoning_provider", "claude")
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-test-invented-0000")
    monkeypatch.setattr(settings, "standards_reader_enabled", True)
    monkeypatch.setattr(settings, "standards_reader_allow_public_egress", True)
    for name in (
        "STANDARDS_READER_ENABLED",
        "STANDARDS_READER_ALLOW_PUBLIC_EGRESS",
        "ANTHROPIC_API_KEY",
        "STANDARDS_READER_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(claude_spend, "reserve", fake_reserve)
    with pytest.raises(_Stop):
        call()
    return seen


def test_the_provider_reserves_a_tool_loop_image_by_the_rule(monkeypatch):
    image = _block(_png(1500, 1500, pad=200_000))
    messages = (
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "t", "content": [image]}
            ],
        },
    )
    packet = rp.Packet(
        prompt="p", num_ctx=1, num_predict=10, step="s", messages=messages
    )
    provider = rp.ClaudeProvider(MODEL, transport=lambda *a, **k: {})
    seen = _provider_reserved(monkeypatch, lambda: provider.reason(packet))
    stripped, tokens = cit.split_images(messages[0])
    prompt = provider._request(packet)[2]
    chars = len(packet.system) + len(prompt) + len(json.dumps(stripped))
    assert tokens == cit.image_tokens(1500, 1500) and chars < 1000
    assert seen == [
        pytest.approx(
            claude_spend.worst_case_usd(MODEL, chars, 10, image_tokens=tokens)
        )
    ]


def test_the_provider_reserves_a_streamed_image(monkeypatch):
    image = rp.PageImage("image/png", _b64(_png(800, 800)), 800, 800)
    packet = rp.Packet(prompt="p", num_ctx=1, num_predict=10, step="s", images=(image,))
    provider = rp.ClaudeProvider(MODEL, stream_transport=lambda *a, **k: iter(()))
    seen = _provider_reserved(
        monkeypatch, lambda: provider.stream(packet, lambda _t: None)
    )
    chars = len(packet.system) + len(provider._request(packet)[2])
    assert seen == [
        pytest.approx(
            claude_spend.worst_case_usd(
                MODEL, chars, 10, image_tokens=cit.image_tokens(800, 800)
            )
        )
    ]
