"""Order 69 (#692): the API description is grouped by area and every file
response is typed. Documentation only - the routes themselves are unchanged."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.responses import Response

from app import api_tags
from app.main import app


def _operations(spec: dict):
    for path, item in spec["paths"].items():
        for method, operation in item.items():
            yield method.upper(), path, operation


def test_every_operation_has_exactly_one_known_area():
    known = {tag for tag, _about, _prefixes in api_tags.AREAS}
    ops = list(_operations(app.openapi()))
    assert len(ops) >= 160
    wrong = [(m, p, o.get("tags")) for m, p, o in ops
             if len(o.get("tags") or []) != 1 or o["tags"][0] not in known]
    assert wrong == []
    assert {t["name"] for t in app.openapi()["tags"]} == known


@pytest.mark.parametrize(("path", "area"), [
    ("/api/reviews/runs/{review_run_id}/crs", "crs"),
    ("/api/reviews/runs/{review_run_id}/crs/issue-gate", "crs"),
    ("/api/reviews/runs/{review_run_id}", "review"),
    ("/api/reviews/findings/{finding_id}/evidence-image", "review"),
    ("/api/standards", "standards"),
    ("/api/documents/{document_id}/pages/{page_no}/image", "documents"),
    ("/api/conversations/{conversation_id}/ask/stream", "chat"),
    ("/api/reports/{report_id}/download", "analysis"),
    ("/api/management/report", "management"),
    ("/api/health", "admin"),
    ("/api/watch/status", "watch"),
    ("/api/healthz", None),          # a prefix is a path segment, not a string start
    ("/api/unknown-area", None),
])
def test_area_by_path_segment(path, area):
    assert api_tags.area_for(path) == area


def test_every_file_response_is_typed():
    untyped = []
    for method, path, operation in _operations(app.openapi()):
        for code, response in operation.get("responses", {}).items():
            if code.startswith("2"):
                untyped += [(method, path, media) for media, body in
                            (response.get("content") or {}).items() if not body.get("schema")]
    assert untyped == []
    spec = app.openapi()["paths"]
    png = spec["/api/documents/{document_id}/pages/{page_no}/image"]["get"]["responses"]["200"]
    assert png["content"]["image/png"]["schema"] == {"type": "string", "format": "binary"}
    stream = spec["/api/conversations/{conversation_id}/ask/stream"]["post"]["responses"]["200"]
    assert stream["content"]["text/event-stream"]["schema"] == {"type": "string"}


def test_a_route_with_no_area_fails_the_description():
    other = FastAPI()

    @other.get("/api/nowhere")
    def nowhere():
        return {}

    api_tags.describe(other)
    with pytest.raises(RuntimeError, match=r"no area for .*/api/nowhere"):
        other.openapi()


def test_a_route_from_an_included_router_is_tagged_too():
    """`include_router` wraps routes differently across FastAPI versions; the
    tag is set on the description, so both kinds are covered."""
    from fastapi import APIRouter

    other, router = FastAPI(), APIRouter()

    @router.get("/api/watch/status")
    def status():
        return {}

    other.include_router(router)
    api_tags.describe(other)
    assert other.openapi()["paths"]["/api/watch/status"]["get"]["tags"] == ["watch"]


def test_tags_and_types_change_no_route_behaviour():
    """Only the description changes: same routes, same methods, same codes."""
    other = FastAPI()

    @other.get("/api/health")
    def health():
        return {"ok": True}

    @other.get("/api/documents/{document_id}/original", response_class=Response,
               responses={200: {"content": {"application/pdf": {}}}})
    def original(document_id: str):
        return Response(b"%PDF", media_type="application/pdf")

    before = {(m, p): set(o["responses"]) for m, p, o in _operations(other.openapi())}
    other.openapi_schema = None
    api_tags.describe(other)
    after = {(m, p): set(o["responses"]) for m, p, o in _operations(other.openapi())}
    assert before == after
    assert [r.path for r in other.routes][-2:] == ["/api/health", "/api/documents/{document_id}/original"]
