"""Lock 3 (order 1.3, issue #1626): the switches merged with proof are ON by default.

The code default is what a machine with no .env runs. The list is the one the owner
approves on #1626; a switch not on it keeps its default.
"""

from __future__ import annotations

import pytest

from app.config import Settings

TURNED_ON = (
    "clause_review_enabled",
    "data_page_not_frontmatter_enabled",
    "datasheet_label_join_enabled",
    "datasheet_one_value_enabled",
    "deferred_value_is_query_enabled",
    "document_kind_enabled",
    "kind_chooses_rules_enabled",
    "nothing_read_fails_enabled",
    "page_read_by_reading_enabled",
    "playbook_presence_without_standard_enabled",
    "playbook_section_presence_enabled",
    "procedure_crs_fields_enabled",
    "procedure_path_enabled",
    "procedure_playbook_rows_enabled",
    "review_audit_report_enabled",
    "review_progress_bar_enabled",
    "transmittal_kit_enabled",
)

#: Each stays off for a stated reason (#1626): a known block, verdict power before Lock 1, or an egress gate.
STAYS_OFF = (
    "geometry_reader_enabled",
    "at_limit_precision_enabled",
    "crs_export_quality_enabled",
    "leading_dot_decimal_enabled",
    "percent_kind_check_enabled",
    "recommendation_queries_enabled",
    "session_expired_notice_enabled",
    "rule_auto_use_enabled",
    "tested_cards_decide_enabled",
    "one_checked_definition_enabled",
    "pdf_heading_detection_enabled",
    "answer_judge_enabled",
    "word_page_markers_enabled",
    "owner_approved_rules_decide_enabled",
    "equipment_from_title_block_enabled",
    "market_live_enabled",
    "standards_reader_enabled",
    "chat_web_enabled",
    "review_web_standards_enabled",
    "smtp_enabled",
    "claude_auto_approve_reviews_enabled",
)


@pytest.mark.parametrize("name", TURNED_ON)
def test_a_proven_switch_is_on_with_no_env_file(name):
    assert Settings.model_fields[name].default is True


@pytest.mark.parametrize("name", STAYS_OFF)
def test_a_blocked_switch_stays_off_with_no_env_file(name):
    assert Settings.model_fields[name].default is False


@pytest.mark.parametrize(
    "name", ("ai_applicability_enabled", "rule_parse_model_enabled")
)
def test_a_deleted_switch_is_gone(name):
    assert name not in Settings.model_fields


def test_the_lock3_pins_are_lifted_only_when_asked():
    from tests import env_isolation

    name = env_isolation.LOCK3_PINNED[0]
    assert Settings.model_fields[name].default is True
    held, lifted = Settings(_env_file=None), Settings(_env_file=None)
    env_isolation.isolate(held, env={})
    env_isolation.isolate(lifted, env={env_isolation.LIFT_ENV: "1"})
    assert getattr(held, name) is False
    assert getattr(lifted, name) is True


def test_an_egress_gate_is_never_a_lifted_pin():
    from tests import env_isolation

    assert not set(env_isolation.LOCK3_PINNED) & set(STAYS_OFF)
