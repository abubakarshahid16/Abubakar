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
#: Why a row stays UNSURE: a CLOSED set. The code sets it where it can be determined; the agent chooses among the rest.
UNSURE_CODES = (
    "standard_not_held",
    "document_evidence_not_found",
    "claim_unclear",
    "step_limit",
    "error",
)
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
        self.enforce_minimum = True  # tests that are not about the minimum turn it off
        self._seen: dict[
            str, dict
        ] = {}  # item -> pages opened, searches run, early call refused, standards not held
        self.refusals: dict[
            str, int
        ] = {}  # code -> count (RESULTS: unverifiable quotes, never text)

    # ---------------------------------------------------------------- what the agent did for this row

    def _seen_for(self, item: str) -> dict:
        return self._seen.setdefault(
            item, {"pages": set(), "searches": [], "early": False, "not_held": set()}
        )

    def open_page(self, doc: object = None, page: object = None) -> dict:
        out = super().open_page(doc, page)
        if (
            out.get("ok")
            and isinstance(out.get("result"), dict)
            and out["result"].get("page")
        ):
            self._seen_for(str(self.ctx.current_item or ""))["pages"].add(
                out["result"]["page"]
            )
        return out

    def search(self, query: object = None, scope: object = None) -> dict:
        out = super().search(query, scope)
        if out.get("ok") and isinstance(query, str):
            self._seen_for(str(self.ctx.current_item or ""))["searches"].append(query)
        return out

    def get_clause(self, standard: object = None, clause: object = None) -> dict:
        out = super().get_clause(standard, clause)
        state = str((out.get("result") or {}).get("state") or "")
        if not out.get("ok") and state.startswith("not held"):
            self._seen_for(str(self.ctx.current_item or ""))["not_held"].add(
                str(standard)
            )
        return out

    def standard_held(self, row: Mapping, item: str | None = None) -> bool | None:
        """Is the standard the row cites held at a confirmed edition? None when the row names none (not determinable)."""
        ref = row.get("reference") or rules.parse_reference(
            row.get("standard_reference")
        )
        if not ref or not ref.get("standard"):
            return None
        from . import standard_ids

        seen = self._seen_for(str(item or self.ctx.current_item or ""))["not_held"]
        if any(standard_ids.same_standard(ref["standard"], n) for n in seen):
            return False
        for name, edition in self.ctx.editions.items():
            if standard_ids.same_standard(ref["standard"], name):
                return self._evidence(name, edition).get("status") == "confirmed"
        return False

    def minimum_missing(self, item: str, row: Mapping) -> list[str]:
        """What the agent must still do before it may record CONFIRM or UNSURE: open the row's cited page and search for
        the row's subject words (no page cell: two searches)."""
        if not self.enforce_minimum:
            return []
        seen, pages = self._seen_for(item), rules.row_pages(row)
        subject = rules.head_subject(row.get("comment")) or frozenset(
            rules._content_words(" ".join(str(row.get("comment") or "").split()[:8]))
        )
        hit = [
            q
            for q in seen["searches"]
            if not subject or subject & set(rules._content_words(q))
        ]
        if pages:
            missing = (
                []
                if set(pages) & seen["pages"]
                else [f"open the row's cited page ({pages[0]}) with open_page"]
            )
            return missing + (
                [] if hit else ["run one search for the row's subject words"]
            )
        return (
            []
            if len(hit) >= 2
            else ["the row names no page: run two searches for its subject words"]
        )

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
        unsure_code: object = None,
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
            unsure_code,
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
        unsure_code=None,
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
        held = self.standard_held(row)
        early = self._early(item, row, base, held)
        if early is not None:
            return early
        if dec == "UNSURE":
            return self._unsure(base, unsure_code, held)
        code = str(reason_code or "").strip().lower() if dec == "REMOVE" else None
        if code in NOTES:  # never a REMOVE: the row stays and the engineer decides
            return self._unsure(
                {**base, "reason": NOTES[code], "suggests": code}, None, held
            )
        if dec == "REMOVE":
            if code not in REMOVE_REASONS:
                return "reason_code_not_already_stated"
            if absent is True or rules.absence(said):
                return NOT_MENTIONED
            subject = rules.row_subject(row.get("comment"))
            if not subject or subject in self.shared:
                return "row_subject_not_derived"  # such a row can only be CONFIRMed or UNSURE
        return self._evidenced(
            item,
            row,
            base,
            held,
            code,
            (page, doc_quote, standard, clause, clause_quote, figures, absent),
        )

    def _evidenced(self, item, row, base, held, code, given):
        """CONFIRM or REMOVE: gather and check the evidence, the REMOVE rules, the figures; then the decision to store."""
        page, doc_quote, standard, clause, clause_quote, figures, absent = given
        dec = base["decision"]
        if dec == "CONFIRM" and absent is True:
            doc_quote = None  # a "missing" claim confirmed: there is no quote to give
        unheld = (
            dec == "CONFIRM" and held is False
        )  # the standard is not held: only the DOCUMENT side can be confirmed
        if unheld and absent is not True and not str(doc_quote or "").strip():
            return "document_quote_required"  # the standard is not held: the document side needs a verified quote
        if unheld and absent is True and (bad := self._absence_problem(item, row)):
            return bad
        evidence = self._gather(
            dec, page, doc_quote, standard, clause, clause_quote, need_clause=not unheld
        )
        if isinstance(evidence, str):
            return evidence
        if (
            unheld
            and evidence.get("page")
            and rules.row_pages(row)
            and evidence["page"] not in rules.row_pages(row)
        ):
            return "page_not_the_rows_page"
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
                if dec == "CONFIRM" and absent is True and not unheld
                else {}
            ),
            **(
                {"standard_not_held": True, "absence_checked_on_page": True}
                if unheld and absent is True
                else {}
            ),
            **({"standard_not_held": True} if unheld and absent is not True else {}),
            **({"figures": figures} if figures else {}),
        }

    def _early(self, item, row, base, held):
        """The evidence minimum: before CONFIRM, REMOVE or UNSURE the agent must have opened the row's cited page and searched
        for its subject. The first early call is refused with a hint (once); a second is accepted but coded claim_unclear."""
        missing = self.minimum_missing(item, row)
        if not missing:
            return None
        seen = self._seen_for(item)
        if not seen["early"]:
            seen["early"] = True
            return "evidence_minimum_not_met", {"still_required": missing}
        return self._unsure(
            {**base, "reason": "decided before the evidence minimum was met"},
            "claim_unclear",
            held,
        )

    @staticmethod
    def _unsure(base, agent_code, held):
        """UNSURE with a reason CODE from the closed set: set by code where it can be determined (the standard is not held),
        else the agent's choice, anything else claim_unclear. The reason text is never empty."""
        chosen = str(agent_code or "").strip().lower()
        code = (
            "standard_not_held"
            if held is False
            else (chosen if chosen in UNSURE_CODES else "claim_unclear")
        )
        return {
            **base,
            "decision": "UNSURE",
            "color": COLOUR["UNSURE"],
            "unsure_code": code,
            "reason": base.get("reason") or f"unsure: {code}",
        }

    def _absence_problem(self, item, row):
        """A missing-item claim confirmed WITHOUT a clause: code checks the cited page was opened and does not hold the
        subject's words. (Absence is never a quote.)"""
        pages = rules.row_pages(row)
        subject = rules.head_subject(row.get("comment"))
        if not pages or not subject:
            return "absence_not_verifiable"
        if pages[0] not in self._seen_for(item)["pages"]:
            return "absence_needs_the_page_opened"
        text = self._page_text(self.ctx.document_id, pages[0]) or ""
        return (
            "subject_words_are_on_the_page" if rules.words_in(text, subject) else None
        )

    def _gather(
        self, dec, page, doc_quote, standard, clause, clause_quote, need_clause=True
    ):
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
        if not need_clause:
            return out
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
