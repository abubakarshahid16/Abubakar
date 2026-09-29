"""Every requirement type the extractor stores can be returned by the API.

The response model listed three types while `requirements_3b` also writes
`applicability_trigger`, `relative_limit` and `table_row`, so a standard
holding any of them failed GET /api/standards/{id}/requirements with a 500.
Found 2026-09-30 by the frontend contract check. Mutation M1615.
"""
from typing import get_args

import pytest

from app import requirements_3b, schemas


def test_the_schema_accepts_every_type_the_extractor_stores():
    assert set(get_args(schemas.RequirementType)) == set(requirements_3b.STORED_REQUIREMENT_TYPES)


@pytest.mark.parametrize("kind", requirements_3b.STORED_REQUIREMENT_TYPES)
def test_a_stored_row_of_each_type_validates_as_a_response(kind):
    from pydantic import TypeAdapter
    assert TypeAdapter(schemas.RequirementType).validate_python(kind) == kind
