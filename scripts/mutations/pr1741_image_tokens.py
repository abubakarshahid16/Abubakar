"""Owner answer 4 (11 Nov 2026): a page image is counted by the published image rule (width x height / 750 after
the long-edge scale-down, at most one image's maximum; an unreadable size counts the maximum), not as its base64
text, in the worst-case reservation. `claude_spend.py` is in the danger zone (rule 6); `claude_image_tokens.py` is
the count it calls. Ids M1741-01.. (named after the PR, rule 12)."""

from __future__ import annotations

from ._base import APP, Mutation

_I = APP / "claude_image_tokens.py"
_S = APP / "claude_spend.py"
_T = "tests/test_claude_spend_image_tokens.py"
_TAGS = ("budget", "critical")


def _m(n: str, desc: str, path, anchor: str, repl: str, kw: str) -> Mutation:
    return Mutation(
        id=f"M1741-{n}",
        phase=1741,
        description=desc,
        path=path,
        anchor=anchor,
        replacement=repl,
        target=_T,
        keyword=kw,
        tags=_TAGS,
    )


MUTATIONS: tuple[Mutation, ...] = (
    _m(
        "01",
        "a large image is counted at its full size (the long-edge scale-down is dropped)",
        _I,
        "    if long_edge > IMAGE_LONG_EDGE_PX:\n",
        "    if False:\n",
        "scaled_to_the_long_edge",
    ),
    _m(
        "02",
        "a zero or negative image size counts 0 tokens instead of the maximum",
        _I,
        "    if w <= 0 or h <= 0:\n        return IMAGE_MAX_TOKENS\n",
        "    if w <= 0 or h <= 0:\n        return 0\n",
        "zero_or_negative_size",
    ),
    _m(
        "03",
        "a size that is not two whole numbers is counted as if it were one",
        _I,
        "    if not all(isinstance(v, int) and not isinstance(v, bool) for v in (width, height)):\n"
        "        return IMAGE_MAX_TOKENS\n",
        "",
        "not_whole_numbers",
    ),
    _m(
        "04",
        "one image may count more than the published maximum (the cap is dropped)",
        _I,
        "    return min(IMAGE_MAX_TOKENS, w * h // IMAGE_PIXELS_PER_TOKEN + 1)\n",
        "    return w * h // IMAGE_PIXELS_PER_TOKEN + 1\n",
        "never_counts_more_than_the_maximum",
    ),
    _m(
        "05",
        "the image count rounds down, below the API's",
        _I,
        "    return min(IMAGE_MAX_TOKENS, w * h // IMAGE_PIXELS_PER_TOKEN + 1)\n",
        "    return min(IMAGE_MAX_TOKENS, w * h // IMAGE_PIXELS_PER_TOKEN)\n",
        "width_times_height_over_750",
    ),
    _m(
        "06",
        "an image whose size cannot be read counts 0 tokens (it would leave unbudgeted)",
        _I,
        "            return image_tokens(*size)\n    return IMAGE_MAX_TOKENS\n",
        "            return image_tokens(*size)\n    return 0\n",
        "cannot_be_read_counts_the_maximum",
    ),
    _m(
        "07",
        "a JPEG's width and height are read the wrong way round",
        _I,
        '            return int.from_bytes(raw[i + 7 : i + 9], "big"), int.from_bytes(\n'
        '                raw[i + 5 : i + 7], "big"\n            )\n',
        '            return int.from_bytes(raw[i + 5 : i + 7], "big"), int.from_bytes(\n'
        '                raw[i + 7 : i + 9], "big"\n            )\n',
        "jpeg_header_width_first",
    ),
    _m(
        "08",
        "a PNG's width and height are read the wrong way round",
        _I,
        '        return int.from_bytes(raw[16:20], "big"), int.from_bytes(raw[20:24], "big")\n',
        '        return int.from_bytes(raw[20:24], "big"), int.from_bytes(raw[16:20], "big")\n',
        "png_header",
    ),
    _m(
        "09",
        "an image's base64 text is ALSO counted as prompt characters (the 13x over-count is back)",
        _I,
        '                return {k: walk(v) for k, v in node.items() if k != "source"}\n',
        "                return {k: walk(v) for k, v in node.items()}\n",
        "page_image_by_the_image_rule",
    ),
    _m(
        "10",
        "an image block is not counted at all",
        _I,
        "                tokens += image_block_tokens(node)\n",
        "                pass\n",
        "unreadable_image_at_the_maximum",
    ),
    _m(
        "11",
        "an image inside a list (a tool_result's content) is not found",
        _I,
        "            return [walk(v) for v in node]\n",
        "            return node\n",
        "inside_a_tool_result",
    ),
    _m(
        "12",
        "the chat tool loop counts fewer image tokens than its placeholder says",
        _I,
        "        declared = max(declared, in_messages)\n",
        "        declared = in_messages\n",
        "never_fewer",
    ),
    _m(
        "13",
        "the metered review routes reserve no image tokens",
        _S,
        "        worst = worst_case_usd(model, prompt_chars, cap, image_tokens=images)\n",
        "        worst = worst_case_usd(model, prompt_chars, cap)\n",
        "metered_counts",
    ),
)
