"""GET /api/watch/status - what the watched drop folder is doing.

An `APIRouter` rather than routes on `app`: this is one self-contained feature
with one endpoint, and main.py includes the router. Nothing else lives here.

THE FOLDER PATH NEVER LEAVES THIS PROCESS, AND THAT TAKES TWO PROTECTIONS.

The first is the admin gate, `scope.unrestricted or scope.is_admin` - the same
predicate /api/metrics uses for host facts, and it is here for the same
reason: `settings.watch_folder` says where the client's documents live, what
the drive layout is, and often what the share is called. No document grant can
entitle a caller to that; administration is the only thing that can.

THE GATE ALONE WAS NOT ENOUGH, and the codebase-wide leak sweep proved it
rather than anybody reasoning it out. Under `AUTH_MODE=disabled` every caller
is `unrestricted`, so "administrators only" means "everybody" in the mode the
whole suite runs in, and the full host path went out on a 200.
`test_every_get_route_is_scanned_for_leaks_on_hostile_input` asserts a FLAT
invariant - no host filesystem path in any GET body, any caller, any mode -
and it caught this the way it caught /api/health's traceback.

So the second protection is the value itself: `folder_name` is the last path
segment and nothing above it. An administrator can still tell which folder is
configured; the host's directory structure is not published to anyone. The two
are for different threats - the gate decides WHO is answered, the segment
decides WHAT the answer can contain - and neither substitutes for the other.

Everything else in the payload is: whether the feature is on, how often it
looks, when it last looked, and what it decided. An engineer wondering why the
specification they dropped this morning has not appeared needs all of that and
none of the path.

THAT SENTENCE USED TO BE FALSE, and the way it was false is worth keeping.
"What it decided" is a list of `filename`s - real client documents - and it
went to every caller unscoped while this docstring counted it among the
harmless fields and reasoned only about the path. `recent_events` is now given
the caller's scope and filters on `document_id`; a drop that never became a
document names a file nobody has a grant on, so it sits behind the same
capability gate as the folder name.

BEING OFF IS NOT AN ERROR. No watch folder configured is the DEFAULT state of
this system. The endpoint answers 200 with `enabled: false` and nulls, because
a 404 or a 503 would make a deliberately unconfigured feature look broken and
send an operator hunting for a fault that does not exist.
"""

from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from . import access
from . import schemas
from . import watcher as watcher_mod
from .api_utils import reject_unknown_params
from .config import settings
from .db import connect

router = APIRouter()

#: Both separator styles, always. The backend may see `D:\\share\\inbox`, a
#: POSIX mount, or a UNC path `\\\\fileserver\\engineering\\inbox`, and the
#: client's real deployment is a Windows share reached by whichever spelling
#: the operator typed into `.env`. Splitting on one of them would return the
#: WHOLE remaining path as "the last segment" for the other - the leak, not a
#: cosmetic difference.
_SEPARATORS = re.compile(r"[\\/]")

#: `D:` - a drive designator is not a folder name.
_DRIVE = re.compile(r"^[A-Za-z]:$")

#: A UNC path: two separators, then a machine name.
_UNC = re.compile(r"^[\\\\/]{2}")


def folder_name(configured: str) -> str | None:
    r"""The LAST SEGMENT of the configured path, or None.

    THE PATH ITSELF NEVER LEAVES THIS PROCESS. `test_no_internal_leaks.py::
    test_every_get_route_is_scanned_for_leaks_on_hostile_input` asserts a flat
    invariant over every GET route in the application: no host filesystem path
    appears in any response body, for any caller, in any mode. This route
    failed it, and the admin gate was not the reason - under
    `AUTH_MODE=disabled` every caller is `unrestricted`, so "administrators
    only" is "everybody" in the mode the suite runs in. Two protections for
    two different threats: the gate decides WHO is answered, and this decides
    WHAT the answer can contain. Neither substitutes for the other.

    `D:/project/Rag_chatbot/backend/data/watch-inbox` becomes `watch-inbox`.
    An administrator can still tell which folder is configured, and the
    directory structure of the host - the drive, the deployment root, the
    account name a home directory carries - stops being published.

    None, never "", when there is genuinely no folder to name: a drive root,
    a bare separator, an empty value, a UNC path carrying only a host. An
    empty string on a screen reads as a folder whose name is blank rather
    than as a value that could not be derived, and this codebase does not
    spell null that way.

    A TRAILING SEPARATOR IS NOT "no folder". `D:\data\inbox\` is `inbox`,
    because pasting a share path with one extra character on the end is the
    likeliest operator typo there is, and answering null to it would tell an
    administrator that NO folder is configured about a folder that is
    configured and working. Null has to mean the value names nothing, not
    that somebody typed a separator too many - a field that cannot tell those
    two apart misdirects the person reading it.
    """
    trimmed = (configured or "").strip()
    if not trimmed:
        return None
    # Empties dropped BEFORE the last is taken, so a trailing separator falls
    # away instead of becoming the answer. Interior empties go the same way,
    # which is what makes a doubled separator harmless too.
    parts = [part.strip() for part in _SEPARATORS.split(trimmed)]
    parts = [part for part in parts if part]
    if not parts:
        return None
    # A UNC path is `\\host\share\...`, so its FIRST segment is a machine
    # name. With nothing after it there is no folder here to name, and
    # returning what is left would publish the host - a sharper version of
    # the leak this function exists to close. Only reachable now that empties
    # are filtered: `\\fileserver` used to fall out as "no last segment".
    if _UNC.match(trimmed) and len(parts) < 2:
        return None
    last = parts[-1]
    if _DRIVE.match(last):
        return None
    return last

