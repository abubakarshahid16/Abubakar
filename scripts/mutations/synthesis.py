"""Mutations of `backend/app/synthesis.py`."""

from __future__ import annotations

from ._base import APP, _B34_TEST, _PROVIDER_TEST, _SYNTH, Mutation


MUTATIONS: tuple[Mutation, ...] = (
    # ---- from B34_STANDARD_IDS --------------------------------------------
    #: Phase 31: B34 - a standard number is a NAME, not a measurement, under a
    #: CLOSED grammar; and a removed sentence is REPORTED, never silently deleted.
    #: M288-M293 loosen or remove the grammar in six different ways - each must be
    #: caught, and M289 and M293 are the loosenings that would let a fabricated
    #: value disguised as a standard number through ("per SAES-H-150, apply 150").
    Mutation(
        id="M288", phase=31,
        description="remove the grammar from the stripper - the original bug: SAES-H-004 read as the quantity 4",
        path=_SYNTH,
        anchor='    return _STANDARD_IDENTIFIER.sub(" ", _REFERENCE_NUMERAL.sub(" ", sentence))',
        replacement='    return _REFERENCE_NUMERAL.sub(" ", sentence)',
        target=_B34_TEST, keyword="naming_a_real_standard_survives",
        tags=("honesty", "answer_path"),
    ),
    Mutation(
        id="M289", phase=31,
        description="LOOSEN BY VALUE: exempt the identifier's digits wherever they appear - lets 'per SAES-H-150, apply 150' through",
        path=_SYNTH,
        anchor='    return _STANDARD_IDENTIFIER.sub(" ", _REFERENCE_NUMERAL.sub(" ", sentence))',
        replacement=(
            '    stripped = _STANDARD_IDENTIFIER.sub(" ", _REFERENCE_NUMERAL.sub(" ", sentence))\n'
            '    for ident in _STANDARD_IDENTIFIER.findall(sentence):\n'
            '        for digits in re.findall(r"\\d+", ident):\n'
            '            stripped = re.sub(r"(?<![\\d.])" + digits + r"(?![\\d.])", " ", stripped)\n'
            '    return stripped'),
        target=_B34_TEST, keyword="disguised",
        tags=("honesty", "critical", "answer_path"),
    ),
    Mutation(
        id="M290", phase=31,
        description="LOOSEN THE PREFIX: any letters-hyphen-digits shape counts as a standard number",
        path=_SYNTH,
        anchor='    r"SAES-[A-Z]-\\d{2,4}[A-Z]?"',
        replacement='    r"[A-Za-z]+-[A-Za-z]?-?\\d{1,5}[A-Z]?"',
        target=_B34_TEST, keyword="lookalike",
        tags=("honesty", "answer_path"),
    ),
    Mutation(
        id="M291", phase=31,
        description="LOOSEN THE DIGITS: SAES takes any number of digits, so SAES-H-15000 is exempt",
        path=_SYNTH,
        anchor='    r"SAES-[A-Z]-\\d{2,4}[A-Z]?"',
        replacement='    r"SAES-[A-Z]-\\d+[A-Z]?"',
        target=_B34_TEST, keyword="15000",
        tags=("honesty", "answer_path"),
    ),
    Mutation(
        id="M292", phase=31,
        description="LOOSEN THE CASE: ignore case, so 'saes-h-150' is exempt",
        path=_SYNTH,
        anchor='    r")(?![\\w-])"\n)',
        replacement='    r")(?![\\w-])",\n    re.IGNORECASE,\n)',
        target=_B34_TEST, keyword="lookalike",
        tags=("honesty", "answer_path"),
    ),
    Mutation(
        id="M293", phase=31,
        description="LOOSEN THE END: let an identifier swallow the text after it - 'SAES-H-150, apply 150' taken whole",
        path=_SYNTH,
        anchor='    r"SAES-[A-Z]-\\d{2,4}[A-Z]?"',
        replacement='    r"SAES-[A-Z]-\\d{2,4}[A-Z]?(?:[^\\[]*?\\d+)?"',
        target=_B34_TEST, keyword="disguised",
        tags=("honesty", "critical", "answer_path"),
    ),
    Mutation(
        id="M294", phase=31,
        description="disable the numeric guard altogether (the order: do not disable it)",
        path=_SYNTH,
        anchor="        if unsupported:\n            # Named as the reader sees it",
        replacement="        if False:\n            # Named as the reader sees it",
        target=_B34_TEST, keyword="disguised",
        tags=("honesty", "critical", "answer_path"),
    ),
    Mutation(
        id="M295", phase=31,
        description="regress the reason wording - the reader no longer sees 'value 300 not in cited passage'",
        path=_SYNTH,
        anchor='            dropped.append((sentence, f"value {value} not in cited passage"))',
        replacement='            dropped.append((sentence, f"carries a number no cited span contains: {value}"))',
        target=_B34_TEST, keyword="reported_and_excluded",
        tags=("honesty", "answer_path"),
    ),
    Mutation(
        id="M296", phase=31,
        description="the summary API drops the removed list - silent deletion again",
        path=_SYNTH,
        anchor='            {"sentence": s, "reason": r} for s, r in summary.dropped_sentences\n        ],',
        replacement='            {"sentence": s, "reason": r} for s, r in ()\n        ],',
        target=_B34_TEST, keyword="reported_and_excluded",
        tags=("honesty", "answer_path"),
    ),
    Mutation(
        id="M297", phase=31,
        description="the recommendation discards what it removed - the one silent path B34 closed",
        path=_SYNTH,
        anchor="        removed_out.extend(dropped)",
        replacement="        pass",
        target=_B34_TEST, keyword="recommendation_reports or recommendation_keeps",
        tags=("honesty", "answer_path"),
    ),
    # ---- from B7_ANALYSIS_GENERATION --------------------------------------
    #: B7: four analysis-route tests had passed through the single-passage
    #: pass-through since 5a7a2b3's relevance floor, so they never reached
    #: generation. With two on-topic passages they do; one mutation per test
    #: proves each still guards the behaviour its name claims.
    Mutation(
        id="M309", phase=34,
        description="a sentence whose number is in no cited span is kept, so "
                    "an unsupported number reaches the reader",
        path=APP / "synthesis.py",
        anchor="        if unsupported:\n            # Named as the reader sees it",
        replacement="        if False:\n            # Named as the reader sees it",
        target="tests/test_analysis_routes.py",
        keyword="number_is_in_no_cited_span",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M310", phase=34,
        description="an uncited sentence is kept in the prose",
        path=APP / "synthesis.py",
        anchor='        if not cited:\n            dropped.append((sentence, "cites no supplied source"))',
        replacement='        if False:\n            dropped.append((sentence, "cites no supplied source"))',
        target="tests/test_analysis_routes.py",
        keyword="uncited_sentence",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M311", phase=34,
        description="the recommendation states a confidence with no checks "
                    "behind it",
        path=APP / "synthesis.py",
        anchor='        "checks": [{"label": c.label, "fired": c.fired} for c in recommendation.checks],',
        replacement='        "checks": [],',
        target="tests/test_analysis_routes.py",
        keyword="confidence_is_never_high",
        tags=("honesty",),
    ),
    # ---- from PROVIDER_SEAM -----------------------------------------------
    #: Feature 1 section 5a + B54: one interface, and provenance that cannot be
    #: omitted. Before it, nothing in the system could say which model answered.
    Mutation(
        id="M354", phase=44,
        description="PUT B54 BACK: Generation discards the model tag Ollama "
                    "reported in every response",
        path=APP / "synthesis.py",
        anchor='            model=str(raw.get("model") or ""),',
        replacement='            model="",',
        target=_PROVIDER_TEST, keyword="no_longer_discards_the_model",
        tags=("honesty",),
    ),
)
