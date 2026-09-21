from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas import AnalysisRequest


@pytest.mark.parametrize("kind", [
    "baseline_vs_submittal", "requirements_vs_submittal",
    "revision_delta", "discipline_coordination",
])
def test_named_engineering_comparison_types_are_accepted(kind):
    request = AnalysisRequest(question="compare the requirements", comparison_type=kind)
    assert request.comparison_type == kind


def test_unknown_comparison_type_is_rejected():
    with pytest.raises(ValidationError):
        AnalysisRequest(question="compare", comparison_type="free_form")
