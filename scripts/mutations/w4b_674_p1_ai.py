"""#674 "P1-AI, the scored model tier": each entry deletes one part;
backend/tests/test_w4b_674_p1_ai.py must notice."""
from __future__ import annotations

from ._base import APP, REPO, Mutation

_T = "tests/test_w4b_674_p1_ai.py"
_TAG = ("w4b_674", "p1_ai")
SC = REPO / "eval" / "p1ai" / "scoring.py"
RUN = REPO / "eval" / "p1ai" / "run_p1ai.py"


def _m(i, desc, path, anchor, repl, kw=None):
    return Mutation(id=f"M{i}", phase=i, description=desc, path=path,
                    anchor=anchor, replacement=repl, target=_T, keyword=kw, tags=_TAG)


MUTATIONS: tuple[Mutation, ...] = (
    _m(4601, "a dropped minus sign is not noticed", SC, '        if claim["sign"] != found["sign"]:\n',
       '        if claim["sign"] == "-" and found["sign"] != "-":\n', "minus_sign"),
    _m(4602, "any unit is accepted for a figure", SC, '        if claim["unit"] in units:\n            return True\n',
       "        return True\n", "wrong_unit or table_rows_label"),
    _m(4603, "any value close enough is accepted", SC, '        if abs(found["value"] - claim["value"]) > 1e-9:\n',
       '        if abs(found["value"] - claim["value"]) > 100:\n', "page_does_not_hold"),
    _m(4604, "a sentence is held to every cited passage, not the one it cites", SC,
       "        pool = [passages[n - 1] for n in marks] if marks else cited_only\n", "        pool = cited_only\n",
       "passage_it_cites"),
    _m(4605, "a sentence with no marker is held to every passage shown", SC,
       "        pool = [passages[n - 1] for n in marks] if marks else cited_only\n",
       "        pool = [passages[n - 1] for n in marks] if marks else passages\n", "no_marker"),
    _m(4606, "a percent sign is not read as a unit", SC, '            if after.startswith("%"):\n                unit = "percent"\n',
       '            if after.startswith("%"):\n                unit = None\n', "table_rows_label"),
    _m(4607, "a unit in a table row's label does not ground its cell", SC,
       '            line_units = {u for u in (_unit(w.strip("()[],;:.")) for w in near) if u}\n',
       "            line_units = set()\n", "table_rows_label"),
    _m(4608, "a decimal comma is read as a thousands separator", SC,
       '    t = text.replace(",", ".") if re.fullmatch(r"\\d+,\\d+", text) else text.replace(",", "")\n',
       '    t = text.replace(",", "")\n', "decimal_comma"),
    _m(4609, "10 % and 10 percent are different facts", SC,
       '    t = _CITATION.sub("", text or "").lower().replace("%", " percent")\n',
       '    t = _CITATION.sub("", text or "").lower()\n', "facts_ignore"),
    _m(4610, "a forbidden figure is never found", SC,
       "    return [f for f in forbidden if _fold(f) in folded]\n", "    return []\n", "wrong_revision or unit_trap"),
    _m(4611, "a model that did not answer counts as a correct refusal", SC,
       '        row["passed"] = bool(not answered and not row["model_unavailable"])\n',
       '        row["passed"] = bool(not answered)\n', "model_that_did_not_answer"),
    _m(4612, "a wrong answer is not called a guess", SC,
       '    row["guessed"] = bool(answered and not row["facts_ok"])\n', '    row["guessed"] = False\n', "guess"),
    _m(4613, "the clause need not be right", SC,
       '                         and row.get("retrieval_correct") is True and row["clause_ok"] is not False)\n',
       '                         and row.get("retrieval_correct") is True)\n', "wrong_clause"),
    _m(4614, "an ungrounded figure does not fail the question", SC,
       '    row["passed"] = bool(answered and row["figures_ok"] and row["facts_ok"]\n',
       '    row["passed"] = bool(answered and row["facts_ok"]\n', "wrong_figure_fails"),
    _m(4615, "a refusal caused by the token budget counts as a correct refusal", SC,
       '    if row.get("length_limited"):\n', "    if False:\n", "token_budget"),
    _m(4616, "a shown figure the page lacks does not block", SC,
       '        if not r["figures_ok"]:\n', "        if False:\n", "no_baseline_at_all"),
    _m(4617, "an unanswerable question that was answered does not block", SC,
       '        if not r["answerable"] and r["answered"]:\n', "        if False:\n", "unanswerable_question_that_was_answered"),
    _m(4618, "a question that passed in the baseline may fail now", SC,
       '        if qid not in passed_now:\n            reasons.append(f"{qid} passed in the baseline',
       '        if False:\n            reasons.append(f"{qid} passed in the baseline', "passed_in_the_baseline"),
    _m(4619, "the owner's minimum is ignored", SC,
       '    if gate is not None and len(passed_now) < gate["min_passing"]:\n', "    if False:\n", "gate_the_owner"),
    _m(4620, "a label naming an answer for an unanswerable question is accepted", RUN,
       '        if not q["answerable"] and (q.get("expected_document")', '        if False and (q.get("expected_document")',
       "label_that_is_false"),
    _m(4621, "an unreachable model is scored anyway", RUN,
       '    if not status.get("answer_model_reachable") or not status.get("answer_model_installed"):\n',
       "    if False:\n", "unreachable_model or not_installed"),
    _m(4622, "rows the model did not answer make a score", RUN,
       '    if any(r["model_unavailable"] for r in rows):\n', "    if False:\n", "did_not_answer_make_no_score"),
    _m(4623, "the exam does not take the shared lock", RUN,
       '    return heavy_lock.run_locked("p1", lambda: _guarded(argv), owner="P1-AI")\n', "    return _guarded(argv)\n",
       "shared_lock"),
    _m(4624, "models are not unloaded at the end", RUN, "    finally:\n        unload_models()\n",
       "    finally:\n        pass\n", "unloaded_on_success"),
    _m(4625, "the model is hard-coded", RUN, "    model = args.model or settings.p1_ai_model\n",
       '    model = args.model or "qwen3.5:2b"\n', "model_is_a_setting"),
    _m(4626, "the answer model setting is not restored", RUN,
       "         settings.auth_mode, settings.answer_model) = saved\n", "         settings.auth_mode, _unused) = saved\n",
       "answer_model_setting_as_it_found"),
    _m(4627, "the baseline is not kept per model", RUN,
       '        baselines.setdefault("baselines", {})[model] = entry\n',
       '        baselines.setdefault("baselines", {})["any"] = entry\n', "kept_per_model"),
    _m(4628, "a baseline rewrite drops the owner's gate", RUN, '        if "gate" in old:\n', "        if False:\n",
       "kept_per_model"),
    _m(4629, "the time per question is not recorded", RUN, '        row["seconds"] = round(elapsed, 2)',
       '        row["seconds"] = 0', "times_every_question"),
    _m(4630, "the default model is not the small one", APP / "config.py", '    p1_ai_model: str = "qwen3.5:2b"\n',
       '    p1_ai_model: str = "qwen3.5:4b"\n', "default_model"),
)
