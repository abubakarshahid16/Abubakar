"""Administration: users, disciplines, grants, the model unload, the read-only
database explorer and the document-kind routing run.

Moved out of main.py with no logic change (planner order 79a, #692; system map target structure).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .. import admin as admin_mod
from .. import admin_explorer as explorer_mod
from .. import doc_router as doc_router_mod
from .. import errors, live_guard, schemas
from .. import model_memory as model_memory_mod
from ..api_utils import reject_unknown_params
from ..config import settings
from ..db import connect
from ..paging import limit_param, offset_param, page_body
from . import rule_cards as api_rule_cards

router = APIRouter()
router.include_router(api_rule_cards.router)  # order 302.4: the rule-approval screen's routes


@router.post("/api/admin/document-kinds/route", response_model=schemas.DocumentKindRouted,
             responses={**schemas.ERRORS_404})
def route_document_kinds(_admin: dict | None = Depends(admin_mod.current_admin)):
    """Route every document that has no routing yet (or an older router's).
    Documents already in the library when the router arrived need this once.
    Confirmed kinds are never touched. Returns counts only."""
    return doc_router_mod.route_unrouted()


# ------------------------------------------------------------------ admin
#
# The administration screen: users, disciplines and document grants, replacing
# `scripts/seed_access.py`, including one-time password setup and reset. Implements
# `docs/design-admin-screen.md`, which was written before these routes existed.
#
# EVERY ROUTE HERE DEPENDS ON `admin.current_admin`, AND A NON-ADMIN GETS 404.
# Not 403. A 403 confirms both that the route exists and that the caller found
# the thing it guards, and the admin surface is the most interesting one on
# this API to probe. It is the same rule `require_document` already follows for
# a document the caller may not read, and it is why these routes take
# `current_admin` rather than `current_scope`: the question is not which
# documents this request may see, it is whether this request may be here at
# all.


@router.post("/api/admin/models/unload", response_model=schemas.AdminModelsFreed,
             responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def admin_free_model_memory(request: Request,
                            actor: dict | None = Depends(admin_mod.current_admin)):
    """Give back the memory the local models hold (#666): ask Ollama to unload
    every resident model (keep_alive 0). A non-admin gets the same 404 as every
    other route here. Nothing is sent but model names; the next question pays a
    cold load, which the button's label says."""
    reject_unknown_params(request, set())
    return model_memory_mod.free_all()


class DatabaseShape(BaseModel):
    live_shaped: bool = Field(
        description="whether this server's database path has the live app's "
        "shape (backend/data/rag_intelligence.sqlite): a boolean about the "
        "path, never the path"
    )


def _database_is_live_shaped() -> bool:
    return live_guard.is_live_shaped(settings.db_path)


@router.get(
    "/api/admin/database-shape",
    response_model=DatabaseShape,
    dependencies=[Depends(admin_mod.current_admin)],
    responses={**schemas.ERRORS_404, **schemas.ERRORS_422},
)
def admin_database_shape(request: Request):
    """Does this server hold a live-shaped database? A tool that writes test
    documents and review runs (the PF1 runner) asks this before it writes,
    because a port says nothing about which database a server holds. Admin
    only (a non-admin gets the same 404 as every route here): the unauthenticated
    `/api/health` is deliberately not widened (#806). A boolean about the path's
    shape, never the path."""
    reject_unknown_params(request, set())
    return {"live_shaped": _database_is_live_shaped()}


@router.get("/api/admin/users", response_model=schemas.AdminUserList,
            responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def admin_list_users(
    request: Request,
    limit: int | None = limit_param(),
    offset: int = offset_param(),
    actor: dict | None = Depends(admin_mod.current_admin),
):
    """Every user, with disciplines and the "no discipline" warning.

    Carries NO setup token, for any user, ever - only its SHA-256 is stored,
    so there is no plaintext here to return.
    """
    reject_unknown_params(request, {"limit", "offset"})
    return page_body("users", admin_mod.list_users()["users"], limit, offset)


@router.post("/api/admin/users", response_model=schemas.AdminUserCreated,
             status_code=201,
             responses={**schemas.ERRORS_404, **schemas.ERRORS_409,
                        **schemas.ERRORS_422})
def admin_create_user(body: admin_mod.CreateUserRequest,
                      actor: dict | None = Depends(admin_mod.current_admin)):
    """Create a user and return a one-time setup token.

    NO PASSWORD IS ACCEPTED OR RETURNED, and there is no parameter for one.
    The reasons are argued in the contract: `seed_access.py` guarantees that a
    password can only ever arrive by being typed interactively twice, an admin
    who types someone's password knows it, and a password in a request body is
    a password in a log - which this project found in a 422 handler that
    echoed the submitted body back.
    """
    return admin_mod.create_user(body, actor)


@router.delete("/api/admin/users/{user_id}",
               response_model=schemas.AdminUserDeactivated,
               responses={**schemas.ERRORS_404, **schemas.ERRORS_409})
def admin_deactivate_user(user_id: str,
                          actor: dict | None = Depends(admin_mod.current_admin)):
    """Deactivate a user. Idempotent, and never a delete.

    An admin cannot deactivate themselves: without that rule the last admin
    can lock everyone out of a system whose only other door is a terminal.
    """
    return admin_mod.deactivate_user(user_id, actor)


@router.post("/api/admin/users/{user_id}/password-reset",
             response_model=schemas.AdminUserCreated,
             responses={**schemas.ERRORS_404})
def admin_issue_password_reset(
        user_id: str,
        actor: dict | None = Depends(admin_mod.current_admin)):
    """Issue a replacement shown-once token; never accept a password here."""
    return admin_mod.issue_password_reset(user_id, actor)


@router.get("/api/admin/disciplines", response_model=schemas.AdminDisciplineList,
            responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def admin_list_disciplines(
    request: Request,
    limit: int | None = limit_param(),
    offset: int = offset_param(),
    actor: dict | None = Depends(admin_mod.current_admin),
):
    """Disciplines with user and document counts.

    A discipline with no documents is flagged, because everyone in it logs in
    successfully and then sees an empty corpus - which during a demo looks
    exactly like broken search rather than a missing grant.
    """
    reject_unknown_params(request, {"limit", "offset"})
    disciplines = admin_mod.list_disciplines()["disciplines"]
    return page_body("disciplines", disciplines, limit, offset)


@router.get("/api/admin/grants", response_model=schemas.AdminGrantList,
            responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def admin_list_grants(
    request: Request,
    limit: int | None = limit_param(),
    offset: int = offset_param(),
    actor: dict | None = Depends(admin_mod.current_admin),
):
    """Documents and the disciplines that can see them.

    A document nobody can see is flagged: it is invisible in every search and
    looks like a broken upload.
    """
    reject_unknown_params(request, {"limit", "offset"})
    return page_body("documents", admin_mod.list_grants()["documents"], limit, offset)


@router.put("/api/admin/grants", response_model=schemas.AdminGrantResult,
            responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def admin_grant(body: admin_mod.GrantRequest,
                actor: dict | None = Depends(admin_mod.current_admin)):
    """Grant a document to a discipline. Idempotent - a retried click cannot
    double-grant and cannot fail."""
    return admin_mod.grant(body, actor)


@router.delete("/api/admin/grants", response_model=schemas.AdminGrantResult,
               responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def admin_revoke_grant(body: admin_mod.GrantRequest,
                       actor: dict | None = Depends(admin_mod.current_admin)):
    """Revoke a document from a discipline. 200 whether or not it was granted.

    The document leaves that discipline's members' search results on their NEXT
    REQUEST: `access.scope_for_user` re-runs the grant-table join every request
    and caches nothing, so deleting the row IS the invalidation. See
    `admin.revoke_grant`, where that is stated at the line it happens.
    """
    return admin_mod.revoke_grant(body, actor)


@router.get(
    "/api/admin/company-standards/held",
    response_model=schemas.HeldCompanyStandardList,
    responses={**schemas.ERRORS_404, **schemas.ERRORS_422},
)
def admin_held_company_standards(
    request: Request,
    limit: int | None = limit_param(),
    offset: int = offset_param(),
    _actor: dict | None = Depends(admin_mod.current_admin),
):
    """#620 (owner's option a): the Company standards a non-administrator
    uploaded on or after the cut-off that wait for an administrator's
    confirmation before reviews use them. `confirm_from` states the boundary:
    standards uploaded before it count as confirmed and are not listed."""
    from .. import company_standard_confirm as csc
    from ..config import settings

    reject_unknown_params(request, {"limit", "offset"})
    return {
        **page_body("standards", csc.list_held(), limit, offset),
        "confirm_from": str(settings.company_standard_confirm_from or "") or None,
    }


@router.post(
    "/api/admin/company-standards/{document_id}/confirm",
    response_model=schemas.CompanyStandardConfirmed,
    responses={**schemas.ERRORS_404, **schemas.ERRORS_422},
)
def admin_confirm_company_standard(
    document_id: str,
    actor: dict | None = Depends(admin_mod.current_admin),
):
    """#620: an administrator confirms one held Company standard, so reviews
    use it from the next run. Idempotent (`confirmed: false` when it already
    was) and audited once. An unknown id is a 404, and so is a caller with no
    identity (a confirmation always names an administrator); a document that
    is not a Company standard is a 422."""
    from .. import company_standard_confirm as csc
    from .. import standards as standards_mod

    if (
        actor is None
        or connect()
        .execute("SELECT 1 FROM documents WHERE id = ?", (document_id,))
        .fetchone()
        is None
    ):
        raise HTTPException(
            status_code=404,
            detail=errors.safe_error(errors.NOT_FOUND, "no document with that id"),
        )
    if (
        connect()
        .execute(
            "SELECT 1 FROM document_classification WHERE document_id = ? AND document_role = ?",
            (document_id, standards_mod.COMPANY_STANDARD),
        )
        .fetchone()
        is None
    ):
        raise HTTPException(
            status_code=422,
            detail=errors.safe_error(
                errors.INVALID_PARAMETER, "that document is not a Company standard"
            ),
        )
    try:
        confirmed = csc.confirm(
            document_id,
            actor_user_id=actor["id"],
            actor_username=actor.get("email") or actor["id"],
        )
    except csc.NotAnAdministrator:
        raise HTTPException(
            status_code=404, detail=errors.safe_error(errors.NOT_FOUND, "not found")
        ) from None
    return {"document_id": document_id, "confirmed": confirmed}


# ------------------------------------------ the read-only database explorer
#
# THE SAME GATE AS EVERY OTHER ADMIN ROUTE, and that is the point: this is the
# single most interesting surface on the API to probe, because it names every
# table in the system. `admin.current_admin` answers a non-admin with 404, so
# a caller who is not an admin cannot even learn that these routes exist.
#
# A WINDOW, NOT A WORKBENCH. Three GETs and nothing else - no POST, no PATCH,
# no DELETE, and no request model anywhere that accepts a value to store. An
# explorer that could write would be a second, unaudited path into every table
# the real endpoints guard with scope checks and honesty invariants.
#
# THE EXPLORER READS EVERY TABLE, NOT ONLY WHAT THE ADMIN'S GRANTS COVER. That is
# a decision, not an oversight (owner, 2026-10-07: "admin can read everything").
# It is why the gate above matters, why credential columns are masked, and why
# the document routes' grant-based scope is NOT a statement about this screen.
# If an administrator must one day be limited to granted documents here too,
# `admin_explorer.read_rows` is where that filter goes.
#
# CREDENTIAL MATERIAL IS MASKED IN `admin_explorer`, before it reaches the
# wire. Not in the UI: a browser's network tab renders a JSON response just
# fine, so masking on the client would be decoration over a disclosure.


@router.get("/api/admin/db/tables", response_model=schemas.AdminDbTableList,
            responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def admin_db_tables(
    request: Request,
    limit: int | None = limit_param(),
    offset: int = offset_param(),
    actor: dict | None = Depends(admin_mod.current_admin),
):
    """Every user table with its row count. SQLite internals excluded."""
    reject_unknown_params(request, {"limit", "offset"})
    return page_body("tables", explorer_mod.list_tables(connect()), limit, offset)


@router.get("/api/admin/db/tables/{name}", response_model=schemas.AdminDbTableInfo,
            responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def admin_db_table(name: str, request: Request,
                   actor: dict | None = Depends(admin_mod.current_admin)):
    """One table's columns, with type, nullability and whether its values are
    masked.

    An unknown table is 404 - the same answer a non-admin gets for the whole
    route - so probing for a table name tells a caller nothing they did not
    already have.
    """
    reject_unknown_params(request, set())
    info = explorer_mod.table_info(connect(), name)
    if info is None:
        raise HTTPException(status_code=404, detail=errors.safe_error(
            errors.NOT_FOUND, "no such table"))
    return info


@router.get("/api/admin/db/tables/{name}/rows", response_model=schemas.AdminDbRows,
            responses={**schemas.ERRORS_404, **schemas.ERRORS_422})
def admin_db_rows(
    name: str,
    request: Request,
    limit: int = Query(50, ge=1, description="rows to return; capped server-side"),
    offset: int = Query(0, ge=0, description="rows to skip"),
    actor: dict | None = Depends(admin_mod.current_admin),
):
    """A page of rows, with the whole table's count beside it.

    The cap lives in `admin_explorer.MAX_ROWS` and is applied there whatever
    this route is asked for, so a caller cannot page the entire corpus into
    one response by asking loudly.
    """
    reject_unknown_params(request, {"limit", "offset"})
    page = explorer_mod.read_rows(connect(), name, limit=limit, offset=offset)
    if page is None:
        raise HTTPException(status_code=404, detail=errors.safe_error(
            errors.NOT_FOUND, "no such table"))
    return page
