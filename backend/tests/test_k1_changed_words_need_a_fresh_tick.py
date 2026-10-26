"""K1 (code audit 26 Oct): a numbered CRS row whose words changed needs a fresh tick.

A permanent number's key is the comment's SUBJECT (the field, the clause), not
its words. A later run lands on the same number with a new value or reason; the
older behaviour carried the engineer's confirmation onto those words, so a
comment nobody read was issued as confirmed. Now the number stays, the tick
does not travel: the row is unconfirmed until the engineer confirms the new
words (or edits them), which also refreshes the words the number keeps.
Invented data only (the `world` run of test_review_screen).
"""

from __future__ import annotations

from app import crs_carry, crs_mapping, crs_numbers, main
from app.access import AccessScope
from tests.test_b3_page_ledger import temp_storage  # noqa: F401 - autouse
from tests.test_review_screen import world  # noqa: F401

OLD_WORDS = "Invented earlier wording the engineer confirmed under this number."


def _scope(scope):
    return AccessScope(user_id="eng-1", allowed_document_ids=scope)


def _rows(run, scope):
    rows, *_ = main._crs_content(run, _scope(scope))
    return rows


def _first_plain_row(rows):
    [row] = [
        r
        for r in rows
        if r.get("crs_row_key")
        and r.get("finding_id")
        and not str(r.get("ai_review_comment") or "").strip()
        and r.get("comment")
    ][:1]
    return row


def _issue(world_, key, words):
    """The engineer issued number N for `key` with `words` stored."""
    sub, run, *_ = world_
    crs_scope, label = main._crs_scope_of(sub)
    stored = crs_numbers.assign(
        crs_scope,
        label,
        [key],
        document_id=sub,
        review_run_id=run,
        snapshots={key: {"comment": words, "comment_by": "Eng"}},
        user_id="eng-1",
    )
    return stored[key]["ref"], crs_scope


def test_the_same_words_under_an_issued_number_stay_confirmed(world):  # noqa: F811
    _sub, run, scope = world
    row = _first_plain_row(_rows(run, scope))
    key, words = row["crs_row_key"], row["comment"]
    ref, _ = _issue(world, key, words)
    again = _first_plain_row(_rows(run, scope))
    assert again["crs_ref"] == ref
    assert again["engineer_confirmed"] is True
    assert again.get("changed_since_confirmed") is None


def test_other_words_under_an_issued_number_keep_the_number_and_lose_the_tick(world):  # noqa: F811
    _sub, run, scope = world
    row = _first_plain_row(_rows(run, scope))
    key = row["crs_row_key"]
    ref, _ = _issue(world, key, OLD_WORDS)
    again = _first_plain_row(_rows(run, scope))
    assert again["crs_ref"] == ref  # the number is permanent
    assert not again.get("engineer_confirmed")
    assert again["changed_since_confirmed"] is True


def test_case_and_spacing_alone_are_not_a_change(world):  # noqa: F811
    _sub, run, scope = world
    row = _first_plain_row(_rows(run, scope))
    key = row["crs_row_key"]
    noisy = "  " + row["comment"].upper().replace(" ", "   ") + "\n"
    _issue(world, key, noisy)
    again = _first_plain_row(_rows(run, scope))
    assert again["engineer_confirmed"] is True


def test_a_number_that_kept_no_words_is_not_judged(world):  # noqa: F811
    """An older build saved the number with no words: nothing to compare, so the
    earlier behaviour stands (the row stays confirmed)."""
    _sub, run, scope = world
    row = _first_plain_row(_rows(run, scope))
    _issue(world, row["crs_row_key"], "")
    again = _first_plain_row(_rows(run, scope))
    assert again["engineer_confirmed"] is True
    assert again.get("changed_since_confirmed") is None


def test_the_line_added_for_replaced_numbers_is_not_part_of_the_words():
    snapshot = {
        "comment": "Contractor to revise the value.\n"
        "Replaces earlier comments CRS-0001, CRS-0002 (now one comment per field)."
    }
    assert not crs_carry.words_changed_since_issue(
        {"comment": "Contractor to revise the value."}, snapshot
    )
    assert crs_carry.words_changed_since_issue(
        {"comment": "Contractor to revise the value to 12."}, snapshot
    )


def test_a_draft_that_prints_the_issued_words_is_not_judged():
    row = {"comment": "x", "ai_review_comment": "the draft"}
    assert not crs_carry.words_changed_since_issue(row, {"comment": "other"})


def test_a_waiting_sentence_is_not_words():
    waiting = crs_mapping.AI_UNCONFIRMED_COMMENT
    assert not crs_carry.words_changed_since_issue(
        {"comment": "now"}, {"comment": waiting}
    )
    assert not crs_carry.words_changed_since_issue(
        {"comment": waiting}, {"comment": "then"}
    )


def test_a_carried_tick_does_not_refresh_the_words_the_number_keeps(world):  # noqa: F811
    """Unchanged words keep their tick by number; writing a snapshot from a row that
    was only confirmed by its number would store words nobody just confirmed."""
    sub, run, scope = world
    row = _first_plain_row(_rows(run, scope))
    key = row["crs_row_key"]
    kept = row["comment"].upper()  # the same words, spelled so a refresh would show
    _issue(world, key, kept)
    again = _first_plain_row(_rows(run, scope))
    assert again["confirmed_by_number"] is True
    crs_scope, _label = main._crs_scope_of(sub)
    main._mint_crs_numbers(run, _scope(scope))
    assert crs_numbers.lookup(crs_scope, [key])[key]["comment"] == kept


def test_a_row_issued_before_references_named_their_edition_is_not_seen_as_changed():
    """Order 227: the edition gained by the Standard Reference (and so by the comment's lead)
    is not the words changing; a real change still is."""
    old = {"comment": "STD-100 cl. 4.3 (p.4): requires X. Contractor to revise X."}
    for lead in ("STD-100 (edition not recorded) cl. 4.3 (p.4)", "STD-100 (2023) cl. 4.3 (p.4)"):
        now = {"comment": f"{lead}: requires X. Contractor to revise X."}
        assert not crs_carry.words_changed_since_issue(now, old)
    changed = {"comment": "STD-100 (2023) cl. 4.3 (p.4): requires Y. Contractor to revise Y."}
    assert crs_carry.words_changed_since_issue(changed, old)
    # two editions of the same clause are two comments once the first one named its edition
    named = {"comment": "STD-100 (2019) cl. 4.3 (p.4): requires X. Contractor to revise X."}
    now = {"comment": "STD-100 (2023) cl. 4.3 (p.4): requires X. Contractor to revise X."}
    assert crs_carry.words_changed_since_issue(now, named)
