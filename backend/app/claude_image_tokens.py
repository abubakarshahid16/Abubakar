"""How many input tokens an image costs, for `claude_spend`'s worst-case reservation (owner answer 4, 11 Nov 2026).

A page image used to be counted as the characters of its base64 text, about 13 times what the API bills, so a run
with page images met the USD 5 step cap at once. The fix is the count, not the cap. Anthropic's published vision rule
(Claude API docs, "Vision"; the claude-api skill, high-resolution tier): an image costs about width x height / 750
tokens AFTER the API scales it down to fit its long-edge limit, and one image costs at most a fixed number of tokens.
2576 px and 4784 tokens are the LARGEST limits of any current model (older models scale further down, to 1568 px and
about 1600 tokens), so both err toward refusing. The size is read from the PNG or JPEG header with no image library;
an image whose size cannot be read counts the maximum, never 0. Part of the rule 6 danger zone with `claude_spend`.
"""

from __future__ import annotations

import base64
import binascii
import json

#: The longest edge, in pixels, any model keeps; a larger image is scaled down to it before it is counted.
IMAGE_LONG_EDGE_PX = 2576
#: The most one image can cost, in tokens: also the count for an image whose size cannot be read (the safe side).
IMAGE_MAX_TOKENS = 4784
#: Pixels per token in the published rule.
IMAGE_PIXELS_PER_TOKEN = 750

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
#: JPEG start-of-frame markers (baseline, progressive, lossless, arithmetic); each carries the frame's height and width.
_JPEG_SOF = frozenset(
    {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
)
#: JPEG markers with no length field after them (TEM, RST0-7, SOI); EOI (0xD9) ends the image.
_JPEG_STANDALONE = frozenset({0x01, *range(0xD0, 0xD9)})


def image_tokens(width, height) -> int:
    """Tokens one image costs by the published rule: scaled to fit `IMAGE_LONG_EDGE_PX` on its long edge, then
    width x height / 750 (plus one, so never below the API's rounding), never more than `IMAGE_MAX_TOKENS`. A size
    that is not two positive whole numbers counts as `IMAGE_MAX_TOKENS`, never as 0."""
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in (width, height)):
        return IMAGE_MAX_TOKENS
    w, h = width, height
    if w <= 0 or h <= 0:
        return IMAGE_MAX_TOKENS
    long_edge = max(w, h)
    if long_edge > IMAGE_LONG_EDGE_PX:
        # Round each scaled edge UP, so the count never falls below the API's.
        w = -(-w * IMAGE_LONG_EDGE_PX // long_edge)
        h = -(-h * IMAGE_LONG_EDGE_PX // long_edge)
    return min(IMAGE_MAX_TOKENS, w * h // IMAGE_PIXELS_PER_TOKEN + 1)


def _jpeg_size(raw: bytes) -> tuple[int, int] | None:
    i = 2
    while i + 1 < len(raw):
        if raw[i] != 0xFF:
            return None
        marker = raw[i + 1]
        if marker == 0xFF:  # a fill byte before the marker
            i += 1
            continue
        if marker in _JPEG_STANDALONE:
            i += 2
            continue
        # The end of the image, or the data cut short, before any frame.
        if marker == 0xD9 or i + 4 > len(raw):
            return None
        length = int.from_bytes(raw[i + 2 : i + 4], "big")
        if marker in _JPEG_SOF:
            if length < 7 or i + 9 > len(raw):
                return None
            return int.from_bytes(raw[i + 7 : i + 9], "big"), int.from_bytes(
                raw[i + 5 : i + 7], "big"
            )
        if length < 2:
            return None
        i += 2 + length
    return None


def image_size(data) -> tuple[int, int] | None:
    """(width, height) in pixels from a PNG or JPEG header, given the image as base64 text or as bytes; None when the
    data is not one of those two or its header cannot be read. Reads the header only; needs no image library."""
    raw = data
    if isinstance(data, str):
        try:
            raw = base64.b64decode(data, validate=False)
        except (binascii.Error, ValueError):
            return None
    if not isinstance(raw, (bytes, bytearray)):
        return None
    raw = bytes(raw)
    if raw.startswith(_PNG_SIGNATURE):
        if len(raw) < 24 or raw[12:16] != b"IHDR":
            return None
        return int.from_bytes(raw[16:20], "big"), int.from_bytes(raw[20:24], "big")
    if raw.startswith(b"\xff\xd8"):
        return _jpeg_size(raw)
    return None


def image_block_tokens(block) -> int:
    """Tokens of one Messages API image block: by the published rule from the size in its base64 data's header, else
    (a url or file source, another format, a header that cannot be read) `IMAGE_MAX_TOKENS`."""
    source = block.get("source") if isinstance(block, dict) else None
    if isinstance(source, dict) and source.get("type") == "base64":
        size = image_size(source.get("data"))
        if size is not None:
            return image_tokens(*size)
    return IMAGE_MAX_TOKENS


def split_images(value):
    """`(value without image data, image tokens)`. Every image block (a dict with `"type": "image"` and a `source`)
    anywhere in `value` (messages, a tool_result's content, a system list) is counted by `image_block_tokens` and its
    `source` left out of the copy, so its base64 text is not ALSO counted as prompt characters. Everything else is
    copied as it is: with no image in it, the copy serialises to exactly the same characters as `value`."""
    tokens = 0

    def walk(node):
        nonlocal tokens
        if isinstance(node, dict):
            if node.get("type") == "image" and "source" in node:
                tokens += image_block_tokens(node)
                return {k: walk(v) for k, v in node.items() if k != "source"}
            return {k: walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        if isinstance(node, tuple):
            return tuple(walk(v) for v in node)
        return node

    stripped = walk(value)
    return stripped, tokens


def json_counts(parts, *, ensure_ascii: bool = True) -> tuple[int, int]:
    """(characters, image tokens) of `parts`: the sum of each part's JSON (`default=str`) with its image blocks
    counted by the rule (`split_images`), not as base64 text. With no image, the characters are exactly as before."""
    stripped, tokens = split_images(list(parts))
    chars = sum(
        len(json.dumps(p, ensure_ascii=ensure_ascii, default=str)) for p in stripped
    )
    return chars, tokens


def packet_counts(packet, prompt: str) -> tuple[int, int]:
    """(prompt characters, image tokens) for one single or streamed `reasoning_provider` call: `packet.system`,
    `prompt` and each of `packet.messages` (`json_counts`). With `messages` set (not None), `packet.images` is only an
    accounting placeholder for images that ride inside `messages` (none of them is sent), so the larger of the two
    counts, never both and never fewer; without `messages`, `packet.images` is what is sent."""
    chars, in_messages = json_counts(packet.messages or ())
    declared = sum(image.tokens for image in packet.images)
    if packet.messages is not None:
        declared = max(declared, in_messages)
    return len(packet.system) + len(prompt) + chars, declared