# --------------------------------------------------------------- the shape
#
# DECLARED, not left to inference. Every 200 in this API was once documented
# as `string`, which made the generated frontend types guesses -
# `test_every_endpoint_declares_a_typed_success_response` is the guard that
# exists because of it, and a route returning a bare dict trips it. These
# models live HERE rather than in schemas.py because the whole feature is one
# router and its contract belongs beside it.
#
# NULLABLE MEANS NULLABLE, AND REQUIRED. Every field that can be null is typed
# `X | None` with NO default, so the schema says "always present, sometimes
# null" rather than "sometimes absent". The distinction is not pedantry here:
# the panel branches on null for every one of these - a folder it may not see,
# a scan that has not happened, a watcher that is reachable-unknown - and a
# generated type marking them optional would let the UI treat "absent" and
# "null" as the same thing when only one of them can ever occur.

#: The three outcomes, matching `watch_events.outcome`'s CHECK constraint and
#: the union the frontend already declares. A bare `str` here would generate a
#: type that permits a fourth value the database cannot store.
WatchOutcome = Literal["ingested", "duplicate", "failed"]


class WatchEvent(BaseModel):
    """One decision the watcher made about one file.

    `source_path` is deliberately absent. It is the host path the `folder`
    field is withheld for, and carrying it per row would move the disclosure
    rather than close it.
    """

    filename: str = Field(description="as it was named in the folder")
    outcome: WatchOutcome
    at: str = Field(
        description="ISO-8601 UTC, when the watcher decided",
        examples=["2026-09-07T09:15:00Z"],
    )
    detail: str | None = Field(
        description="why, in words; null when there was nothing to add")


class WatchStatus(BaseModel):
    """What the watched folder is and what it last did."""

    enabled: bool = Field(
        description="a folder is CONFIGURED - not that it is working")
    folder_name: str | None = Field(
        description="the watched folder's own name - its last path segment, "
                    "never the directories above it. Administrators only; "
                    "null for everyone else, null when the feature is off, "
                    "and null when the configured value has no final segment")
    reachable: bool | None = Field(
        description="did the most recent scan find the folder readable; null "
                    "before any scan has run, and never false unobserved")
    last_error: str | None = Field(
        description="the most recent SCAN-LEVEL failure, in words that name no "
                    "path; null when the last scan was fine. A single bad PDF "
                    "is a 'failed' event in `recent`, not this")
    last_scan_at: str | None = Field(
        description="ISO-8601 UTC of the last completed scan; null if none has",
        examples=["2026-09-07T09:15:00Z"],
    )
    interval_seconds: int | None = Field(
        description="how often the folder is polled; null when the feature is off")
    recent: list[WatchEvent] = Field(
        description="the newest decisions, newest first; empty when there are none")

#: How many events the screen shows. A window, not a log: the whole history is
#: in `watch_events` and is queried there. Ten is what fits beside the folder
#: status without becoming a second page.
RECENT_LIMIT = 10


