"""A document's file name, typed the way a person types it, never leaves.

Honesty audit entry 67: `market_phrase` removed a corpus file name exactly,
as its stem, and with every separator deleted - but not as a reader writes
it: `coating-inspection-plan.pdf` typed "coating inspection plan" passed the
whitelist word by word. A file name is corpus metadata; sent to a search
engine it tells an outside service which documents this organisation holds.

Every variant below is typed through the phrase builder, through the market
screen's preview route, and through chat web search's consent turn - the two
lanes share the builder, and each is checked, not assumed. The public
standard designator in the same question must survive, so the fix cannot be
"send nothing at all".

Synthetic file names only.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import chat_web, db
from app.config import settings
from app.main import app
from app.market_phrase import market_phrase
from tests.test_chat import temp_storage, upload  # noqa: F401 - the fixture is autouse

FILENAME = "coating-inspection-plan.pdf"
PARTS = ("coating", "inspection", "plan")

VARIANTS = [
    "coating inspection plan",           # spaces, no extension
    "coating-inspection-plan",           # hyphens, no extension
    "coating_inspection_plan",           # underscores
    "coating.inspection.plan",           # dots
    "Coating_Inspection.Plan",           # a mix, mixed case
    "COATING INSPECTION PLAN.PDF",       # upper case, with the extension
    "coating inspection plan pdf",       # the extension typed as a word
    "coatinginspectionplan",             # no separators at all
    "coating - inspection _ plan",       # separators with spaces round them
]


def _question(variant: str) -> str:
    return f"is there a newer edition of ISO 12944 online, and of {variant}"


def _leaked(phrase: str | None) -> list[str]:
    low = (phrase or "").lower()
    return [p for p in PARTS if p in low]


@pytest.mark.parametrize("variant", VARIANTS)
def test_the_phrase_builder_removes_every_typed_form_of_the_name(variant):
    phrase = market_phrase(_question(variant), [FILENAME])
    assert not _leaked(phrase), f"{variant!r} left {_leaked(phrase)} in {phrase!r}"
    assert phrase and "12944" in phrase, "the public designator must survive"


def test_the_same_words_are_kept_when_they_name_no_document():
    """Only a document's own name is removed - the fix does not ban words."""
    phrase = market_phrase(_question("coating inspection plan"), ["other-file.pdf"])
    assert _leaked(phrase) == list(PARTS)


@pytest.fixture
def named_document():
    client = TestClient(app)
    doc = upload(client)
    conn = db.connect()
    with conn:
        conn.execute("UPDATE documents SET filename = ? WHERE id = ?", (FILENAME, doc))
    return client, doc


@pytest.mark.parametrize("variant", VARIANTS)
def test_the_market_screen_never_offers_to_send_the_name(named_document, variant):
    client, _ = named_document
    body = client.get("/api/market/preview", params={"phrase": _question(variant)}).json()
    assert not _leaked(body["phrase"]), f"{variant!r} reached the market preview: {body['phrase']!r}"
    for p in body["payloads"]:
        assert not _leaked(p["payload"]["phrase"])


@pytest.mark.parametrize("variant", VARIANTS)
def test_chat_web_search_never_offers_to_send_the_name(named_document, variant, monkeypatch):
    client, doc = named_document
    monkeypatch.setattr(settings, "chat_web_enabled", True)
    monkeypatch.setattr(settings, "market_live_enabled", True)
    monkeypatch.setattr(settings, "market_allow_public_egress", True)
    consent = chat_web.consent(_question(variant), allowed_document_ids=frozenset({doc}))
    assert not _leaked(consent["web_phrase"]), f"{variant!r} reached the web consent: {consent['web_phrase']!r}"
    assert not _leaked(consent["answer"])


def test_a_file_named_only_after_a_public_standard_keeps_the_standard_searchable():
    """The one exception (see market_phrase._flexible_name): the name of a
    published standard is public."""
    phrase = market_phrase("is there a newer edition of NORSOK M 501 online", ["NORSOK-M-501.pdf"])
    assert phrase and "norsok" in phrase.lower()


@pytest.mark.parametrize("variant", ["norsok m 501 internal notes", "NORSOK_M_501.Internal-Notes"])
def test_the_exception_stops_at_the_standard_a_file_that_adds_words_is_removed(variant):
    phrase = market_phrase(f"what about {variant}", ["NORSOK-M-501-internal-notes.pdf"])
    low = (phrase or "").lower()
    assert "internal" not in low and "notes" not in low, phrase
