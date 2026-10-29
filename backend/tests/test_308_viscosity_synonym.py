"""Order 308: a field read under a near name is linked through the synonym table before any absence claim.
The relieving-viscosity label a sheet prints ("Viscosity at relieving temper.") is the same quantity as the
checklist's "viscosity relieving". Invented sheets only."""

from __future__ import annotations

import pytest

from app import crs_page_words, db, field_links, submittal_review
from tests.test_228_page_column import (  # noqa: F401 - fixture and helper
    NOW,
    _sheet,
    temp_storage,
)


@pytest.mark.parametrize(
    "label",
    [
        "Viscosity at relieving temper.",
        "Viscosity at relieving temperature",
        "viscosity at relieving temp",
        "Relieving viscosity",
    ],
)
def test_every_spelling_of_the_relieving_viscosity_folds_to_one_name(label):
    assert field_links.canonical(label) == field_links.canonical("viscosity relieving")


def test_a_different_viscosity_is_not_folded():
    assert field_links.canonical("Viscosity at 20 degC") != field_links.canonical(
        "viscosity relieving"
    )


def test_the_page_cell_names_the_exact_field_not_a_probable_one(temp_storage):  # noqa: F811
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    doc = _sheet(5)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO submittal_facts (id, review_run_id, submittal_document_id, field_name, field_label,"
            " field_value, raw_value, page, is_blank, extraction_method, created_at, updated_at)"
            " VALUES ('f1', NULL, ?, 'viscosity at relieving temper', 'Viscosity at relieving temper.',"
            " '0.01 cP', '0.01', 4, 0, 'extracted', ?, ?)",
            (doc, NOW, NOW),
        )
    pages, exact = crs_page_words.read_pages({doc}, "Viscosity relieving")
    assert pages == [4] and exact is True
