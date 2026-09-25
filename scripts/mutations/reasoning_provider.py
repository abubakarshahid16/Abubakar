"""Mutations of `backend/app/reasoning_provider.py`."""

from __future__ import annotations

from ._base import APP, _PROVIDER_TEST, Mutation


MUTATIONS: tuple[Mutation, ...] = (
    # ---- from PROVIDER_SEAM -----------------------------------------------
    #: Feature 1 section 5a + B54: one interface, and provenance that cannot be
    #: omitted. Before it, nothing in the system could say which model answered.
    Mutation(
        id="M352", phase=44,
        description="let a response be built with no model tag, so a stored "
                    "answer cannot name its engine",
        path=APP / "reasoning_provider.py",
        anchor="        if not self.model_tag:\n            raise ValueError(",
        replacement="        if False:\n            raise ValueError(",
        target=_PROVIDER_TEST, keyword="no_model_tag_cannot_be_built",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M353", phase=44,
        description="fall back silently to the REQUESTED tag, papering over a "
                    "floating tag that resolved to something else",
        path=APP / "reasoning_provider.py",
        anchor='        model_tag = reported or f"{self.requested_model} (unreported)"',
        replacement="        model_tag = reported or self.requested_model",
        target=_PROVIDER_TEST, keyword="reports_no_tag_is_marked",
        tags=("honesty",),
    ),
    Mutation(
        id="M355", phase=44,
        description="swallow a transport failure into an empty answer instead "
                    "of a named refusal",
        path=APP / "reasoning_provider.py",
        anchor=("        # ruff's blind-except rule is about swallowing, which this does not do.\n"
                "        except Exception as exc:\n"
                '            raise ProviderRefused(f"{self.name}: {type(exc).__name__}: {exc}") from exc'),
        replacement=("        # ruff's blind-except rule is about swallowing, which this does not do.\n"
                     "        except Exception as exc:\n"
                     '            raw = {"response": "", "model": self.requested_model}'),
        target=_PROVIDER_TEST, keyword="transport_failure_is_a_named_refusal",
        tags=("honesty", "critical"),
    ),
    # ---- from B5_STANDARDS_INVENTORY --------------------------------------
    #: B5 part 2: standard family, licence status, cover-page backfill, and the
    #: "cited by a submittal" flag on the inventory.
    Mutation(
        id="M565", phase=61,
        description="get_provider ignores REASONING_PROVIDER and always uses ollama",
        path=APP / "reasoning_provider.py",
        anchor="    ok, why = claude_available()\n    if ok:\n",
        replacement="    ok, why = claude_available()\n    if False:\n",
        target="tests/test_claude_provider.py",
        keyword="claude_is_selected_only_when",
        tags=("model",),
    ),
    Mutation(
        id="M566", phase=61,
        description="a missing API key no longer forces the ollama fallback",
        path=APP / "reasoning_provider.py",
        anchor='        return False, "no ANTHROPIC_API_KEY"\n',
        replacement="        pass\n",
        target="tests/test_claude_provider.py",
        keyword="missing_key_falls_back",
        tags=("model", "safety"),
    ),
    Mutation(
        id="M567", phase=61,
        description="the provider's refusal message carries the request headers (the key)",
        path=APP / "reasoning_provider.py",
        anchor=("            # TYPE only - reader_transport never puts headers in it).\n"
                '            raise ProviderRefused(f"{self.name}: {type(exc).__name__}: {exc}") from exc\n'),
        replacement=("            # TYPE only - reader_transport never puts headers in it).\n"
                     '            raise ProviderRefused(f"{self.name}: {exc} {request}") from exc\n'),
        target="tests/test_claude_provider.py",
        keyword="key_never_reaches",
        tags=("safety",),
    ),
    Mutation(
        id="M568", phase=61,
        description="the budget check before a Claude call is skipped",
        path=APP / "reasoning_provider.py",
        anchor="        claude_spend.ensure_affordable(\n",
        replacement="        (lambda *a, **k: None)(\n",
        target="tests/test_claude_provider.py",
        keyword="step_cap_stops or total_cap_counts",
        tags=("safety", "budget"),
    ),
    Mutation(
        id="M570", phase=61,
        description="the JSON schema gate trusts the model (no code check)",
        path=APP / "reasoning_provider.py",
        anchor='    _check(value, schema, "", errors)\n',
        replacement="    pass\n",
        target="tests/test_claude_provider.py",
        keyword="schema_gate_is_code",
        tags=("honesty", "model"),
    ),
    Mutation(
        id="M571", phase=61,
        description="the response cache is never read, so a repeat call is bought again",
        path=APP / "reasoning_provider.py",
        anchor="        cached = _cache_read(key)\n",
        replacement="        cached = None\n",
        target="tests/test_claude_provider.py",
        keyword="served_from_cache",
        tags=("budget",),
    ),
    Mutation(
        id="M572", phase=61,
        description="OllamaProvider calls the transport without a timeout "
                    "(the first real call failed with a TypeError)",
        path=APP / "reasoning_provider.py",
        anchor='            raw = model_transport.post_json("/api/generate", body, timeout=self.timeout)\n',
        replacement='            raw = model_transport.post_json("/api/generate", body)\n',
        target="tests/test_reasoning_provider.py",
        keyword="explicit_timeout",
        tags=("model",),
    ),
    Mutation(
        id="M573", phase=61,
        description="temperature is sent to a model that rejects it (Sonnet 5: 400)",
        path=APP / "reasoning_provider.py",
        anchor="        if no_temperature(self.requested_model):\n",
        replacement="        if False:\n",
        target="tests/test_claude_provider.py",
        keyword="rejects_temperature",
        tags=("model",),
    ),
)
