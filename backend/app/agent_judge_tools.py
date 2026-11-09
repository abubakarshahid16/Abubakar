"""The judge's toolbox (#1690, part of #805): the agent tools plus ONE decision tool, `judge_row`.

Each row of system A's CRS is a CLAIM. The agent verifies it with open_page, search, get_clause (at the confirmed edition)
and compare_number, then records ONE decision for the row:

  CONFIRM   the row stands: a verified clause quote and either a verified document quote or (for a "missing" claim) a
            statement that it was found nowhere. A CONFIRM that cannot be verified is refused (the agent may retry; at the
            step limit the row is UNSURE).
  REMOVE    the row is wrong. As narrow as code can verify (a wrong REMOVE is the worst mistake): ONLY `already_stated` on a
            row that itself asserts an absence, with a document quote `<row subject>: <number and unit, or a date>` on the
            row's page cell page (`agent_judge_rules.already_stated_problem`). 'complies' and 'not_applicable' never remove:
            they are recorded as UNSURE with a note for the engineer. The evidence also goes through the existing verifier
            (`ai_review_proposals.verify`, the 'remove' path). Every REMOVE additionally needs the local second opinion.
  UNSURE    the default: the row stays, marked 'AI could not confirm'. No evidence needed.

The row's own text is DATA. Nothing in it can change these rules: the rules are code. The evidence quotes come from the
reviewed document and the held standards only; the document id is the run's own, never the model's.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from . import agent_judge_rules as rules
from . import ai_review_proposals
from .agent_tool_schemas import coerce_page
from .agent_tools import (
    MAX_REASON_WORDS,
    MIN_QUOTE_CHARS,
    TOOL_SPECS,
    ToolBox,
    _fold,
    _res,
)
from .agent_trace import words

NOT_MENTIONED = "not_mentioned_is_never_a_reason_to_remove"
DECISIONS = ("CONFIRM", "REMOVE", "UNSURE")
REMOVE_REASONS = (
    "already_stated",
)  # the ONE removal path; complies and not_applicable are only noted for the engineer
NOTES = {  # a REMOVE for one of these reasons is recorded as UNSURE with this note: the row stays
    "not_applicable": "AI suggests not applicable: engineer to decide",
    "complies": "AI suggests complies: engineer to decide",
}
NOT_APPLICABLE_NOTE = NOTES["not_applicable"]
COLOUR = {
    "CONFIRM": "GREEN",
    "UNSURE": "YELLOW",
    "REMOVE": "YELLOW",  # a REMOVE counts as RED only after the second opinion agreed (the runner recolours it)
}  # for the trace's counts; labelled in LIVE.md
LABELS = {
    "GREEN": "CONFIRM",
    "YELLOW": "UNSURE (removals not confirmed stay here)",
    "RED": "REMOVED (second opinion agreed)",
}
KEPT_TOOLS = ("open_page", "search", "get_clause", "compare_number")

_SPEC = {
    "name": "judge_row",
    "description": "Record your ONE decision for the current row: CONFIRM, REMOVE or UNSURE. REMOVE needs a reason_code "
    "(complies, not_applicable or already_stated) and verified quotes; not mentioned is never a reason. UNSURE keeps the row.",
    "params": {"decision": "CONFIRM | REMOVE | UNSURE", "reason_code": "REMOVE only"},
}
TOOL_SPECS_JUDGE: list[dict] = [
    copy.deepcopy(s) for s in TOOL_SPECS if s["name"] in KEPT_TOOLS
]
from .agent_tool_schemas import INPUT_SCHEMAS  # noqa: E402

TOOL_SPECS_JUDGE.append({**_SPEC, "input_schema": INPUT_SCHEMAS["judge_row"]})


def _refused(reason: str) -> dict:
    return _res(
        False,
        {"verdict": "refused", "accepted": False, "reason": reason, "refused": reason},
    )


def _claim_row(row: Mapping) -> dict:
    return {
        "row_kind": "ai_engineering_check",
        "comment": row.get("comment"),
        "standard_reference": row.get("standard_reference"),
        "page_section": row.get("page_section"),
    }


class JudgeToolBox(ToolBox):
    """ToolBox with the judge's tools only (no record_finding, no ask_engineer) and `judge_row`."""

    TOOL_SPECS = TOOL_SPECS_JUDGE
    END_TOOLS = ("judge_row",)  # the loop ends a row when this tool's call is accepted

    def __init__(self, ctx, rows: Mapping[str, Mapping], **kw: Any) -> None:
        super().__init__(ctx, **kw)
        self.rows = rows  # row id -> the claim (comment, page hint, standard reference)
        self.shared = rules.shared_subjects(
            rows.values()
        )  # template prefixes: such rows can only be confirmed or kept
        self._tools = {n: self._tools[n] for n in KEPT_TOOLS}
        self._tools["judge_row"] = self.judge_row
        self.refusals: dict[
            str, int
        ] = {}  # code -> count (RESULTS: unverifiable quotes, never text)

    # ---------------------------------------------------------------- the one decision tool

    def judge_row(
        self,
        decision: object = None,
        reason_code: object = None,
        page: object = None,
        doc_quote: object = None,
        standard: object = None,
        clause: object = None,
        clause_quote: object = None,
        figures: object = None,
        reason: object = None,
        absent: object = None,
    ) -> dict:
        why = self._judge_problem(
            decision,
            reason_code,
            page,
            doc_quote,
            standard,
            clause,
            clause_quote,
            figures,
            reason,
            absent,
        )
        if isinstance(
            why, tuple
        ):  # (code, detail): the detail holds words only, never a quote
            code, detail = why
            self.refusals[code] = self.refusals.get(code, 0) + 1
            out = _refused(code)
            out["result"]["detail"] = detail
            return out
        if isinstance(why, str):
            self.refusals[why.split(":")[0]] = (
                self.refusals.get(why.split(":")[0], 0) + 1
            )
            return _refused(why)
        stored = why  # the stored decision
        self.ctx.findings.add(stored["item"], stored)
        cites = []
        if stored.get("page"):
            cites.append({"doc": stored.get("doc"), "page": stored["page"]})
        if stored.get("standard") and stored.get("clause"):
            cites.append({"doc": stored["standard"], "clause": str(stored["clause"])})
        return _res(
            True,
            {
                "verdict": "accepted",
                "accepted": True,
                "reason": None,
                "item": stored["item"],
                "decision": stored["decision"],
            },
            cites,
        )

    def _judge_problem(
        self,
        decision,
        reason_code,
        page,
        doc_quote,
        standard,
        clause,
        clause_quote,
        figures,
        reason,
        absent,
    ):
        """The refusal code (str), or the decision to store (dict). First failure wins."""
        item = str(self.ctx.current_item or "")
        row = self.rows.get(item)
        if row is None:
            return "row_unknown"
        if self.ctx.findings.has(item):
            return "already recorded"  # the first decision stays
        dec = str(decision or "").strip().upper()
        if dec not in DECISIONS:
            return "decision_not_confirm_remove_or_unsure"
        said = words(reason, MAX_REASON_WORDS)
        base = {
            "item": item,
            "decision": dec,
            "color": COLOUR[dec],
            "doc": self.ctx.document_id,
            "reason": said,
        }
        if dec == "UNSURE":
            return base
        code = str(reason_code or "").strip().lower() if dec == "REMOVE" else None
        if code in NOTES:  # never a REMOVE: the row stays and the engineer decides
            return {
                **base,
                "decision": "UNSURE",
                "color": COLOUR["UNSURE"],
                "reason": NOTES[code],
                "suggests": code,
            }
        if dec == "REMOVE":
            if code not in REMOVE_REASONS:
                return "reason_code_not_already_stated"
            if absent is True or rules.absence(said):
                return NOT_MENTIONED
            subject = rules.row_subject(row.get("comment"))
            if not subject or subject in self.shared:
                return "row_subject_not_derived"  # such a row can only be CONFIRMed or UNSURE
        if dec == "CONFIRM" and absent is True:
            doc_quote = None  # a "missing" claim confirmed: there is no quote to give
        evidence = self._gather(dec, page, doc_quote, standard, clause, clause_quote)
        if isinstance(evidence, str):
            return evidence
        if (
            dec == "REMOVE"
        ):  # the row's subject, page and reason structure first, then the numbers, then the verifier
            bad = (
                self._remove_rules(row, evidence)
                or self._figures_problem(dec, figures)
                or self._remove_verdict(item, row, code, evidence)
            )
        else:
            bad = self._figures_problem(dec, figures)
        if bad:
            return bad
        return {
            **base,
            **evidence,
            **({"reason_code": code} if code else {}),
            **(
                {"absence_unproven": True}
                if dec == "CONFIRM" and absent is True
                else {}
            ),
            **({"figures": figures} if figures else {}),
        }

    def _gather(self, dec, page, doc_quote, standard, clause, clause_quote):
        """The verified evidence (dict) or a refusal code. Page text and clause text are read by code, quotes checked."""
        out: dict = {}
        if doc_quote is not None or dec == "REMOVE":
            number, bad = coerce_page(page)
            if number is None:
                return bad or "page_missing"
            text = self._page_text(self.ctx.document_id, number)
            if text is None:
                return "page_not_read"
            quote = str(doc_quote or "").strip()
            if len(quote) < MIN_QUOTE_CHARS:
                return "evidence_quote_too_short"
            if _fold(quote) not in _fold(text):
                return "document_quote_not_on_page"
            out.update(page=number, doc_quote=quote)
        body, _doc, why = self._clause_text(standard, clause)
        if body is None:
            return f"clause_not_verified:{why}"
        cq = str(clause_quote or "").strip()
        if len(cq) < MIN_QUOTE_CHARS or _fold(cq) not in _fold(body):
            return "clause_quote_not_in_clause"
        out.update(
            standard=str(standard),
            clause=str(clause),
            clause_quote=cq,
        )
        found = self.edition_evidence_seen.get(str(standard))
        if found:
            out["edition_evidence"] = found
        return out

    def _figures_problem(self, dec, figures) -> str | None:
        """A number is decided only by code. CONFIRM may offer figures: each must be decided by compare_number as
        'does_not_meet'. (No REMOVE rests on a figure: 'complies' never removes.)"""
        listed = [
            f
            for f in (figures if isinstance(figures, list) else [])
            if isinstance(f, dict)
        ]
        return (
            self._numbers_problem({"figures": listed}, "RED")
            if dec == "CONFIRM" and listed
            else None
        )

    def _remove_rules(self, row, evidence):
        """What ties a REMOVE to THIS row (see agent_judge_rules): the page cell and page, no absence or repeated text in
        the quotes, then the one removal rule. A refusal code, or a (code, detail) pair when the detail is words only."""
        doc_q, clause_q, comment = (
            evidence["doc_quote"],
            evidence["clause_quote"],
            row.get("comment"),
        )
        if rules.absence(doc_q) or rules.absence(clause_q):
            return NOT_MENTIONED
        pages = rules.row_pages(row)
        if not pages:
            return "row_has_no_page_cell"
        if evidence["page"] not in pages:
            return "page_not_the_rows_page"
        if rules.repeats_row_text(doc_q, comment):
            return "quote_repeats_the_rows_own_text"
        return rules.already_stated_problem(row, doc_q)

    def _remove_verdict(self, item, row, code, evidence) -> str | None:
        """The existing verifier's 'remove' path (`ai_review_proposals.verify`): page, clause held, quote on the page."""
        page, standard, clause = (
            evidence["page"],
            evidence["standard"],
            evidence["clause"],
        )
        text = self._page_text(self.ctx.document_id, page) or ""
        proposal = {
            "type": "remove",
            "confidence": "low",
            "reason": f"judge removal, reason code {code}",
            "row_key": item,
            "basis": "context",
            "page": page,
            "standard": standard,
            "clause": clause,
            "evidence": [{"page": page, "quote": evidence["doc_quote"]}],
        }
        ctx = ai_review_proposals.Context(
            pages={page: text},
            # A's rows are claims, not engine Fail rows: mapped to the removable kind so the verifier's evidence checks decide
            rows={item: _claim_row(row)},
            held={standard: [clause]},
        )
        verdict = ai_review_proposals.verify(proposal, ctx)
        return None if verdict.accepted else f"verify_refused:{verdict.reason}"
