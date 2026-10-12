"""#674: P1-AI, the scored model tier. No model runs here: the answers are
invented dicts shaped like `chat.ask`'s, and the runner is driven with a fake
`ask`. Every document and standard is INVENTED (the P1 corpus).

Mutations: M4601-M4630 (scripts/mutations/w4b_674_p1_ai.py).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from app import heavy_lock
from app.config import settings

REPO = Path(__file__).resolve().parents[2]
for sub in ("eval/p1ai", "eval/p1", "eval"):
    sys.path.insert(0, str(REPO / sub))
import run_p1ai  # noqa: E402
import scoring  # noqa: E402

QS = json.loads((REPO / "eval" / "p1ai" / "questions.json").read_text(encoding="utf-8"))["questions"]
BY_ID = {q["id"]: q for q in QS}


def passage(text, doc="STD-A-001.pdf", page=3, section="4.1 Vibration"):
    return {"text": text, "filename": doc, "page_start": page, "page_end": page, "section": section}


def generated(answer, *passages, cited=(1,), removed=0):
    return {"answer_type": "generated", "answer": answer, "passages": list(passages),
            "cited": list(cited), "seconds": 1.0, "reason": None,
            "numbers_unsupported": ["x"] * removed}


def refused(kind="insufficient_evidence"):
    return {"answer_type": kind, "answer": None, "passages": [], "cited": [], "seconds": 1.0,
            "reason": "no evidence"}


def scored(qid, result):
    from run_eval import score_one
    q = BY_ID[qid]
    row = score_one({**q}, result, asked=q["question"])
    row["category"] = q["category"]
    return scoring.score_row(q, row, result)


VIB = passage("4.1 Vibration measured at the bearing housing shall not exceed 3.0 mm/s RMS during continuous operation.")


# ------------------------------------------------------------ figures, checked apart

def test_a_figure_with_its_unit_on_the_cited_page_is_grounded():
    assert scoring.ungrounded_figures("The limit is 3.0 mm/s [S1].", [VIB], [VIB]) == []


def test_a_figure_the_page_does_not_hold_is_reported():
    assert scoring.ungrounded_figures("The limit is 4.5 mm/s [S1].", [VIB], [VIB]) == ["4.5 mm/s"]


def test_the_right_number_in_the_wrong_unit_is_reported():
    pct = passage("6.1 Accumulation shall not exceed 10 % of the design pressure for a single relief device.")
    assert scoring.ungrounded_figures("It is 10 psi [S1].", [pct], [pct]) == ["10 psi"]
    assert scoring.ungrounded_figures("It is 10 % of the design pressure [S1].", [pct], [pct]) == []
    assert scoring.ungrounded_figures("It is 10 percent [S1].", [pct], [pct]) == []


def test_a_unit_in_a_table_rows_label_grounds_a_bare_cell():
    row = passage("Table 3 Worked example\nAllowable accumulation, psi (kPa)  10.0 (69)", page=2, section="Table 3")
    assert scoring.ungrounded_figures("It is 10 psi [S1].", [row], [row]) == []
    assert scoring.ungrounded_figures("It is 10 % [S1].", [row], [row]) == ["10 percent"]


def test_a_dropped_minus_sign_is_a_different_figure():
    cold = passage("3.1 The lowest design temperature for outdoor equipment shall be -29 degC.")
    assert scoring.ungrounded_figures("The lowest is -29 degC [S1].", [cold], [cold]) == []
    assert scoring.ungrounded_figures("The lowest is 29 degC [S1].", [cold], [cold]) == ["29 degc"]


def test_a_decimal_comma_on_the_page_matches_a_decimal_point_in_the_answer():
    drift = passage("5.2 Zero drift shall stay within -0,5 kPa to +0,5 kPa per year.")
    assert scoring.ungrounded_figures("Within 0.5 kPa per year [S1].", [drift], [drift]) == []


def test_a_sentence_is_held_to_the_passage_it_cites_not_to_another_one():
    a, b = passage("Limit is 3.0 mm/s."), passage("Limit is 6.0 mm/s.", doc="STD-K-010.pdf")
    assert scoring.ungrounded_figures("It is 6.0 mm/s [S1].", [a, b], [a, b]) == ["6.0 mm/s"]
    assert scoring.ungrounded_figures("It is 6.0 mm/s [S2].", [a, b], [a, b]) == []


def test_a_sentence_with_no_marker_is_held_to_the_passages_the_answer_cited():
    a, b = passage("Limit is 3.0 mm/s."), passage("Limit is 6.0 mm/s.")
    assert scoring.ungrounded_figures("It is 6.0 mm/s.", [a, b], [a]) == ["6.0 mm/s"]


def test_reference_numbers_and_ids_are_not_measurements_the_page_must_state():
    p = passage("STD-A-001 Revision 1. 4.1 The limit is 3.0 mm/s.")
    assert scoring.ungrounded_figures("STD-A-001 clause 4.1 says 3.0 mm/s [S1].", [p], [p]) == []


def test_the_checker_does_not_use_the_applications_own_figure_filter(monkeypatch):
    """If the exam called `answer.ground_numbers`, weakening that filter would
    weaken the exam by the same amount and nothing would turn red."""
    from app import answer

    def boom(*a, **k):
        raise AssertionError("the exam called the filter it tests")

    monkeypatch.setattr(answer, "ground_numbers", boom)
    monkeypatch.setattr(answer, "figure_check", boom)
    assert scoring.ungrounded_figures("It is 4.5 mm/s [S1].", [VIB], [VIB]) == ["4.5 mm/s"]


# ------------------------------------------------------------------------ facts

def test_facts_ignore_citation_markers_percent_wording_and_decimal_commas():
    assert scoring.facts_present("About 10 % of the design pressure [S1].", ["10 percent"])
    assert scoring.facts_present("Within 0,5 kPa [S1]", ["0.5 kPa"])
    assert not scoring.facts_present("About 12 percent", ["10 percent"])
    assert scoring.forbidden_present("it is 10 psi", ["psi", "kpa"]) == ["psi"]


# ---------------------------------------------------------------------- the rows

def test_a_right_cited_grounded_answer_passes():
    r = scored("PAI-01", generated("The vibration limit is 3.0 mm/s RMS [S1].", VIB))
    assert (r["passed"], r["figures_ok"], r["facts_ok"], r["clause_ok"]) == (True, True, True, True)


def test_a_wrong_figure_fails_and_is_listed():
    r = scored("PAI-01", generated("The vibration limit is 4.5 mm/s [S1].", VIB))
    assert r["passed"] is False and r["figures_ok"] is False and r["figures_ungrounded"] == ["4.5 mm/s"]
    # The expected fact is there, with an invented second figure beside it: still a fail.
    extra = scored("PAI-01", generated("The limit is 3.0 mm/s, tested at 7 bar [S1].", VIB))
    assert extra["facts_ok"] is True and extra["figures_ok"] is False and extra["passed"] is False


def test_a_right_figure_from_the_wrong_revision_is_a_guess_that_fails():
    old = passage("4.1 Vibration shall not exceed 2.5 mm/s RMS.", doc="STD-A-001-REV0.pdf", page=1)
    r = scored("PAI-01", generated("The limit is 2.5 mm/s [S1].", old))
    assert r["passed"] is False and r["forbidden_found"] == ["2.5 mm/s"] and r["guessed"] is True


def test_the_wrong_clause_fails_even_with_the_right_figure():
    off = passage(VIB["text"], section="4.2 Readings")
    r = scored("PAI-01", generated("The limit is 3.0 mm/s [S1].", off))
    assert r["clause_ok"] is False and r["passed"] is False and r["figures_ok"] is True


def test_the_unit_trap_answered_in_psi_fails():
    pct = passage("6.1 Accumulation shall not exceed 10 % of the design pressure.", doc="STD-P-014.pdf",
                  page=1, section="6.1 Accumulation")
    good = scored("PAI-15", generated("At most 10 % of the design pressure [S1].", pct))
    assert good["passed"] is True
    row = passage("Allowable accumulation, psi (kPa)  10.0 (69)", doc="STD-P-014.pdf", page=2, section="Table 3")
    bad = scored("PAI-15", generated("At most 10 psi [S1].", row))
    assert bad["passed"] is False and bad["forbidden_found"] == ["psi"]


def test_could_not_read_on_an_answerable_question_costs_a_point_but_is_not_a_guess():
    r = scored("PAI-01", refused())
    assert r["passed"] is False and r["could_not_read"] is True and r["guessed"] is False


def test_a_question_the_corpus_cannot_answer_passes_only_when_it_is_refused():
    assert scored("PAI-23", refused())["passed"] is True
    r = scored("PAI-23", generated("The pipework is red [S1].", VIB))
    assert r["passed"] is False and r["guessed"] is True


def test_a_refusal_caused_by_the_token_budget_is_not_a_correct_refusal():
    cut = {**refused(), "truncated": True}
    r = scored("PAI-23", cut)
    assert r["length_limited"] is True and r["passed"] is False


def test_a_model_that_did_not_answer_is_never_a_pass_or_a_refusal():
    r = scored("PAI-23", refused("model_unavailable"))
    assert r["model_unavailable"] is True and r["passed"] is False


def test_the_figures_the_models_text_lost_to_the_filter_are_reported_apart():
    r = scored("PAI-01", generated("The limit is 3.0 mm/s [S1].", VIB, removed=2))
    assert r["model_figures_removed"] == 2 and r["passed"] is True


def test_the_summary_counts_each_failure_kind_and_the_time_per_question():
    rows = [scored("PAI-01", generated("It is 3.0 mm/s [S1].", VIB)),
            scored("PAI-02", generated("It is 4.5 mm/s [S1].", VIB)),
            scored("PAI-23", generated("It is red [S1].", VIB)),
            scored("PAI-24", refused()),
            scored("PAI-03", refused())]
    for r, t in zip(rows, (1.0, 2.0, 3.0, 4.0, 10.0)):
        r["seconds"] = t
    s = scoring.summarise(rows)
    assert s["passed"] == 2
    assert s["figures_ungrounded_answers"] == ["PAI-02"]
    assert s["unanswerable_answered"] == ["PAI-23"]
    assert s["could_not_read_answerable"] == ["PAI-03"]
    assert (s["seconds_median"], s["seconds_worst"], s["seconds_total"]) == (3.0, 10.0, 20.0)


# ----------------------------------------------------------------- the baseline

def _rows(passed=("PAI-01",), bad_figure=None, answered_unanswerable=None):
    rows = []
    for q in QS:
        res = generated("It is 3.0 mm/s [S1].", VIB) if q["id"] in passed else refused()
        r = scored(q["id"], res)
        r["passed"] = q["id"] in passed
        if q["id"] == bad_figure:
            r["figures_ok"], r["figures_ungrounded"] = False, ["9 bar"]
        if q["id"] == answered_unanswerable:
            r["answered"] = True
        rows.append(r)
    return rows


def test_a_shown_figure_the_page_lacks_blocks_with_no_baseline_at_all():
    why = scoring.compare_with_baseline(_rows(bad_figure="PAI-05"), None)
    assert why and "PAI-05" in why[0] and "9 bar" in why[0]


def test_an_unanswerable_question_that_was_answered_blocks_with_no_baseline():
    why = scoring.compare_with_baseline(_rows(answered_unanswerable="PAI-24"), {})
    assert why and "PAI-24" in why[0] and "guess" in why[0]


def test_a_clean_run_with_no_baseline_has_no_reasons():
    assert scoring.compare_with_baseline(_rows(), None) == []


def test_a_question_that_passed_in_the_baseline_and_fails_now_blocks():
    base = {"passing": ["PAI-01", "PAI-02"]}
    why = scoring.compare_with_baseline(_rows(passed=("PAI-01",)), base)
    assert why == ["PAI-02 passed in the baseline and does not now"]


def test_a_gate_the_owner_wrote_holds_the_minimum_and_the_protected_questions():
    base = {"passing": ["PAI-01", "PAI-02"], "gate": {"min_passing": 2, "protected": ["PAI-01"]}}
    why = scoring.compare_with_baseline(_rows(passed=("PAI-02",)), base)
    assert any("1 questions pass; the gate needs at least 2" in w for w in why)
    assert any(w.startswith("PAI-01 passed in the baseline") for w in why)
    assert not any(w.startswith("PAI-02") for w in why)                 # not protected: it may trade places


# --------------------------------------------------------------- the question set

def test_the_question_set_is_true_of_the_invented_corpus():
    assert run_p1ai.check_labels(QS) == []
    assert len({q["id"] for q in QS}) == len(QS) == 26
    assert {q["category"] for q in QS} >= {"figure", "unit_trap", "sign", "near_miss", "absent", "old_revision"}


def test_a_label_that_is_false_of_the_corpus_is_caught():
    tampered = json.loads(json.dumps(QS))
    tampered[0]["expected_answer_contains"] = ["9.9 mm/s"]
    tampered[1]["expected_pages"] = [9]
    tampered[2]["expected_clause"] = "8.8"
    tampered[22]["expected_document"] = "STD-A-001.pdf"
    tampered[3]["forbidden_in_answer"] = ["85 degC"]               # inside a required phrase
    problems = run_p1ai.check_labels(tampered)
    assert any("PAI-01" in p and "expected phrase" in p for p in problems)
    assert any("PAI-02" in p and "page out of range" in p for p in problems)
    assert any("PAI-03" in p and "clause 8.8" in p for p in problems)
    assert any("PAI-23" in p and "unanswerable" in p for p in problems)
    assert any("PAI-04" in p and "part of a required phrase" in p for p in problems)


def test_the_unanswerable_questions_name_things_no_standard_in_the_corpus_mentions():
    import corpus
    everything = " ".join(" ".join(" ".join(p) for p in pages) for pages in corpus.DOCS.values()).lower()
    for qid, word in (("PAI-23", "colour"), ("PAI-24", "warranty"), ("PAI-25", "crane"), ("PAI-26", "flange")):
        assert word in BY_ID[qid]["question"].lower() and word not in everything
    assert "does not cover reciprocating pumps" in everything


# ----------------------------------------------------------------------- the runner

class Clock:
    def __init__(self):
        self.t = 0.0
        self.step = iter([1.5, 2.5, 0.5])

    def __call__(self):
        return self.t


def test_the_runner_times_every_question_and_prints_the_time(monkeypatch):
    t = {"now": 0.0}
    gaps = iter([1.5, 2.5, 4.0])

    def ask(question, qid):
        t["now"] += next(gaps)
        return generated("It is 3.0 mm/s [S1].", VIB)

    monkeypatch.setattr(run_p1ai.time, "perf_counter", lambda: t["now"])
    lines: list[str] = []
    rows = run_p1ai.run_questions(QS[:3], ask, None, say=lines.append)
    assert [r["seconds"] for r in rows] == [1.5, 2.5, 4.0]
    assert any("1.5s" in l for l in lines) and any("4.0s" in l for l in lines)
    out: list[str] = []
    s = run_p1ai.report(rows, "m1", say=out.append)
    assert s["seconds_worst"] == 4.0
    assert any("median" in l and "worst 4.0s" in l and "total 8.0s" in l for l in out)


@pytest.fixture
def fake_env(tmp_path, monkeypatch):
    """The runner with no model, no corpus build and a free lock."""
    monkeypatch.setenv("HEAVY_JOB_LOCK", "off")
    monkeypatch.setattr(run_p1ai, "model_status",
                        lambda m: {"answer_model_reachable": True, "answer_model_installed": True})
    monkeypatch.setattr(run_p1ai.harness, "ingest_corpus", lambda folder: {})
    monkeypatch.setattr(settings, "db_path", tmp_path / "x.sqlite")
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    return tmp_path


def _good_ask():
    def ask(question, qid):
        q = next(x for x in QS if x["id"] == qid)
        return generated("It is 3.0 mm/s [S1].", VIB) if q["answerable"] else refused()
    return ask


def test_a_run_with_no_baseline_says_so_and_passes_the_hard_rules(fake_env, capsys):
    code = run_p1ai._run(["--baseline", str(fake_env / "b.json")], ask_factory=_good_ask, ingest=lambda f: {})
    out = capsys.readouterr().out
    assert code == 0 and "NO BASELINE stored for this model yet" in out and "P1-AI score:" in out


def test_a_shown_wrong_figure_blocks_the_run(fake_env, capsys):
    def wrong():
        return lambda question, qid: generated("It is 99 mm/s [S1].", VIB) if BY_ID[qid]["answerable"] else refused()
    code = run_p1ai._run(["--baseline", str(fake_env / "b.json")], ask_factory=wrong, ingest=lambda f: {})
    out = capsys.readouterr().out
    assert code == 1 and "BLOCKED" in out and "99 mm/s" in out


def test_an_unreachable_model_ends_the_run_with_no_score_and_asks_nothing(monkeypatch, fake_env, capsys):
    monkeypatch.setattr(run_p1ai, "model_status",
                        lambda m: {"answer_model_reachable": False, "ollama_error": "connection refused"})

    def never():
        raise AssertionError("a question was asked with no model")
    code = run_p1ai._run([], ask_factory=never, ingest=lambda f: pytest.fail("the corpus was built"))
    out = capsys.readouterr().out
    assert code == run_p1ai.EXIT_NO_MODEL == 3
    assert "CANNOT RUN: connection refused" in out and "P1-AI score" not in out


def test_a_model_that_is_not_installed_is_named(monkeypatch, fake_env, capsys):
    monkeypatch.setattr(run_p1ai, "model_status",
                        lambda m: {"answer_model_reachable": True, "answer_model_installed": False})
    assert run_p1ai._run(["--model", "qwen9:1b"], ask_factory=_good_ask, ingest=lambda f: {}) == 3
    assert "model qwen9:1b is not installed" in capsys.readouterr().out


def test_rows_the_model_did_not_answer_make_no_score(fake_env, capsys):
    code = run_p1ai._run([], ask_factory=lambda: (lambda q, i: refused("model_unavailable")),
                         ingest=lambda f: {})
    out = capsys.readouterr().out
    assert code == 3 and "CANNOT SCORE" in out and "P1-AI score" not in out


def test_the_model_is_a_setting_and_the_flag_overrides_it(fake_env, monkeypatch, capsys):
    seen = []
    monkeypatch.setattr(run_p1ai, "model_status",
                        lambda m: seen.append(m) or {"answer_model_reachable": True, "answer_model_installed": True})
    monkeypatch.setattr(settings, "p1_ai_model", "model-from-setting")
    run_p1ai._run(["--baseline", str(fake_env / "b.json")], ask_factory=_good_ask, ingest=lambda f: {})
    run_p1ai._run(["--model", "model-from-flag", "--baseline", str(fake_env / "b.json")],
                  ask_factory=_good_ask, ingest=lambda f: {})
    assert seen == ["model-from-setting", "model-from-flag"]


def test_the_default_model_is_the_small_one_and_is_documented():
    assert type(settings).model_fields["p1_ai_model"].default == "qwen3.5:2b"
    assert "P1_AI_MODEL=qwen3.5:2b" in (REPO / "backend" / ".env.example").read_text(encoding="utf-8")


def test_the_run_leaves_the_answer_model_setting_as_it_found_it(fake_env, monkeypatch):
    monkeypatch.setattr(settings, "answer_model", "original-model")
    run_p1ai._run(["--model", "other", "--baseline", str(fake_env / "b.json")],
                  ask_factory=_good_ask, ingest=lambda f: {})
    assert settings.answer_model == "original-model"


def test_the_baseline_is_kept_per_model_and_a_rewrite_keeps_the_owners_gate(fake_env):
    b = fake_env / "b.json"
    b.write_text(json.dumps({"baselines": {"m-a": {"passing": ["PAI-01"], "gate": {"min_passing": 1, "protected": []}}}}))
    for model in ("m-a", "m-b"):
        assert run_p1ai._run(["--model", model, "--write-baseline", "--baseline", str(b)],
                             ask_factory=_good_ask, ingest=lambda f: {}) == 0
    stored = json.loads(b.read_text())["baselines"]
    assert set(stored) == {"m-a", "m-b"}
    assert stored["m-a"]["gate"] == {"min_passing": 1, "protected": []}
    assert "gate" not in stored["m-b"]
    assert stored["m-a"]["total"][1] == 26 and "PAI-01" in stored["m-a"]["passing"]


def test_a_stored_baseline_for_the_model_is_enforced(fake_env, capsys):
    b = fake_env / "b.json"
    b.write_text(json.dumps({"baselines": {"qwen3.5:2b": {"passing": ["PAI-01", "PAI-02"]}}}))
    code = run_p1ai._run(["--baseline", str(b)], ask_factory=_good_ask, ingest=lambda f: {})
    assert code == 1 and "PAI-02 passed in the baseline and does not now" in capsys.readouterr().out
    b.write_text(json.dumps({"baselines": {"another-model": {"passing": ["PAI-02"]}}}))
    assert run_p1ai._run(["--baseline", str(b)], ask_factory=_good_ask, ingest=lambda f: {}) == 0


# --------------------------------------------- the lock, the unload, the real command

def test_the_exam_takes_the_shared_lock_and_gives_up_when_it_is_held(tmp_path, monkeypatch):
    lock = tmp_path / "heavy.lock"
    monkeypatch.setenv("HEAVY_JOB_LOCK", str(lock))
    monkeypatch.setenv("HEAVY_JOB_WAIT_MINUTES", "0")
    heavy_lock.try_acquire("p1", owner="session 2")
    ran = []
    monkeypatch.setattr(run_p1ai, "_guarded", lambda argv: ran.append(1) or 0)
    assert run_p1ai.main([]) == heavy_lock.EXIT_BUSY and ran == []


def test_the_exam_holds_the_lock_while_it_runs_and_frees_it_after(tmp_path, monkeypatch):
    lock = tmp_path / "heavy.lock"
    monkeypatch.setenv("HEAVY_JOB_LOCK", str(lock))
    seen = {}
    monkeypatch.setattr(run_p1ai, "_guarded", lambda argv: seen.update(rec=json.loads(lock.read_text())) or 0)
    assert run_p1ai.main([]) == 0
    assert seen["rec"]["kind"] == "p1" and seen["rec"]["owner"] == "P1-AI" and not lock.exists()


@pytest.mark.parametrize("failure", [None, RuntimeError("boom"), KeyboardInterrupt()])
def test_models_are_unloaded_on_success_on_error_and_on_ctrl_c(monkeypatch, failure):
    from app import model_memory
    unloaded = []
    monkeypatch.setattr(model_memory, "unload_used", lambda: unloaded.append(1) or {"unloaded": ["m"], "failed": []})

    def fake_run(argv):
        if failure:
            raise failure
        return 0
    monkeypatch.setattr(run_p1ai, "_run", fake_run)
    if failure:
        with pytest.raises(type(failure)):
            run_p1ai._guarded([])
    else:
        assert run_p1ai._guarded([]) == 0
    assert unloaded == [1]


def test_a_model_that_would_not_unload_never_turns_a_result_into_a_crash(monkeypatch, capsys):
    from app import model_memory

    def boom():
        raise RuntimeError("x")
    monkeypatch.setattr(model_memory, "unload_used", boom)
    run_p1ai.unload_models()
    assert "could not be unloaded" in capsys.readouterr().out


def test_the_real_command_with_no_ollama_says_cannot_run_and_makes_no_score(tmp_path):
    env = {**__import__("os").environ, "HEAVY_JOB_LOCK": "off", "OLLAMA_URL": "http://127.0.0.1:9",
           "PYTHONPATH": str(REPO / "backend")}
    done = subprocess.run([sys.executable, str(REPO / "eval" / "p1ai" / "run_p1ai.py")], cwd=REPO, env=env,
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 3, done.stdout + done.stderr
    assert "CANNOT RUN" in done.stdout and "P1-AI score" not in done.stdout


def test_the_readme_says_it_cannot_run_in_the_cloud_and_how_to_run_it():
    text = (REPO / "eval" / "p1ai" / "README.md").read_text(encoding="utf-8")
    assert "cannot run in the cloud" in text.lower() and "run_p1ai.py" in text and "--write-baseline" in text
