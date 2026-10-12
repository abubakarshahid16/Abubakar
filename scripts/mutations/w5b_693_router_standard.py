"""#693: the router has a standard kind and reads the recorded role. Ids M4921-M4926."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_w5b_693_router_standard.py"
_TAG = ("w5b", "router")
_ROUTER = APP / "doc_router.py"
_CUES = APP / "reference" / "document_kinds.json"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M4921", phase=4921, description="the role cue never fires (score ignores the role)",
             path=_ROUTER, anchor='                hit = role is not None and role == cue.get("role")',
             replacement="                hit = False",
             target=_T, keyword="classified_as_a_company_standard", tags=_TAG),
    Mutation(id="M4922", phase=4922, description="any recorded role counts as a standard",
             path=_ROUTER, anchor='                hit = role is not None and role == cue.get("role")',
             replacement="                hit = role is not None",
             target=_T, keyword="does_not_turn_a_procedure", tags=_TAG),
    Mutation(id="M4923", phase=4923, description="a stored document is routed without its recorded role",
             path=_ROUTER, anchor='                    recorded["document_role"] if recorded is not None else None)',
             replacement="                    None)",
             target=_T, keyword="reads_the_recorded_role", tags=_TAG),
    Mutation(id="M4924", phase=4924, description="the router version stays 1, so old procedure suggestions are never re-read",
             path=_CUES, anchor='"router_version": "2"', replacement='"router_version": "1"',
             target=_T, keyword="router_version_change", tags=_TAG),
    Mutation(id="M4925", phase=4925, description="the standard kind is missing from the vocabulary",
             path=_CUES, anchor='    "standard": {\n      "label": "Standard",',
             replacement='    "standard_off": {\n      "label": "Standard",',
             target=_T, keyword="offers_standard_as_a_kind", tags=_TAG),
    Mutation(id="M4926", phase=4926, description="the standard's own words (normative references, definitions) carry no weight",
             path=_CUES, anchor='"pattern": "normative references?|terms and definitions|foreword", "weight": 1}',
             replacement='"pattern": "normative references?|terms and definitions|foreword", "weight": 0}',
             target=_T, keyword="read_as_a_standard", tags=_TAG),
)
