"""#1178 review: re-confirming on a later run must never overwrite the words
an engineer confirmed under a number with the waiting sentence of a new,
unconfirmed AI/web draft about the same subject. Invented data only."""

from __future__ import annotations

from app import access, crs_mapping, crs_numbers
from app import main as main_mod
from tests.test_b3_page_ledger import temp_storage  # noqa: F401 - autouse
from tests.test_review_screen import world  # noqa: F401

KEY = "invented-ai-item-key"
WORDS = "Confirm the invented coupling guard is fitted. (Engineer's words.)"


def test_the_re_confirm_path_keeps_the_engineers_stored_wording(world, monkeypatch):  # noqa: F811
    sub, run, scope = world
    crs_scope, label = main_mod._crs_scope_of(sub)
    # run 1: the engineer confirmed the AI item - number issued, their words stored
    crs_numbers.assign(
        crs_scope,
        label,
        [KEY],
        document_id=sub,
        review_run_id=run,
        snapshots={KEY: {"comment": WORDS, "comment_by": "AI, confirmed"}},
        user_id="eng-1",
    )
    # run 2: the same item raised again as an UNCONFIRMED draft; the issued
    # number marks its row confirmed, and another confirmation re-snapshots
    draft = {
        "crs_row_key": KEY,
        "engineer_confirmed": True,
        "row_kind": crs_mapping.ROW_KIND_AI_ENGINEERING_CHECK,
        "comment": crs_mapping.AI_UNCONFIRMED_COMMENT,
        "ai_review_comment": "Confirm the invented coupling guard is fitted.",
    }
    other = {
        "crs_row_key": "invented-other-key",
        "engineer_confirmed": True,
        "row_kind": "missing_information",
        "comment": "Contractor to provide X.",
    }
    monkeypatch.setattr(
        main_mod,
        "_crs_content",
        lambda *_a, **_k: ([draft, other], {}, "s.pdf", "2026-10-19"),
    )
    main_mod._mint_crs_numbers(
        run, access.AccessScope(user_id="eng-1", allowed_document_ids=frozenset(scope))
    )
    stored = crs_numbers.lookup(crs_scope, [KEY, "invented-other-key"])
    assert stored[KEY]["comment"] == WORDS
    assert stored["invented-other-key"]["comment"] == "Contractor to provide X."