def recent_events(scope: access.AccessScope, may_see_host_paths: bool,
                  limit: int = RECENT_LIMIT) -> list[dict]:
    """The newest events the caller may see, newest first.

    SCOPED, AND THE SCOPE IS REQUIRED. This function used to take no scope and
    its query had no predicate, so the last ten watched-folder decisions went
    back byte-identically to every caller - including one with zero grants, in
    the same second that `GET /api/documents` correctly returned `[]` for them.
    A `filename` here names a real client document, and `duplicate`
    additionally asserts that a document with that content is already in the
    corpus. That is the disclosure `/api/health` was stripped for.

    The docstring below used to reason only about `source_path` and conclude
    that returning it "would move the leak rather than close it". It was
    inspecting the path while the filename beside it was the leak.

    A row whose `document_id` is NULL is a drop that never became a document -
    a `failed` PDF - so no grant can ever cover it, and it is still the name of
    a file in the client's inbox. Those rows sit behind `may_see_host_paths`,
    the same gate as the folder name itself.

    Ordered by `id DESC` rather than by `observed_at DESC`, deliberately.
    Timestamps are truncated to the second, so several files handled inside
    one scan share one - and ordering by a value with ties puts them in
    whatever order SQLite likes, which for a list whose entire purpose is
    "what happened most recently" is the one property it must not have. `id`
    is the insertion order, which is the real answer. The index on
    `observed_at` is what serves range queries over the history; this is a
    small ordered head off the primary key.

    `source_path` is NOT returned. It is the same host path the folder field
    withholds, and returning it per row would move the leak rather than close
    it - which is precisely how /api/health's disclosures ended up on
    /api/metrics.
    """
    conn = connect()
    if scope.unrestricted:
        # No predicate at all - the same rows as before, for the mode in which
        # every caller may read every document anyway.
        where, params = "", []
    elif may_see_host_paths:
        # An admin under a real auth mode: granted documents, plus the
        # never-ingested drops, which belong to no document and so can only be
        # gated on this flag.
        where = " WHERE document_id IS NULL OR document_id IN (%s)" % (
            ",".join("?" * len(scope.allowed_document_ids)) or "NULL")
        params = list(scope.allowed_document_ids)
    elif not scope.allowed_document_ids:
        # Zero grants. `WHERE 1 = 0` rather than skipping the query, so this
        # returns [] by the same path as every other answer and cannot be a
        # code branch that forgot to filter.
        where, params = " WHERE 1 = 0", []
    else:
        where = " WHERE document_id IN (%s)" % ",".join(
            "?" * len(scope.allowed_document_ids))
        params = list(scope.allowed_document_ids)

    return [
        {
            "filename": r["filename"],
            "outcome": r["outcome"],
            "at": r["observed_at"],
            # Nullable and left null. A row with nothing to add carries None,
            # never "" - an empty string reads on a screen as an explanation
            # that was given and was blank.
            "detail": r["detail"],
        }
        for r in conn.execute(
            "SELECT filename, outcome, observed_at, detail FROM watch_events"
            + where + " ORDER BY id DESC LIMIT ?",
            (*params, limit),
        )
    ]


@router.get("/api/watch/status", response_model=WatchStatus,
            responses=schemas.ERRORS_422)
def watch_status(request: Request,
                 scope: access.AccessScope = Depends(access.current_scope)):
    """Whether the folder is being watched, and what it has decided lately.

    `access.current_scope` is the dependency every scoped route in main.py
    uses, and it is the one used here - identity comes from the request, the
    entitlement is derived server-side. `current_admin` was the alternative
    and is wrong for this route: that dependency REFUSES a non-administrator,
    and an engineer is entitled to the answer, just not to the path.
    """
    reject_unknown_params(request, set())

    folder = (settings.watch_folder or "").strip()
    if not folder:
        # Off. Every field that would describe a running watcher is null, and
        # `recent` is empty rather than absent: the shape of the payload does
        # not change with the state, so a client never has to branch on which
        # keys exist.
        return {
            "enabled": False,
            "folder_name": None,
            "reachable": None,
            "last_error": None,
            "last_scan_at": None,
            "interval_seconds": None,
            "recent": [],
        }

    # THE predicate, and the same one /api/metrics uses for host facts. It
    # reads the capability KIND resolved onto the scope, not a role name.
    may_see_host_paths = scope.unrestricted or scope.is_admin

    return {
        "enabled": True,
        # Null for everyone else, and null MEANS "not shown to you" rather
        # than "not configured" - which the caller can tell apart, because
        # `enabled` is true beside it. The gate and `folder_name` are separate
        # protections: the gate decides who is answered, `folder_name` decides
        # what the answer can contain, and under AUTH_MODE=disabled - where
        # every caller is `unrestricted` - only the second one is doing
        # anything at all.
        "folder_name": folder_name(folder) if may_see_host_paths else None,
        # None until a scan has actually completed. Never a zero timestamp and
        # never "now": a watcher that has just started has not looked yet, and
        # saying otherwise would be the screen's own invention.
        # ENABLED SAYS CONFIGURED. REACHABLE SAYS WORKING. At the client's
        # site this folder is a network share, and a share can be unmounted,
        # have its permissions revoked, or sit behind a VPN that dropped
        # overnight. With `enabled` alone the panel renders perfectly healthy
        # while `last_scan_at` quietly ages, and the first person to notice is
        # whoever asks why last week's specification is not searchable.
        #
        # None until a scan has actually run. Never False before then: False
        # is an observation - somebody looked and could not read it - and this
        # codebase does not report unobserved values, in either direction.
        "reachable": watcher_mod.last_reachable(),
        # The scan-level failure, in words, or null when the last scan was
        # fine. SHOWN TO EVERYONE, which is the constraint that shapes it: it
        # says the folder could not be read and never where the folder is.
        # `watcher.FOLDER_UNREADABLE` carries the reasoning, including why the
        # operating system's own message - which embeds the path on a
        # permission error - is never passed through.
        #
        # A single corrupt PDF does NOT appear here. That is a per-file
        # 'failed' event in `recent`; raising a folder-level alarm for one bad
        # drop would teach an operator to ignore the alarm.
        "last_error": watcher_mod.last_error(),
        "last_scan_at": watcher_mod.last_scan_at(),
        "interval_seconds": settings.watch_interval_seconds,
        "recent": recent_events(scope, may_see_host_paths),
    }
