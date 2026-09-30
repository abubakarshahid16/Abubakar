"""Mutations for "AI reads, code checks": backend/app/datasheet_ai.py and its
merge inside backend/app/datasheets._extract_facts (DATASHEET_AI_READER).

1. Flag off asks no model (M1670).
2. The merge: agreement raises confidence below the cap (M1671, M1672),
   disagreement keeps both flagged (M1673, M1674), kinds are respected
   (M1675), an AI-only fact is the model's (M1676), an AI-read page counts
   as read (M1677).
3. The quote is the proof: the rules' value gate does not apply (M1678), a
   quote not on the page is dropped (M1679), two runs must agree (M1680).
4. Failure is a reason: an engine failure (M1681) and a cap stop (M1682).
5. The engines' gates: REASONING_PROVIDER (M1683), claude_spend metering
   (M1684), the model URL check (M1685).
Target: backend/tests/test_datasheet_ai.py.
"""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_datasheet_ai.py"
_AI = APP / "datasheet_ai.py"
_DS = APP / "datasheets.py"
_CD = APP / "claude_datasheet.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1670", phase=1670,
             description="the AI reader runs with DATASHEET_AI_READER=off",
             path=_DS,
             anchor='                          or "off") != "off":\n',
             replacement='                          or "off") != "never":\n',
             target=_T, keyword="flag_off", tags=("datasheet_ai", "critical")),
    Mutation(id="M1671", phase=1671,
             description="an agreement no longer raises the rule fact's confidence",
             path=_DS,
             anchor="                (datasheet_ai.AGREED_CONFIDENCE,\n",
             replacement="                (d[\"rule\"][\"confidence\"],\n",
             target=_T, keyword="agreement_is_one_fact", tags=("datasheet_ai",)),
    Mutation(id="M1672", phase=1672,
             description="agreed confidence reaches 1.0 ('high')",
             path=_AI,
             anchor="AGREED_CONFIDENCE = 0.7\n",
             replacement="AGREED_CONFIDENCE = 1.0\n",
             target=_T, keyword="agreement_is_one_fact", tags=("datasheet_ai", "honesty")),
    Mutation(id="M1673", phase=1673,
             description="a disagreement silently keeps the rule's value (AI reading dropped)",
             path=_AI,
             anchor="                against.setdefault(ri, []).append(ai_i)\n",
             replacement="                pass\n",
             target=_T, keyword="disagreement or four_outcomes", tags=("datasheet_ai", "critical")),
    Mutation(id="M1674", phase=1674,
             description="the rule fact in a disagreement is not flagged conflict",
             path=_DS,
             anchor="                    (GEOMETRY_CONFLICT,\n"
                    "                     provenance_box(d[\"ai\"][0], conflicts_with=ids,\n",
             replacement="                    (None,\n"
                         "                     provenance_box(d[\"ai\"][0], conflicts_with=ids,\n",
             target=_T, keyword="disagreement", tags=("datasheet_ai",)),
    Mutation(id="M1675", phase=1675,
             description="the merge ignores whose value (kind) a column holds",
             path=_AI,
             anchor="                    if (rk is None or rk == a.get(\"kind\")) and values_agree(r, a)]\n",
             replacement="                    if values_agree(r, a)]\n",
             target=_T, keyword="same_kind", tags=("datasheet_ai",)),
    Mutation(id="M1676", phase=1676,
             description="an AI-only fact is written as the rule reader's",
             path=_DS,
             anchor="                extraction_method=datasheet_ai.EXTRACTION_METHOD,\n",
             replacement="                extraction_method=\"extracted\",\n",
             target=_T, keyword="free_text_answer_is_kept", tags=("datasheet_ai",)),
    Mutation(id="M1677", phase=1677,
             description="a page read only by the AI is reported unparsed",
             path=_DS,
             anchor="            page_read = page_written + page_geometry + page_vision + page_ai\n",
             replacement="            page_read = page_written + page_geometry + page_vision\n",
             target=_T, keyword="counts_as_read", tags=("datasheet_ai",)),
    Mutation(id="M1678", phase=1678,
             description="the rules' categorical value gate is applied to AI readings",
             path=_DS,
             anchor="    if is_blank_value(raw)[0]:\n        return \"blank\"\n",
             replacement="    if is_blank_value(raw)[0]:\n        return \"blank\"\n"
                         "    if not states_a_value(value):\n        return \"value gate\"\n",
             target=_T, keyword="free_text_answer_is_kept", tags=("datasheet_ai",)),
    Mutation(id="M1679", phase=1679,
             description="a quote that is not on the page is accepted",
             path=_CD,
             anchor="        if not quote or not _contains(folded_page, quote):\n",
             replacement="        if not quote:\n",
             target=_T, keyword="quote_is_not_on_the_page", tags=("datasheet_ai", "critical")),
    Mutation(id="M1680", phase=1680,
             description="a reading only one of two runs produced is kept",
             path=_CD,
             anchor="    stable = [p for p in first if _identity(p) in seen]\n",
             replacement="    stable = list(first)\n",
             target=_T, keyword="unstable", tags=("datasheet_ai",)),
    Mutation(id="M1681", phase=1681,
             description="an engine failure propagates into ingestion",
             path=_AI,
             anchor="    except Exception as exc:  # noqa: BLE001 - never into ingestion\n"
                    "        return _empty(page_no, engine, error=f\"engine failed ({type(exc).__name__})\")\n",
             replacement="",
             target=_T, keyword="engine_failure", tags=("datasheet_ai", "critical")),
    Mutation(id="M1682", phase=1682,
             description="after a cap refusal the reader keeps calling for later pages",
             path=_AI,
             anchor="        if out.get(\"stopped\"):\n            stopped = out[\"stopped\"]\n",
             replacement="",
             target=_T, keyword="cap_refusal", tags=("datasheet_ai", "budget")),
    Mutation(id="M1683", phase=1683,
             description="the claude engine ignores REASONING_PROVIDER",
             path=_AI,
             anchor="    if code is not None:\n        return None, f\"claude engine unavailable ({code}: {why})\"\n",
             replacement="",
             target=_T, keyword="reasoning_provider or unavailable_engine",
             tags=("datasheet_ai", "egress")),
    Mutation(id="M1684", phase=1684,
             description="the claude engine is not metered by claude_spend",
             path=_AI,
             anchor="    call = claude_budget.Budget(reader_api.model_call_via(claude_spend.metered(\n"
                    "        transport, STEP, unbilled=reader_transport.unbilled)))\n",
             replacement="    call = claude_budget.Budget(reader_api.model_call_via(transport))\n",
             target=_T, keyword="metered or cap_refusal", tags=("datasheet_ai", "budget", "critical")),
    Mutation(id="M1685", phase=1685,
             description="the ollama engine skips the model URL check",
             path=_AI,
             anchor="    except Exception as exc:  # noqa: BLE001 - a refused host is a reason, not a crash\n"
                    "        return None, f\"ollama engine unavailable ({type(exc).__name__})\"\n",
             replacement="    except Exception:  # noqa: BLE001\n        pass\n",
             target=_T, keyword="refuses_a_host", tags=("datasheet_ai", "egress")),
)
