"""#438: the synthesis log lines reach the system's log file.

WHAT WAS WRONG. `synthesis.py` logged under the old product codename's logger.
`errors.logger()` configures only `rag_intelligence` (with `propagate = False`)
since the rename, so every synthesis call record - stage, passage count,
prompt tokens, refusal - went nowhere: the one record kept of how a summary
was produced was silently dropped.
"""
from __future__ import annotations

from app import errors, synthesis
from app.config import settings


def test_a_synthesis_call_record_lands_in_the_log_file(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    errors.logger()
    synthesis._Call(stage="collection_map", passage_count=3, prompt_tokens=120,
                    raw_completion="x" * 40).record()
    for handler in errors.logger().handlers:
        handler.flush()
    text = (tmp_path / "logs" / "rag-intelligence.log").read_text(encoding="utf-8")
    assert "synthesis stage=collection_map passages=3 prompt_tokens=120" in text


def test_the_synthesis_logger_is_a_child_of_the_configured_one():
    assert synthesis._log.name.startswith(errors.logger().name + ".")
