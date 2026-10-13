"""#922: small correctness defects found in the owner's full-code audit,
fixed one at a time. Invented values only.
"""
from __future__ import annotations

import ast

from app import analysis, classification, claude_budget, config

# ------------------------------------------------------------- A6: dashes

def test_an_en_dash_project_number_is_the_same_identity_as_a_hyphenated_one():
    """`_identity` strips every non-alphanumeric character after folding
    dashes, so this alone would pass even with the broken regex (both a
    hyphen and an en-dash vanish either way) - kept to document the field's
    real use, with `_clean` below carrying the actual proof."""
    assert classification._identity("RFP–1234567") == classification._identity("RFP-1234567")  # noqa: RUF001


def test_an_em_dash_and_a_figure_dash_also_fold_to_hyphen():
    for dash in ("–", "—", "‒", "―", "‐", "‑"):  # noqa: RUF001 - the dashes under test
        assert classification._clean(f"RFP{dash}1234567") == "RFP-1234567"


def test_a_literal_question_mark_is_not_touched_its_not_a_dash():
    assert classification._clean("RFP?1234567") == "RFP?1234567"


# ------------------------------------------ A8: config.py watch_* defined twice

def _field_lines(source: str, name: str) -> list[int]:
    """Every line a `Settings` class defines `name: ... = ...` at the top
    (class-body) level - an AST walk, not a grep, so a docstring or comment
    that happens to mention the name is never counted."""
    tree = ast.parse(source)
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Settings":
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and getattr(stmt.target, "id", None) == name:
                    lines.append(stmt.lineno)
    return lines


def test_watch_folder_settings_are_defined_exactly_once():
    import inspect
    source = inspect.getsource(config)
    for name in ("watch_folder", "watch_interval_seconds", "watch_owner_email"):
        assert len(_field_lines(source, name)) == 1, (
            f"{name} is defined more than once in Settings - the first copy is dead "
            "(Python keeps only the last), and a reader editing the dead one changes nothing")


# -------------------------------------------- A8: config_version omits AI settings

def test_the_ai_settings_the_audit_named_are_in_the_answer_affecting_list():
    for name in ("ai_task_model", "datasheet_ai_reader", "match_engine",
                "ai_applicability_enabled", "applicability_reasoning_enabled"):
        assert name in config.ANSWER_AFFECTING_SETTINGS, name


def test_changing_the_ai_reader_changes_the_stamped_version(monkeypatch):
    before = config.config_version()
    monkeypatch.setattr(config.settings, "datasheet_ai_reader", "ollama")
    assert config.config_version() != before


def test_changing_the_match_engine_changes_the_stamped_version(monkeypatch):
    before = config.config_version()
    monkeypatch.setattr(config.settings, "match_engine", "claude")
    assert config.config_version() != before


# ---------------------------------- A8: analysis.py names defined twice (95/315 etc)

def _module_level_names(source: str, name: str) -> list[int]:
    """Every module-level line that (re)defines `name` - a plain assignment
    or a `def` - so a duplicate function or constant is counted the same
    way. Nested defs (inside another function) are not module level and are
    not counted."""
    tree = ast.parse(source)
    lines = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", None) == name for t in node.targets):
            lines.append(node.lineno)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            lines.append(node.lineno)
    return lines


def test_quick_passages_is_comprehensive_and_synthesise_are_each_defined_once():
    """A8/#922 item 3: the audit found QUICK_PASSAGES, is_comprehensive and
    _synthesise each defined twice (95/315, 98/349, 759/797 at main a206fc2).
    Python keeps only the LAST definition of a module-level name - the first
    copy of each was dead code, invisible to every caller, that a future
    editor could "fix" for nothing."""
    import inspect
    source = inspect.getsource(analysis)
    for name in ("QUICK_PASSAGES", "is_comprehensive", "_synthesise"):
        lines = _module_level_names(source, name)
        assert len(lines) == 1, f"{name} is defined {len(lines)} times: lines {lines}"


def test_summary_still_calls_the_surviving_synthesise(monkeypatch):
    """Proves the de-duplication kept the function `summary()` actually
    calls, not an unrelated unreachable one."""
    calls = []
    monkeypatch.setattr(analysis, "_synthesise",
                        lambda *a, **k: calls.append((a, k)) or object())
    monkeypatch.setattr(analysis, "gather", lambda *a, **k: ([], {}))
    monkeypatch.setattr(analysis.synthesis, "summary_to_api", lambda result: {"summary": "x"})
    analysis.summary("q", scope=None, limit=8)
    assert len(calls) == 1


# ------------------------------------- A8: one Claude price table, not two

def test_claude_budget_has_no_second_price_table():
    assert not hasattr(claude_budget, "PRICE_PER_MILLION")


# --------------------------------------------- A8: the search.py reader note

def test_the_relevance_floor_comment_names_the_constant_not_a_stale_number():
    import inspect

    from app import search
    source = inspect.getsource(search)
    assert "-3.0 floor" not in source
