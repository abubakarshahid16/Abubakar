"""The rule-approval screen's routes (order 302.4): list the rule cards, open one, edit it, approve or reject it.

Super user only (`admin.current_admin`: anyone else gets the same 404 the admin screen gives) and AUDITED, ids
and clause numbers only. A decision names the version and the hash the engineer saw; a card that changed
meanwhile answers 409 and writes nothing. The rules of a decision are in `rule_card_versions`.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .. import admin as admin_mod
from .. import errors
from .. import rule_card_versions as versions
from ..api_utils import reject_unknown_params
from ..db import connect

router = APIRouter()


class SeenCard(BaseModel):
    """What the engineer looked at: the decision or edit applies to this version and content only."""

    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    content_hash: str = Field(min_length=64, max_length=64)


class DecisionRequest(SeenCard):
    decision: str = Field(pattern="^(approved|rejected)$")


class EditRequest(SeenCard):
    changes: dict[str, Any] = Field(min_length=1)


def _who(actor: dict | None) -> str:
    return str((actor or {}).get("email") or (actor or {}).get("id") or "")


def _audit(
    action: str, actor: dict | None, card_id: str, detail: str, outcome: str = "ok"
) -> None:
    admin_mod._audit(action, actor, "rule_card", card_id, outcome, detail)


def _fail(exc: versions.CardError) -> HTTPException:
    status = 409 if isinstance(exc, versions.Conflict) else 422
    return HTTPException(
        status_code=status, detail=errors.safe_error(errors.INVALID_PARAMETER, str(exc))
    )


def _find(card_id: str, rules: dict) -> str:
    for equipment_type, checklist in rules["checklists"].items():
        if isinstance(checklist, dict) and any(
            i["id"] == card_id for i in checklist["items"]
        ):
            return equipment_type
    raise HTTPException(
        status_code=404,
        detail=errors.safe_error(errors.NOT_FOUND, "no rule card with that id"),
    )


def _card(card: dict) -> dict:
    """The card for the screen: words, source, rule, state, why, and the cases (expected against got)."""
    return {
        "card_id": card["card_id"],
        "equipment_type": card["equipment_type"],
        "version": card["version"],
        "content_hash": card["content_hash"],
        "state": card["state"],
        "why": card["why"],
        "weak_source": card["weak_source"],
        "basis": card["basis"],
        "written_cases": card["written_cases"],
        "baseline_changed": card["baseline_changed"],
        "versions": card["versions"],
        "decided_by": card["decided_by"],
        "decided_at": card["decided_at"],
        "item": card["item"],
        "cases": card["runs"],
    }


@router.get("/api/rule-cards", dependencies=[Depends(admin_mod.current_admin)])
def list_rule_cards(request: Request):
    """Every card with its state, and the counts per equipment type (its own cards are the denominator)."""
    reject_unknown_params(request, set())
    return versions.listing(connect())


@router.get(
    "/api/rule-cards/{card_id}", dependencies=[Depends(admin_mod.current_admin)]
)
def get_rule_card(card_id: str, request: Request):
    reject_unknown_params(request, set())
    from .. import datasheet_checks as dc

    rules = dc.load_rules()
    return _card(versions.whole(connect(), _find(card_id, rules), card_id, rules))


@router.post("/api/rule-cards/{card_id}/decision")
def decide_rule_card(
    card_id: str,
    body: DecisionRequest,
    actor: dict | None = Depends(admin_mod.current_admin),
):
    """Approve or reject the version the engineer saw. Approve needs the card tested now and a clause number."""
    from .. import datasheet_checks as dc

    rules = dc.load_rules()
    equipment_type = _find(card_id, rules)
    try:
        versions.decide(
            connect(),
            equipment_type,
            card_id,
            body.decision,
            version=body.version,
            seen_hash=body.content_hash,
            actor=_who(actor),
            rules=rules,
        )
    except versions.CardError as exc:
        _audit(
            "rule_card.decision",
            actor,
            card_id,
            f"{body.decision} v{body.version} refused",
            "refused",
        )
        raise _fail(exc) from exc
    _audit("rule_card.decision", actor, card_id, f"{body.decision} v{body.version}")
    return _card(versions.whole(connect(), equipment_type, card_id, rules))


@router.post("/api/rule-cards/{card_id}/edit")
def edit_rule_card(
    card_id: str,
    body: EditRequest,
    actor: dict | None = Depends(admin_mod.current_admin),
):
    """A new version with the changes, tested again at once, with no decision."""
    from .. import datasheet_checks as dc

    rules = dc.load_rules()
    equipment_type = _find(card_id, rules)
    try:
        card = versions.edit(
            connect(),
            equipment_type,
            card_id,
            body.changes,
            version=body.version,
            seen_hash=body.content_hash,
            actor=_who(actor),
            rules=rules,
        )
    except versions.CardError as exc:
        _audit(
            "rule_card.edit",
            actor,
            card_id,
            f"edit of v{body.version} refused",
            "refused",
        )
        raise _fail(exc) from exc
    _audit(
        "rule_card.edit",
        actor,
        card_id,
        f"v{body.version} to v{card['version']}: {', '.join(sorted(body.changes))}",
    )
    return _card(card)
