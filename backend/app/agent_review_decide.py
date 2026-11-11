"""The AI reviewer's per-item decision: evidence, the gate, the holds, the absence proof, the context check (F4).

A mixin of `agent_review_run.Runner` (split out so no file passes the size bar). Every guard here only makes a line LESS
confident; the one exit that finishes a line is `Runner.exit_line`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from . import agent_claude, agent_run_second
from . import agent_review_absence as absence
from . import agent_review_context as ctxc
from . import agent_review_crs as crs_lines
from . import agent_review_verdict as verdict
from .agent_review_request import (
    ABSENCE_SECOND_MAX_TOKENS,
    ABSENCE_SECOND_SYSTEM,
    FATAL,
    FINAL_MAX_TOKENS,
    FINAL_MODEL,
    TIGHTENING,
    _hints,
    _text_of,
    deferred_mark,
    held_texts,
    reason_of,
)
from .agent_trace import words
from .reader_api import _fold


class DecideMixin:
    # ---- per item
    def _evidence(
        self, item: dict, answer: Mapping, pages: Mapping[int, str], error: str | None
    ) -> dict:
        """What code verified for one item: the held texts, the quote checks, the AI's verdict word and reason code."""
        held = held_texts(item, self.clauses)
        clause_text, held_kind = (
            (held[0]["text"], held[0]["kind"]) if held else (None, None)
        )
        for h in held:
            if verdict.check_clause_quote(answer.get("clause_quote"), h["text"])[0]:
                clause_text, held_kind = h["text"], h["kind"]
                break
        requirement = next(
            (h["text"] for h in held if h["kind"] == "requirement"), None
        )
        checks = verdict.check_quotes(
            answer,
            pages,
            clause_text,
            requirement if held_kind == "requirement" else None,
        )
        ai = verdict.ai_verdict_word(answer.get("verdict"))
        reason_code, searched = reason_of(answer, ai, error, pages)
        if reason_code in TIGHTENING:
            ai = verdict.QUERY  # code tightens, never loosens: an unsupported Fail or Pass is asked as a query
        return {
            "held": held,
            "held_kind": held_kind,
            "requirement": requirement,
            "checks": checks,
            "ai": ai,
            "reason_code": reason_code,
            "searched": searched,
            "absent": verdict.says_absent(answer),
        }

    def _gate(
        self,
        item: dict,
        answer: Mapping,
        ev: Mapping,
        lead_model: str | None,
        error: str | None,
        box: Any,
    ) -> dict:
        """The decision of the gate for one item, with the second opinion and the absence proof when they are earned."""
        iid, checks, ai = str(item.get("item_id")), ev["checks"], ev["ai"]
        # a rule whose tier is not Owner / Engineer / AI approved never buys a call beyond the lead's own answer
        allowed = verdict.calls_allowed(item, self.tier_lookup)
        out: dict = {
            "second": None,
            "compare": None,
            "proof": None,
            "absence_second": None,
            "comment": answer.get("comment"),
        }
        if verdict.is_number_item(item):
            if not error and checks.both:
                out["compare"] = verdict.compare_figures(box, answer)
            out["decision"] = verdict.number_verdict(
                out["compare"], checks, answer, error=error
            )
        else:
            if (
                allowed
                and verdict.needs_second_opinion(ai, checks, error, ev["absent"])
                and not self._stop.is_set()
            ):
                try:
                    out["second"] = self.second_opinion(iid, ai, answer)
                except FATAL as exc:
                    self._halt(exc)
            out["decision"] = verdict.textual_verdict(
                ai, checks, out["second"], lead_model, error=error, absent=ev["absent"]
            )
        if ev["reason_code"] == "absent" and not error:
            out["decision"] = {
                **out["decision"],
                "verdict": verdict.QUERY,
                "decided_by": verdict.BY_ENGINEER,
                "why": "not shown on the sheet; code cannot prove an absence",
            }
            if (
                self.absence_check
                and allowed
                and verdict.ai_verdict_word(answer.get("verdict")) == verdict.FAIL
            ):
                got = self.absence_decision(
                    item, answer, checks, ev["requirement"], lead_model
                )
                out["decision"], out["proof"], out["absence_second"] = got
                if got[0]["verdict"] == verdict.FAIL:
                    out["comment"] = absence.comment(
                        got[1].field_words, item.get("standard"), item.get("clause")
                    )
        return out

    def decide(
        self,
        item: dict,
        answer: Mapping | None,
        pages: Mapping[int, str],
        lead_model: str | None,
        error: str | None,
        box: Any,
        usd_share: float,
    ) -> dict:
        """One line, by code."""
        iid = str(item.get("item_id"))
        answer = answer or {}
        if answer == {} and not error:
            error = "no_answer_for_item"
        ev = self._evidence(item, answer, pages, error)
        g = self._gate(item, answer, ev, lead_model, error, box)
        # F1 (conditional rule), F3 (table row or note), then THE cap of a rule that is not approved
        decision = verdict.apply_holds(
            g["decision"],
            item,
            clause_quote=answer.get("clause_quote"),
            requirement=ev["requirement"],
            clause_sources=[self.clauses.source(h["ref"]) for h in ev["held"]],
        )
        decision, ctx_info = self.context_check_fail(
            iid,
            item,
            [answer.get("paper_quote")],
            pages,
            ev["requirement"] or answer.get("clause_quote"),
            decision,
            lead_model,
        )
        label = str(answer.get("field_label") or "").strip()
        label_ok = bool(label) and any(
            _fold(label) in _fold(t) for t in pages.values() if t
        )
        reason_code, deferred_page = ev["reason_code"], None
        if (
            decision["verdict"] == verdict.PASS
        ):  # deferral guard: a value marked 'By Contractor' is not confirmed
            guard = self.pass_guard(item, label if label_ok else "")
            if guard is not None:
                decision, reason_code, deferred_page = guard
        self._ctx.setdefault(iid, {}).update(
            second_opinion_answer=g["second"], absence_second_answer=g["absence_second"]
        )
        return self._line(
            item,
            answer,
            ev,
            g,
            decision,
            ctx_info,
            error,
            lead_model,
            usd_share,
            (label if label_ok else None, label, reason_code, deferred_page),
        )

    def _line(
        self,
        item: dict,
        answer: Mapping,
        ev: Mapping,
        g: Mapping,
        decision: Mapping,
        ctx_info: Mapping,
        error: str | None,
        lead_model: str | None,
        usd_share: float,
        label_info: tuple,
    ) -> dict:
        """The stored line of one item (no model text beyond the AI's own quotes and sentences)."""
        field, label, reason_code, deferred_page = label_info
        second, proof, absence_second = g["second"], g["proof"], g["absence_second"]
        return {
            "item_id": str(item.get("item_id")),
            "source": item.get("source"),
            "standard": item.get("standard"),
            "clause": item.get("clause"),
            "clause_page": self.clauses.page(item.get("clause_quote_ref"))
            or item.get("clause_page"),
            "rule_kind": item.get("rule_kind"),
            "field_roles": item.get("field_roles") or [],
            "field": field,
            "page_hint": _hints(item)
            if item.get("page_hint_source") in (None, "items")
            else [],
            "page_hint_source": item.get("page_hint_source"),
            "verdict": decision["verdict"],
            "decided_by": decision["decided_by"],
            "why": decision.get("why"),
            "model": lead_model if lead_model and lead_model != "unknown" else None,
            "second_opinion": None
            if second is None
            else {
                k: second.get(k)
                for k in ("agree", "model", "reason")
                if k != "reason" or second.get("reason")
            },
            "ai_verdict": verdict.ai_verdict_word(answer.get("verdict")),
            "reason_code": reason_code,
            "reason_code_ai": str(answer.get("reason_code") or "") or None,
            "deferred_page": deferred_page,
            "pages_searched": ev["searched"],
            "requirement": ev["requirement"],
            "field_label_ai": label or None,
            "paper_figure": answer.get("paper_figure") or None,
            "clause_figure": answer.get("clause_figure") or None,
            "clause_quote_from": ev["held_kind"],
            "reasoning": crs_lines.two_sentences(answer.get("reasoning")),
            "comment": words(g["comment"], crs_lines.MAX_COMMENT_WORDS),
            "paper_quote": answer.get("paper_quote") or None,
            "paper_page": verdict._page_no(answer.get("paper_page")),
            "clause_quote": answer.get("clause_quote") or None,
            "quotes_checked": ev["checks"].to_json(),
            "compare": g["compare"],
            "error": error,
            "absence_check": None if proof is None else proof.to_json(),
            "absence_code": decision.get("absence_code"),
            "rule_tier": item.get("rule_tier"),
            "rule_unapproved_why": item.get("rule_unapproved_why"),
            "rule_label": item.get("rule_label"),
            "unapproved_cap": bool(decision.get("unapproved_cap")),
            "conditional_hold": bool(decision.get("conditional")),
            "table_note_hold": decision.get("table_note"),
            "context_hold": bool(decision.get("context_hold")),
            "context_check": None,
            "context_hash": None,
            "context_limits": None,
            "context_condition_met": None,
            **ctx_info,
            "usd": round(
                usd_share
                + float((second or {}).get("usd") or 0.0)
                + float((absence_second or {}).get("usd") or 0.0),
                6,
            ),
        }

    # ---- the absence proof (off by default)
    def absence_decision(
        self,
        item: Mapping,
        answer: Mapping,
        checks: Any,
        requirement: str | None,
        lead_model: str | None,
    ) -> tuple[dict, Any, dict | None]:
        """(decision, proof, second). Fail only when code proves the absence, the clause quote is verified and strong, and a
        DIFFERENT model asked on the absence claim agrees. Else Query with the why."""
        texts = {
            n: self.pages.page(self.paper, n) or ""
            for n in range(1, self.total_pages + 1)
        }
        sentence = requirement or (
            answer.get("clause_quote") if checks.clause else None
        )
        proof = absence.prove(
            item,
            sentence,
            texts,
            self.total_pages,
            getattr(self.pages, "ledger_rows", None),
            list(getattr(self.pages, "facts", []) or []),
            self.carried,
            deferred=lambda w: deferred_mark(
                w, self.pages, self.paper, self.total_pages
            ),
        )

        def query(code: str) -> tuple[dict, Any, dict | None]:
            why = proof.why if code == proof.code else absence.ABSENCE_WHY[code]
            return (
                {
                    "verdict": verdict.QUERY,
                    "decided_by": verdict.BY_ENGINEER,
                    "why": why,
                    "absence_code": code,
                },
                proof,
                second,
            )

        second = None
        if not proof.proven:
            return query(str(proof.code))
        if not (checks.clause and checks.clause_strong):
            return query("absence_clause_weak")
        if self._stop.is_set():
            return query("absence_no_second_opinion")
        try:
            second = self.absence_second(item, answer, proof)
        except FATAL as exc:
            self._halt(exc)
            return query("absence_no_second_opinion")
        if second.get("model"):
            self.second_models.add(second["model"])
        if second.get("agree") is not True:
            return query(
                "absence_second_disagreed"
                if second.get("agree") is False
                else "absence_no_second_opinion"
            )
        if not agent_run_second.models_differ([lead_model or ""], second.get("model")):
            return query("absence_second_same_model")
        return (
            {"verdict": verdict.FAIL, "decided_by": verdict.BY_ABSENCE, "why": None},
            proof,
            second,
        )

    def absence_parts(self, item: Mapping, answer: Mapping, proof: Any) -> dict:
        content: list[dict] = [
            {
                "type": "text",
                "text": f'<paper document="{self.paper}" page="{n}">\n'
                f"{self.pages.page(self.paper, n) or ''}\n</paper>",
            }
            for n in range(1, self.total_pages + 1)
        ]
        if content:
            content[-1] = {**content[-1], "cache_control": {"type": "ephemeral"}}
        claim = {
            "field": list(proof.field_words),
            "standard": item.get("standard"),
            "clause": item.get("clause"),
            "requirement_quote": answer.get("clause_quote"),
            "claim": "The paper does not state this field on any page.",
            "question": 'Is the claim true? Reply with ONE JSON object: {"agree": true or false}',
        }
        content.append({"type": "text", "text": json.dumps(claim, ensure_ascii=False)})
        return {
            "system": [
                {
                    "type": "text",
                    "text": ABSENCE_SECOND_SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "messages": [{"role": "user", "content": content}],
        }

    def absence_second(self, item: Mapping, answer: Mapping, proof: Any) -> dict:
        """One call to the SECOND model through the lane. The first call of a run goes alone so the page prefix is written
        to the cache once; the rest read it."""
        parts = self.absence_parts(item, answer, proof)

        def ask() -> dict:
            self.calls["second"] += 1
            raw, usd = self.call(
                agent_claude.SECOND_MODEL, parts, ABSENCE_SECOND_MAX_TOKENS
            )
            obj = agent_claude.parse_json_object(_text_of(raw)) or {}
            agree = obj.get("agree") if isinstance(obj, dict) else None
            return {
                "agree": agree if isinstance(agree, bool) else None,
                "model": agent_claude._answered_model(raw),
                "usd": usd,
            }

        try:
            if not self._warmed:
                with self._warm:
                    if not self._warmed:
                        try:
                            return ask()
                        finally:
                            self._warmed = True
            return ask()
        except FATAL:
            raise
        except agent_claude.AgentClaudeError:
            return {"agree": None, "model": None, "usd": 0.0}

    # ---- F4: the context check before a Fail is proven
    def context_check_fail(
        self,
        iid: str,
        item: Mapping,
        paper_quotes: list,
        pages: Mapping[int, str],
        rule_text: str | None,
        decision: Mapping,
        lead_model: str | None,
    ) -> tuple[dict, dict]:
        """F4 (the core's `check_fail`): before a Fail is proven, ONE call with the rule-book page. The result can only HOLD
        the Fail. A Fail is proven only if THIS run made the check and it said proven; every other path holds it."""
        if decision.get("verdict") != verdict.FAIL or not self.context_check:
            return dict(decision), {}

        def ask(parts: dict) -> dict:
            with self._lock:
                self.calls["context"] += 1
            raw, usd = self.call(FINAL_MODEL, parts, FINAL_MAX_TOKENS)
            return {
                "obj": agent_claude.parse_json_object(_text_of(raw)),
                "model": agent_claude._answered_model(raw),
                "usd": usd,
            }

        got = ctxc.check_fail(
            decision,
            rule_text=rule_text,
            paper_quotes=paper_quotes,
            paper_pages=pages,
            rule_doc=item.get("standard_document_id"),
            rule_page=self.clauses.page(item.get("rule_quote_ref"))
            or item.get("clause_page"),
            clause=item.get("clause"),
            std_pages=self.std_pages,
            ask=None if self._stop.is_set() else ask,
            lead_model=lead_model,
            fatal=FATAL,
        )
        if got.fatal is not None:
            self._halt(got.fatal)
        if got.exchange:
            self._ctx.setdefault(iid, {})["context_exchange"] = got.exchange
        return got.decision, got.info

    def pass_guard(
        self, item: Mapping, label: str
    ) -> tuple[dict, str, int | None] | None:
        """(decision, reason code, deferred page) when a Pass must become a Query, else None. Field words: the item's roles,
        else the field label found on the page. Unknown field words: Query on the safe side; the field marked deferred on any
        page ('By Contractor', 'TBA', ...): Query."""
        from .agent_bind import content_words

        field = (
            " ".join(str(r).replace("_", " ") for r in item.get("field_roles") or [])
            or label
        )
        if not content_words(field):
            return (
                {
                    "verdict": verdict.QUERY,
                    "decided_by": verdict.BY_ENGINEER,
                    "why": "field words unknown: code cannot check the sheet for a deferral mark",
                },
                "field_unknown_cannot_check_deferral",
                None,
            )
        page = deferred_mark(field, self.pages, self.paper, self.total_pages)
        if page is None:
            return None
        return (
            {
                "verdict": verdict.QUERY,
                "decided_by": verdict.BY_ENGINEER,
                "why": f"the sheet marks this value as not final on page {page}",
            },
            "value_deferred",
            page,
        )
