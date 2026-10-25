"""Order 189 part B: the answer-quality scores, by code only. Every passage and
answer here is INVENTED. No model runs."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
for sub in ("eval/answer_quality", "eval/p1ai", "eval"):
    sys.path.insert(0, str(REPO / sub))
import quality_scoring as qs  # noqa: E402

VIB = {
    "text": "Casing vibration shall not exceed 4.5 mm/s RMS when measured at the bearing housing."
}
SEAL = {"text": "A seal plan 53B is required for toxic service on every pump."}
NOISE = {
    "text": "The nameplate shall be stainless steel and fixed with rivets of the same material."
}
GOOD = (
    "The vibration limit is 4.5 mm/s RMS measured at the bearing housing [S1]. "
    "A seal plan 53B is required for toxic service [S2]."
)


def test_a_supported_answer_scores_full_on_faithfulness_and_citations():
    p = [VIB, SEAL]
    assert qs.faithfulness(GOOD, p) == 1.0
    assert qs.citation_recall(GOOD, p) == 1.0
    assert qs.citation_precision(GOOD, p) == 1.0


def test_a_figure_the_cited_passage_does_not_hold_makes_the_claim_unfaithful():
    bad = "The vibration limit is 7.1 mm/s RMS measured at the bearing housing [S1]."
    assert qs.faithfulness(bad, [VIB]) == 0.0


def test_a_claim_with_words_the_passage_lacks_is_unfaithful_even_with_no_figure():
    bad = "Pumps must be painted bright orange before delivery to the purchaser [S1]."
    assert qs.faithfulness(bad, [VIB]) == 0.0


def test_half_the_claims_unsupported_scores_half():
    mixed = (
        GOOD
        + " Pumps must be painted bright orange before delivery to the purchaser [S1]."
    )
    assert qs.faithfulness(mixed, [VIB, SEAL]) == pytest.approx(2 / 3)


def test_a_claim_without_a_citation_lowers_recall_not_precision():
    a = "The vibration limit is 4.5 mm/s RMS measured at the bearing housing [S1]. A seal plan 53B is required for toxic service."
    p = [VIB, SEAL]
    assert qs.citation_recall(a, p) == 0.5
    assert qs.citation_precision(a, p) == 1.0


def test_a_citation_to_the_wrong_passage_lowers_precision_and_faithfulness():
    a = "A seal plan 53B is required for toxic service [S1]."
    assert qs.citation_precision(a, [VIB, SEAL]) == 0.0
    assert qs.faithfulness(a, [VIB, SEAL]) == 0.0


def test_a_marker_past_the_last_passage_is_not_a_citation():
    a = "The vibration limit is 4.5 mm/s RMS measured at the bearing housing [S9]."
    assert qs.citation_recall(a, [VIB]) == 0.0


def test_a_refusal_has_no_score_not_a_zero():
    for fn in (qs.faithfulness, qs.citation_recall, qs.citation_precision):
        assert fn("INSUFFICIENT EVIDENCE", [VIB]) is None
    assert (
        qs.citation_precision(
            "The vibration limit is 4.5 mm/s RMS at the bearing housing.", [VIB]
        )
        is None
    )


def test_relevancy_is_the_share_of_expected_facts_and_forbidden_is_apart():
    a = "The limit is 4.5 mm/s."
    assert qs.response_relevancy(a, ["4.5 mm/s", "bearing housing"]) == 0.5
    assert qs.response_relevancy(a, []) is None
    assert qs.forbidden(a + " Old revision: 7.1 mm/s.", ["7.1 mm/s"]) == ["7.1 mm/s"]


def test_noise_sensitivity_counts_claims_resting_on_the_irrelevant_passage():
    gold = [VIB]
    noisy_context = [NOISE, VIB]
    clean_ans = (
        "The vibration limit is 4.5 mm/s RMS measured at the bearing housing [S2]."
    )
    noisy_ans = (
        clean_ans
        + " The nameplate shall be stainless steel and fixed with rivets of the same material [S1]."
    )
    assert qs.noise_sensitivity(clean_ans, gold, noisy_context) == 0.0
    assert qs.noise_sensitivity(noisy_ans, gold, noisy_context) == 0.5
    assert qs.noise_sensitivity("INSUFFICIENT EVIDENCE", gold, noisy_context) is None


def _agg(**over):
    base = {m: {"mean": 0.8, "n": 5} for m in qs.MEASURES}
    base["noise_sensitivity"] = {"mean": 0.2, "n": 5}
    base["forbidden_answers"] = []
    for k, v in over.items():
        base[k] = {"mean": v, "n": 5} if k in qs.MEASURES else v
    return base


def test_a_variant_equal_on_every_measure_is_kept():
    assert qs.keep_variant(_agg(), _agg()) == []


@pytest.mark.parametrize(
    "name,worse",
    [
        ("faithfulness", 0.79),
        ("response_relevancy", 0.5),
        ("citation_recall", 0.7),
        ("citation_precision", 0.6),
        ("noise_sensitivity", 0.3),
    ],
)
def test_a_variant_worse_on_any_one_measure_is_not_kept(name, worse):
    reasons = qs.keep_variant(_agg(), _agg(**{name: worse}))
    assert len(reasons) == 1 and reasons[0].startswith(name)


def test_a_variant_better_on_one_and_equal_elsewhere_is_kept():
    assert qs.keep_variant(_agg(), _agg(faithfulness=0.9, noise_sensitivity=0.1)) == []


def test_a_measure_with_no_value_blocks_the_variant():
    assert any(
        "no value" in r for r in qs.keep_variant(_agg(), _agg(citation_precision=None))
    )


def test_a_new_forbidden_answer_or_a_false_meet_blocks_the_variant():
    assert qs.keep_variant(_agg(), _agg(forbidden_answers=["Q3"]))
    assert qs.keep_variant(_agg(), _agg(), false_meets_variant=1)


def test_aggregate_reports_the_count_each_mean_is_made_from():
    rows = [
        qs.score_row(
            {"id": "a", "expected_answer_contains": ["4.5 mm/s"]},
            {"answer_type": "generated", "answer": GOOD, "passages": [VIB, SEAL]},
        ),
        qs.score_row(
            {"id": "b"},
            {"answer_type": "insufficient_evidence", "answer": None, "passages": []},
        ),
    ]
    agg = qs.aggregate(rows)
    assert agg["questions"] == 2
    assert agg["faithfulness"] == {"mean": 1.0, "n": 1}
    assert agg["noise_sensitivity"] == {"mean": None, "n": 0}


# ------------------------------------------------------------ prompt variants


def test_the_default_variant_is_the_unchanged_prompt_byte_for_byte():
    from app import answer, answer_prompts
    from app.config import settings

    assert settings.answer_prompt_variant == "default"
    got = answer_prompts.pick(
        False, answer.SYSTEM_PROMPT, answer.SYSTEM_PROMPT_VERIFIED
    )
    assert got == answer.SYSTEM_PROMPT


def test_a_variant_changes_only_the_instructions_and_unknown_names_fall_back(
    monkeypatch,
):
    from app import answer_prompts
    from app.config import settings

    base, quoting = "BASE", "QUOTING"
    for name in answer_prompts.VARIANTS:
        monkeypatch.setattr(settings, "answer_prompt_variant", name)
        got = answer_prompts.pick(False, base, quoting)
        if name == "quote_first":
            assert got == quoting
        elif name == "default":
            assert got == base
        else:
            assert got.startswith(base) and len(got) > len(base)
    monkeypatch.setattr(settings, "answer_prompt_variant", "no-such-variant")
    assert answer_prompts.pick(False, base, quoting) == base


def test_the_claude_lane_keeps_its_quoting_prompt_whatever_the_variant(monkeypatch):
    from app import answer_prompts
    from app.config import settings

    for name in answer_prompts.VARIANTS:
        monkeypatch.setattr(settings, "answer_prompt_variant", name)
        assert answer_prompts.pick(True, "BASE", "QUOTING") == "QUOTING"


def test_the_answer_call_sends_the_variant_prompt(monkeypatch):
    from app import answer, chat_model
    from app.config import settings

    seen = {}

    def fake_generate(system, prompt, **kw):
        seen["system"] = system
        return {"text": "x"}

    monkeypatch.setattr(chat_model, "generate", fake_generate)
    monkeypatch.setattr(answer, "claude_lane", lambda: False)
    monkeypatch.setattr(settings, "answer_prompt_variant", "check_figures")
    answer._call_model("p")
    assert (
        seen["system"].startswith(answer.SYSTEM_PROMPT)
        and "Before you write a number" in seen["system"]
    )
    monkeypatch.setattr(settings, "answer_prompt_variant", "default")
    answer._call_model("p")
    assert seen["system"] == answer.SYSTEM_PROMPT


def test_the_variant_is_one_of_the_settings_that_can_change_an_answer():
    from app.config import ANSWER_AFFECTING_SETTINGS

    assert "answer_prompt_variant" in ANSWER_AFFECTING_SETTINGS


# ------------------------------------------------------------------ the runner


def _runner():
    sys.path.insert(0, str(REPO / "eval" / "p1"))
    sys.path.insert(0, str(REPO / "eval" / "p1ai"))
    import run_aq

    return run_aq


def _q(qid, answerable=True, needles=("4.5 mm/s",)):
    return {
        "id": qid,
        "question": f"q {qid}",
        "answerable": answerable,
        "expected_answer_contains": list(needles),
        "forbidden_in_answer": [],
    }


def test_the_noise_is_two_other_passages_and_the_same_for_every_variant():
    aq = _runner()
    pool = [{"text": f"page {i}"} for i in range(10)]
    own = [pool[0], pool[1]]
    first = aq.noise_for(3, own, pool)
    assert len(first) == 2 and not any(p in own for p in first)
    assert aq.noise_for(3, own, pool) == first


def test_the_corpus_pool_is_every_page_of_the_invented_corpus():
    aq = _runner()
    import corpus as p1_corpus

    pool = aq.corpus_pool()
    assert len(pool) == sum(len(pages) for pages in p1_corpus.DOCS.values())
    assert all(p["text"] and p["filename"] in p1_corpus.DOCS for p in pool)


def test_a_run_asks_the_noisy_question_only_for_an_answered_answerable_one():
    aq = _runner()
    noisy_calls = []

    def ask(question, qid):
        if qid == "refused":
            return {
                "answer_type": "insufficient_evidence",
                "answer": None,
                "passages": [],
            }
        return {"answer_type": "generated", "answer": GOOD, "passages": [VIB, SEAL]}

    def noisy_ask(question, passages):
        noisy_calls.append(len(passages))
        return (
            "The vibration limit is 4.5 mm/s RMS measured at the bearing housing [S3]."
        )

    pool = [{"text": f"other {i}"} for i in range(6)]
    rows = aq.run_variant(
        [_q("a"), _q("refused"), _q("unans", answerable=False)],
        ask,
        noisy_ask,
        pool,
        say=lambda *_: None,
    )
    assert noisy_calls == [4]
    by = {r["id"]: r for r in rows}
    assert by["a"]["noise_sensitivity"] == 0.0
    assert (
        by["refused"]["noise_sensitivity"] is None
        and by["refused"]["faithfulness"] is None
    )


def test_the_comparison_keeps_a_variant_only_when_it_is_not_worse_anywhere():
    aq = _runner()

    def rows(variant_answer):
        def ask(question, qid):
            return {
                "answer_type": "generated",
                "answer": variant_answer,
                "passages": [VIB, SEAL],
            }

        return aq.run_variant(
            [_q("a")],
            ask,
            lambda q, p: variant_answer,
            [{"text": "n1"}, {"text": "n2"}],
            say=lambda *_: None,
        )

    base = qs.aggregate(rows(GOOD))
    better_same = qs.aggregate(rows(GOOD))
    worse = qs.aggregate(
        rows(
            "The vibration limit is 7.1 mm/s RMS measured at the bearing housing [S1]."
        )
    )
    verdicts = aq.compare({"default": base, "same": better_same, "bad": worse})
    assert verdicts["default"] == [] and verdicts["same"] == [] and verdicts["bad"]
    assert any("figure" in r or "faithfulness" in r for r in verdicts["bad"])
    text = aq.markdown(
        {"default": base, "same": better_same, "bad": worse}, verdicts, "m", 1
    )
    assert "| same |" in text and "YES" in text and "| bad |" in text and "no |" in text


def test_a_new_answer_with_a_figure_the_page_lacks_blocks_the_variant_even_if_means_tie():
    base = _agg()
    base["ungrounded_answers"] = []
    var = _agg()
    var["ungrounded_answers"] = ["Q9"]
    assert any("Q9" in r for r in qs.keep_variant(base, var))


# ------------------------------------------------------- the workflow file itself


def _workflow() -> dict:
    import yaml

    path = REPO / ".github" / "workflows" / "answer-quality-cpu.yml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_the_workflow_starts_by_hand_only_and_names_the_macs_model_without_a_default():
    on = _workflow()[True]  # "on" parses as True
    assert set(on) == {"workflow_dispatch"}
    inputs = on["workflow_dispatch"]["inputs"]
    assert inputs["model"]["required"] is True and "default" not in inputs["model"]
    assert (
        inputs["ollama_version"]["required"] is True
        and "default" not in inputs["ollama_version"]
    )


def test_the_workflow_uses_no_secret_and_no_cloud_model():
    text = (REPO / ".github" / "workflows" / "answer-quality-cpu.yml").read_text(
        encoding="utf-8"
    )
    assert "secrets." not in text
    assert "ANTHROPIC" not in text and "api.anthropic" not in text
    steps = {s.get("name", ""): s for s in _workflow()["jobs"]["score"]["steps"]}
    env = steps["Ask the invented questions with each variant"]["env"]
    assert env["REASONING_PROVIDER"] == "ollama"
    assert env["STANDARDS_READER_ENABLED"] == "false"
    assert env["STANDARDS_READER_ALLOW_PUBLIC_EGRESS"] == "false"
    assert "inputs.model" in env["ANSWER_MODEL"]


def test_the_workflow_reads_only_the_invented_questions_and_the_installer_service_is_stopped():
    steps = _workflow()["jobs"]["score"]["steps"]
    run = "\n".join(s.get("run", "") for s in steps)
    assert "eval/answer_quality/run_aq.py" in run
    assert "systemctl disable --now ollama" in run and "is not version" in run
    for forbidden in ("hidden-exam", "Engineering Deliverables", "upload", "/data/"):
        assert forbidden not in run
