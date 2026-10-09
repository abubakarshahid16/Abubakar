"""#530: a verdict per claim unit. Ids M5501-M5512."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_w5b_530_claim_verdicts.py"
_V = APP / "claim_verdicts.py"
_TAG = ("w5b", "honesty")


def _m(i, desc, anchor, repl, kw=None, path=_V):
    return Mutation(id=f"M{i}", phase=i, description=desc, path=path, anchor=anchor,
                    replacement=repl, target=_T, keyword=kw, tags=_TAG)


MUTATIONS: tuple[Mutation, ...] = (
    _m(5501, "a unit with no evidence passes (not mentioned reads as compliant)",
       '    return {**base, "verdict": QUERY, "confidence": None, "evidence": [],\n            "reason": ("no evidence',
       '    return {**base, "verdict": PASS, "confidence": None, "evidence": [],\n            "reason": ("no evidence',
       "no_evidence_is_a_query or baseline"),
    _m(5502, "evidence without a citation counts",
       "    cited = [e for e in items if _cited(e)]", "    cited = list(items)", "without_a_citation"),
    _m(5503, "a quote without a page is a citation",
       "    return bool((item.get(\"quote\") or \"\").strip()) and item.get(\"page\") is not None",
       "    return bool((item.get(\"quote\") or \"\").strip())", "without_a_citation"),
    _m(5504, "a library document is not a citation",
       "    if item.get(\"document_id\"):\n        return True\n", "", "library_document or holds_passes"),
    _m(5505, "contradicting evidence is ignored", "    if contradicts:\n", "    if False:\n", "contradicting_evidence_fails"),
    _m(5506, "support beats contradiction instead of asking an engineer",
       "    if contradicts and supports:", "    if False:", "together_is_a_query"),
    _m(5507, "the confidence ceiling is not applied",
       "    return round(min(min(given) if given else CONFIDENCE_CEILING, CONFIDENCE_CEILING), 3)",
       "    return round(min(given) if given else CONFIDENCE_CEILING, 3)", "never_above_the_ceiling"),
    _m(5508, "a figure can pass on offered evidence",
       "    if unit[\"kind\"] == claim_units.KIND_FIGURE:\n        return", "    if False:\n        return",
       "figure_is_always_a_query"),
    _m(5509, "pictures on a page are not units",
       "            units += figures_on_page(document_id, page[\"page_no\"], stored)", "            pass",
       "every_picture", path=APP / "claim_units.py"),
    _m(5510, "a standard the library holds is not used as evidence",
       "            if held is not None:\n                evidence.append(", "            if False:\n                evidence.append(",
       "holds_passes or route_returns"),
    _m(5511, "a standard not held does not say so",
       "            result[\"reason\"] = \"standard not held in the library: not met, an engineer is asked\"",
       "            pass", "holds_passes"),
    _m(5512, "the count of units needing an engineer is not reported",
       "            \"engineer_review_required\": sum(1 for r in verdicts if r[\"engineer_review_required\"]),",
       "            \"engineer_review_required\": 0,", "every_picture"),
)
