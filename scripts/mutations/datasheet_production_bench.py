"""Mutations of the production-path datasheet benchmark:
`app/datasheet_offline.read_file` (the real upload stages in a throwaway
database, the switches set and restored, OCR reported), the model-call
override and office page text in `app/datasheet_ai.py`, and the reader
dispatch, conflict count, all-local set and Claude lane in
`scripts/datasheet_bench.py`."""

from __future__ import annotations

from ._base import APP, REPO, Mutation

_T = "tests/test_datasheet_production_bench.py"
_B = "tests/test_datasheet_bench.py"
_S = REPO / "scripts" / "datasheet_bench.py"
_O = APP / "datasheet_offline.py"
_A = APP / "datasheet_ai.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1720", phase=1720, description="the AI reads MuPDF's numbers-only reading of a workbook",
             path=_A, anchor="    if stored_path and datasheet_inputs.is_office_input(stored_path):\n",
             replacement="    if False:\n",
             target=_T, keyword="hybrid_reads_the_xlsx", tags=("honesty",)),
    Mutation(id="M1721", phase=1721, description="a model call handed in is ignored (the configured engine is used)",
             path=_A, anchor="    if override is not None:\n        return override, None\n",
             replacement="    if False:\n        return override, None\n",
             target=_T, keyword="hybrid_reads or override_never_switches or quote_is_not_on_the_page",
             tags=("honesty",)),
    Mutation(id="M1722", phase=1722, description="the model-call override outlives its block",
             path=_A, anchor="        _CALL_OVERRIDE.reset(token)\n",
             replacement="        pass\n",
             target=_T, keyword="restored_after_a_run or override_never_switches", tags=("security",)),
    Mutation(id="M1723", phase=1723, description="a model call handed in switches the AI reader on while it is off",
             path=_A,
             anchor="    name = (engine if engine is not None else engine_setting()).strip().lower()\n    if name == OFF:\n",
             replacement="    name = (engine if engine is not None else engine_setting()).strip().lower()\n"
                         "    if _CALL_OVERRIDE.get() is not None:\n        return _CALL_OVERRIDE.get(), None\n"
                         "    if name == OFF:\n",
             target=_T, keyword="override_never_switches", tags=("security", "critical")),
    Mutation(id="M1724", phase=1724, description="a run leaves DATASHEET_OFFICE_INPUT / DATASHEET_AI_READER switched on",
             path=_O, anchor="        settings.datasheet_office_input, settings.datasheet_ai_reader = saved\n",
             replacement="        pass\n",
             target=_T, keyword="restore", tags=("security", "critical")),
    Mutation(id="M1725", phase=1725, description="the office switch is never set for the run",
             path=_O, anchor="        settings.datasheet_office_input = bool(office_input)\n",
             replacement="        settings.datasheet_office_input = False\n",
             target=_T, keyword="hybrid_reads_the_xlsx or rules_mode_is_todays or restored_after_a_run",
             tags=("honesty",)),
    Mutation(id="M1726", phase=1726, description="the throwaway paths are left in the environment after a run",
             path=_O, anchor="                if value is None:\n                    os.environ.pop(name, None)\n",
             replacement="                if False:\n                    pass\n",
             target=_T, keyword="restored_after_a_run", tags=("security",)),
    Mutation(id="M1727", phase=1727, description="a spawned worker would use the project's data directory",
             path=_O, anchor='        os.environ.update({"DATA_DIR": str(root), "DB_PATH": str(root / "offline.sqlite"),\n',
             replacement='        ({"DATA_DIR": str(root), "DB_PATH": str(root / "offline.sqlite"),\n',
             target=_T, keyword="restored_after_a_run", tags=("security",)),
    Mutation(id="M1728", phase=1728, description="a scan with no OCR engine is reported as read (a silent 0)",
             path=_O, anchor='    if not ok:\n        out["ocr"]["unavailable"] = why\n',
             replacement='    if False:\n        out["ocr"]["unavailable"] = why\n',
             target=_T, keyword="ocr_unavailable", tags=("honesty", "critical")),
    Mutation(id="M1729", phase=1729, description="missing OCR model files are not noticed",
             path=_O, anchor="    if missing:\n        return False, f\"OCR model file(s) missing",
             replacement="    if False:\n        return False, f\"OCR model file(s) missing",
             target=_T, keyword="ocr_unavailable", tags=("honesty",)),
    Mutation(id="M1730", phase=1730, description="rules mode indexes a workbook production stores unindexed",
             path=_O, anchor="    if row[\"status\"] == states.STORED_NOT_INDEXED:\n",
             replacement="    if False:\n",
             target=_T, keyword="rules_mode_is_todays", tags=("honesty",)),
    Mutation(id="M1731", phase=1731, description="conflicts flagged for an engineer are not counted",
             path=_S, anchor='        "conflicts": sum(1 for f in out["facts"]\n',
             replacement='        "conflicts": 0 * sum(1 for f in out["facts"]\n',
             target=_T, keyword="disagreement", tags=("honesty",)),
    Mutation(id="M1732", phase=1732, description="all-local includes the Claude hybrid (spend)",
             path=_S, anchor='ALL_LOCAL = ("rules", "rules+office", "hybrid:ollama", "ai-only:ollama")',
             replacement='ALL_LOCAL = ("rules", "rules+office", "hybrid:ollama", "hybrid:claude", "ai-only:ollama")',
             target=_T, keyword="all_local", tags=("security", "critical")),
    Mutation(id="M1733", phase=1733, description="hybrid:claude uses the benchmark's lane, not production's engine",
             path=_S, anchor='    if spec["mode"] == "hybrid":\n        if spec["engine"] == "oracle":\n',
             replacement='    if spec["mode"] == "hybrid" and spec["engine"] != "claude":\n        if spec["engine"] == "oracle":\n',
             target=_T, keyword="hybrid_claude", tags=("honesty",)),
    Mutation(id="M1734", phase=1734, description="hybrid:claude reports no USD",
             path=_S, anchor="                claude_spend.spent(datasheet_ai.STEP) - before, 4)}",
             replacement="                0.0, 4)}",
             target=_T, keyword="hybrid_claude_is_productions", tags=("honesty",)),
    Mutation(id="M1735", phase=1735, description="the oracle's numbers are not labelled an upper bound",
             path=_S, anchor='        report["label"] = ORACLE_LABEL\n',
             replacement="        pass\n",
             target=_T, keyword="oracle_run_is_labelled", tags=("honesty",)),
    Mutation(id="M1736", phase=1736, description="read_file ignores the model call it is handed",
             path=_O, anchor="    override = (datasheet_ai.using_model_call(model_call) if model_call is not None\n",
             replacement="    override = (contextlib.nullcontext() if model_call is not None\n",
             target=_T, keyword="hybrid_reads or quote_is_not_on_the_page or disagreement",
             tags=("honesty",)),
    Mutation(id="M1737", phase=1737, description="an AI quote need not be on the page",
             path=APP / "claude_datasheet.py",
             anchor="        if not quote or not _contains(folded_page, quote):\n",
             replacement="        if not quote:\n",
             target=_T, keyword="quote_is_not_on_the_page", tags=("honesty", "critical")),
    Mutation(id="M1738", phase=1738, description="the AI-only diagnosis never runs OCR (scans reported read, empty)",
             path=_S, anchor="        if not ocr_ok and path.suffix.lower() == \".pdf\":\n",
             replacement="        if False:\n",
             target=_B, keyword="cannot_read_is_unsupported or counts_unsupported", tags=("honesty",)),
    Mutation(id="M1739", phase=1739, description="the AI-only diagnosis reads office files through MuPDF",
             path=_S, anchor="    pages = datasheet_inputs.page_texts(path, recognise=ocr_ok)\n",
             replacement="    pages = datasheet_inputs.read_pdf(path, recognise=ocr_ok).pages\n",
             target=_B, keyword="reads_office_files", tags=("honesty",)),
)
