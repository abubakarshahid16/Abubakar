"""The API description grouped by area, with every file response typed.

Planner order 69 (#692): all 168 operations sat in one "default" group, and
the 11 that answer with a file or a stream had no response schema. This adds
documentation only - no route, parameter, status code or body changes:

  * each `/api` operation gets ONE tag, by the first area whose path prefix
    it starts with (`AREAS`, most specific first). An operation that matches
    no area makes the description fail to build (and `test_api_tags` fail),
    so a new route cannot quietly fall back into "default". The tags are set
    on the generated description, not on the route objects: routes from
    `include_router` are wrapped differently across FastAPI versions;
  * a 2xx response declared with a non-JSON media type (PNG, PDF, xlsx, the
    original upload, the chat event stream) gets a schema: binary for files,
    text for the event stream.

The area list is the target `api/` split of the system map (order 71c):
documents, review, crs, chat, analysis, auth, admin, watch - plus standards
and management, which are areas of their own today.
"""
from __future__ import annotations

from fastapi import FastAPI

#: (tag, what the area is, path prefixes). First match wins, so a prefix that
#: sits inside another area's prefix comes first (CRS before review).
AREAS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("crs", "Comment Review Sheet: build, export, the issue gate and issued copies",
     ("/api/reviews/runs/{review_run_id}/crs",)),
    ("review", "Submittal review: runs, findings, decisions, the Sheet, evidence, playbooks",
     ("/api/reviews", "/api/playbooks")),
    ("standards", "Standards library: upload, requirements, clause checks, readiness",
     ("/api/standards",)),
    ("documents", "Documents: upload, pages, classification, document kinds",
     ("/api/documents", "/api/document-kinds", "/api/classification")),
    ("chat", "Chat: conversations, answers, search, models",
     ("/api/conversations", "/api/chat", "/api/answer", "/api/search")),
    ("analysis", "Analysis Hub: summaries, gaps, recommendations, reports, market search",
     ("/api/analysis", "/api/reports", "/api/market")),
    ("management", "Project register: deliverables, risks, reminders, summaries",
     ("/api/deliverables", "/api/risks", "/api/management")),
    ("auth", "Sign-in, tokens and the current user", ("/api/auth",)),
    ("admin", "Administration and system: users, health, metrics, jobs, progress",
     ("/api/admin", "/api/health", "/api/metrics", "/api/jobs", "/api/progress")),
    ("watch", "Watched folder", ("/api/watch",)),
)

_JSON = "application/json"
#: The event stream is text; every other non-JSON answer is a file.
_TEXT_TYPES = frozenset({"text/event-stream"})


def area_for(path: str) -> str | None:
    for tag, _about, prefixes in AREAS:
        if any(path == p or path.startswith(p.rstrip("/") + "/") for p in prefixes):
            return tag
    return None


def _describe(spec: dict) -> dict:
    untagged = []
    for path, item in spec.get("paths", {}).items():
        for operation in item.values():
            if path.startswith("/api") and not operation.get("tags"):
                tag = area_for(path)
                if tag is None:
                    untagged.append(path)
                else:
                    operation["tags"] = [tag]
            for code, response in (operation.get("responses") or {}).items():
                if not code.startswith("2"):
                    continue
                for media, body in (response.get("content") or {}).items():
                    if media != _JSON and not (body or {}).get("schema"):
                        body["schema"] = ({"type": "string"} if media in _TEXT_TYPES
                                          else {"type": "string", "format": "binary"})
    if untagged:
        raise RuntimeError(f"api_tags: no area for {sorted(set(untagged))}; add it to AREAS")
    spec["tags"] = [{"name": tag, "description": about} for tag, about, _p in AREAS]
    return spec


def describe(app: FastAPI) -> None:
    """Group `app`'s API description by area and type its file responses."""
    build = app.openapi

    def openapi() -> dict:
        if app.openapi_schema is None:
            app.openapi_schema = _describe(build())
        return app.openapi_schema

    app.openapi = openapi
