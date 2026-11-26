"""The Administration page's Review model section (planner 25 Nov 2026 22:40; lead-4, 26 Nov 2026).

GET  /api/admin/review-model: the Claude models (fixed, as scored), the installed local models with whether each may be chosen
     and why not, the steps, and what is saved. Reads only; loads no model.
PUT  /api/admin/review-model: save the local default and the per-step picks (`review_model_setting.save`). A signed-in
     administrator only: the choice outlives the sign-in mode, so no anonymous caller may make it.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import admin as admin_mod
from .. import review_model_setting

router = APIRouter()

SIGN_IN_FIRST = "Sign in as an administrator to change the review model."


class ModelRow(BaseModel):
    name: str
    engine: str
    selectable: bool
    why: str | None = None
    score_words: str
    approved: bool
    priced: bool
    used_for: str | None = None
    scored_kinds: list[str] | None = None
    bytes: int | None = None
    price_words: str | None = None
    is_default: bool | None = None
    measured: str | None = None


class Stored(BaseModel):
    default: str | None = None
    steps: dict[str, str] = Field(default_factory=dict)
    set_by: str | None = None
    set_at: str | None = None


class Change(BaseModel):
    slot: str
    old_model: str | None = None
    new_model: str | None = None
    changed_by: str | None = None
    changed_at: str


class ReviewModelOptions(BaseModel):
    claude: list[ModelRow]
    local: list[ModelRow]
    engine_down: bool
    engine_down_words: str | None = None
    steps: list[str]
    answer_model: str
    answer_model_why: str | None = None
    stored: Stored
    history: list[Change] = Field(default_factory=list)
    used_by: str


class ReviewModelSaved(BaseModel):
    stored: Stored


class ReviewModelChoice(BaseModel):
    default: str | None = Field(default=None, max_length=200)
    steps: dict[str, str] = Field(default_factory=dict)


@router.get("/api/admin/review-model", response_model=ReviewModelOptions)
def review_model_options(
    _admin: dict | None = Depends(admin_mod.current_admin),
) -> dict:
    return review_model_setting.options()


@router.put("/api/admin/review-model", response_model=ReviewModelSaved)
def save_review_model(
    choice: ReviewModelChoice, actor: dict | None = Depends(admin_mod.current_admin)
) -> dict:
    if actor is None:
        raise HTTPException(status_code=403, detail=SIGN_IN_FIRST)
    try:
        saved = review_model_setting.save(choice.model_dump(), actor.get("id"))
    except review_model_setting.Refused as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"stored": saved}
