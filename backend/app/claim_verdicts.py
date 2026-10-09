"""A verdict per claim unit: pass, fail or query (W5b-06, #530).

`claim_units` breaks a written document into checkable units. This module says
what is known about each one, in three words only:

  * PASS   - at least one piece of evidence supports the unit, none contradicts
    it, and every piece of evidence has a citation that resolves (a quote and a
    page, or a library document);
  * FAIL   - at least one cited piece of evidence contradicts the unit;
  * QUERY  - everything else: no evidence, evidence without a citation,
    supporting and contradicting evidence together (an engineer decides), a
    figure, a unit nothing can judge yet.

THE RULES THAT MAKE IT HONEST (CLAUDE.md rule 4):
  * QUERY NEVER BECOMES COMPLIANT. There is no path from "no evidence" or
    "not mentioned" to PASS.
  * A PIECE OF EVIDENCE WITHOUT A CITATION IS NOT EVIDENCE. It is ignored for
    PASS and for FAIL, and the unit says so.
  * CONFIDENCE IS NEVER "HIGH": PASS is capped at 0.7, FAIL at 0.7, QUERY is
    None (an unjudged unit has no confidence, never 0).
  * EVERY FIGURE IS "ENGINEER REVIEW REQUIRED" until a vision reader exists:
    a figure unit is always QUERY, whatever evidence is offered for it.

WHERE EVIDENCE COMES FROM is the caller's: `judge(unit, evidence)` is pure.
`verdicts_for_document` ships ONE real evidence source, the library: a
`reference` unit (a standard the document names) PASSes when the library holds
that standard (the evidence is the library document) and is QUERY, "standard
not held", when it does not - never met. Obligations and table rows are QUERY
("no baseline compared yet") until a comparison source (a playbook, a
standard's requirements) is wired to them; saying so is the point.

No model, no network, no database write.
"""
from __future__ import annotations

from . import applicability, claim_units, standards

PASS, FAIL, QUERY = "pass", "fail", "query"
VERDICTS = (PASS, FAIL, QUERY)

#: Even a clean pass is a reading, not a proof (CLAUDE.md rule 4).
CONFIDENCE_CEILING = 0.7
ENGINEER_REVIEW = "engineer review required"

SUPPORTS, CONTRADICTS = "supports", "contradicts"


def _cited(item: dict) -> bool:
    """Evidence resolves when it names a library document, or a quote with a page."""
    if item.get("document_id"):
        return True
    return bool((item.get("quote") or "").strip()) and item.get("page") is not None


def judge(unit: dict, evidence: list[dict] | None) -> dict:
    """The verdict for one unit given the evidence offered for it.

    `evidence` items: {"stance": "supports" | "contradicts", "quote": str,
    "page": int, "document_id": str, "confidence": float (optional)}.
    """
    base = {"unit_id": unit["id"], "kind": unit["kind"], "page": unit["page"],
            "citation": unit.get("citation"), "engineer_review_required": False}
    items = list(evidence or [])
    if unit["kind"] == claim_units.KIND_FIGURE:
        return {**base, "verdict": QUERY, "confidence": None, "evidence": [],
                "engineer_review_required": True,
                "reason": f"{ENGINEER_REVIEW}: a figure cannot be read yet (no vision reader)"}
    cited = [e for e in items if _cited(e)]
    uncited = len(items) - len(cited)
    supports = [e for e in cited if e.get("stance") == SUPPORTS]
    contradicts = [e for e in cited if e.get("stance") == CONTRADICTS]
    note = f" ({uncited} piece(s) of evidence without a citation ignored)" if uncited else ""
    if contradicts and supports:
        return {**base, "verdict": QUERY, "confidence": None, "evidence": cited,
                "reason": "evidence both supports and contradicts this unit: an engineer decides" + note}
    if contradicts:
        return {**base, "verdict": FAIL, "confidence": _confidence(contradicts), "evidence": contradicts,
                "reason": "cited evidence contradicts this unit" + note}
    if supports:
        return {**base, "verdict": PASS, "confidence": _confidence(supports), "evidence": supports,
                "reason": "cited evidence supports this unit and none contradicts it" + note}
    return {**base, "verdict": QUERY, "confidence": None, "evidence": [],
            "reason": ("no evidence with a citation was found for this unit" + note)}


def _confidence(items: list[dict]) -> float:
    given = [float(e["confidence"]) for e in items if e.get("confidence") is not None]
    return round(min(min(given) if given else CONFIDENCE_CEILING, CONFIDENCE_CEILING), 3)


def verdicts_for_document(document_id: str, *, allowed_document_ids: frozenset[str],
                          evidence_for=None) -> dict:
    """Every unit of one document with its verdict.

    `evidence_for(unit) -> list[evidence]` is an optional extra source; the
    library check for `reference` units always runs. A document that is not
    readable, has no text or has no unit carries the unit report's own state.
    """
    report = claim_units.units_for_document(document_id, allowed_document_ids=allowed_document_ids)
    library = []
    if any(u["kind"] == claim_units.KIND_REFERENCE for u in report["units"]):
        library = standards.list_standards(allowed_document_ids=allowed_document_ids, include_superseded=True)
    verdicts = []
    for unit in report["units"]:
        evidence = list(evidence_for(unit)) if evidence_for else []
        if unit["kind"] == claim_units.KIND_REFERENCE:
            held = applicability.find_standard(library, unit["text"])
            if held is not None:
                evidence.append({"stance": SUPPORTS, "document_id": held["id"],
                                 "quote": None, "page": None,
                                 "note": "the library holds this standard"})
        result = judge(unit, evidence)
        if unit["kind"] == claim_units.KIND_REFERENCE and result["verdict"] == QUERY and not evidence:
            result["reason"] = "standard not held in the library: not met, an engineer is asked"
        elif unit["kind"] in (claim_units.KIND_OBLIGATION, claim_units.KIND_TABLE_ROW) and not evidence:
            result["reason"] = "no baseline has been compared with this unit yet"
        verdicts.append(result)
    counts = {v: sum(1 for r in verdicts if r["verdict"] == v) for v in VERDICTS}
    return {"document_id": document_id, "state": report["state"], "units_total": len(verdicts),
            "counts": counts,
            "engineer_review_required": sum(1 for r in verdicts if r["engineer_review_required"]),
            "pages_unread": report["pages_unread"], "verdicts": verdicts}
