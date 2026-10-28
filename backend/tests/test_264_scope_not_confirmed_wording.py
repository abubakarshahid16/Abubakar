"""Order 264.7 / 300.3: a clause of a standard whose own scope could not be tied to the equipment says so, and says
the engineer must judge whether it applies. It never says the clause is "compared as usual" (it was kept for
the engineer; nothing was decided about its scope)."""

from __future__ import annotations

from app import scope_type_words


def test_the_note_says_the_scope_was_not_tied_and_the_engineer_must_judge():
    note = scope_type_words.SCOPE_NOT_CONFIRMED
    assert "could not be tied to this equipment" in note
    assert "engineer must judge whether this clause applies" in note


def test_the_note_never_says_the_clause_is_compared_as_usual():
    assert "as usual" not in scope_type_words.SCOPE_NOT_CONFIRMED.lower()
