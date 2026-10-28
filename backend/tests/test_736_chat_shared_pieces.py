"""#736 (Stage D): the two chat engines are kept on purpose, so what they must SHARE is pinned.

`answer.answer` (the local pipeline) and `chat_claude_first.answer` (the Claude tool loop, owner
order 2026-09-27) are different architectures. They are one answer to the user only while three
things stay common: every document claim goes through `answer.verify_claims`, an image-only
citation is relabelled the same way, and Claude is reached only through the reasoning provider
(where `claude_spend.reserve` runs before every call), never through a socket module of its own.
These are read from the source, so a refactor that gives the Claude-first loop its own checker or
its own door to the network goes red. No model, no network, no document.
"""

from __future__ import annotations

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
SOCKET_MODULES = {
    "reader_transport",
    "market_transport",
    "model_transport",
    "notifications",
    "anthropic",
    "httpx",
    "requests",
    "urllib",
    "socket",
    "http",
}


def _tree(name: str) -> ast.Module:
    return ast.parse((APP / f"{name}.py").read_text(encoding="utf-8"))


def _called_names(tree: ast.AST) -> set[str]:
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            names.add(
                fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            )
    return names


def _imported(tree: ast.AST) -> set[str]:
    seen = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            seen.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            seen.update(a.name for a in node.names)
            if node.module:
                seen.add(node.module.split(".")[0])
    return seen


def test_both_engines_verify_claims_with_the_same_function():
    assert "verify_claims" in _called_names(_tree("answer"))
    assert "verify_claims" in _called_names(_tree("chat_claude_first"))


def test_the_claude_first_loop_relabels_image_only_citations_after_the_check():
    assert "_relabel_image_only_citations" in _called_names(_tree("chat_claude_first"))


def test_the_claude_first_loop_has_no_door_to_the_network_of_its_own():
    assert not (_imported(_tree("chat_claude_first")) & SOCKET_MODULES)


def test_the_claude_first_loop_reaches_claude_through_the_reasoning_provider():
    tree = _tree("chat_claude_first")
    assert "reasoning_provider" in _imported(tree)
    assert "reason" in _called_names(tree) or "stream" in _called_names(tree)
