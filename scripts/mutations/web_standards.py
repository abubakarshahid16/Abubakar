"""Owner order 2d-2: the public web standards check (kind D)."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_web_standards.py"
_W = APP / "web_standards.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1112", phase=93, description="a company identifier is treated as public",
             path=_W,
             anchor='    if not text or _COMPANY_MARKERS.search(text):\n        return False\n',
             replacement='    if not text:\n        return False\n',
             target=_T, keyword="refuses_even_alongside_a_public_looking_prefix",
             tags=("privacy", "critical")),
    Mutation(id="M1113", phase=93, description="a company identifier is never attempted, but the gate is bypassed",
             path=_W,
             anchor='    return bool(_PUBLIC_PREFIX.match(text))\n',
             replacement='    return True\n',
             target=_T, keyword="a_company_or_project_identifier_is_never_searchable", tags=("privacy", "critical")),
    Mutation(id="M1114", phase=93, description="the flag off does not stop the check",
             path=_W,
             anchor='    if not settings.review_web_standards_enabled:\n        return False, "the public web standards check is switched off"\n',
             replacement='    if False:\n        return False, "the public web standards check is switched off"\n',
             target=_T, keyword="the_flag_is_off_by_default", tags=("privacy", "critical")),
    Mutation(id="M1115", phase=93, description="an unverified quote is kept anyway",
             path=_W,
             anchor='    return bool(quote) and _fold(quote) in _fold(page_text)\n',
             replacement='    return bool(quote)\n',
             target=_T, keyword="an_unverified_quote_is_never_kept", tags=("honesty", "critical")),
    Mutation(id="M1116", phase=93, description="a differing edition is compared anyway",
             path=_W,
             anchor='    return bool(cited and web and cited.group() != web.group())\n',
             replacement='    return False\n',
             target=_T, keyword="a_differing_edition_is_never_compared", tags=("honesty",)),
    Mutation(id="M1117", phase=93,
             description="a kept web check item is stored with a compliance status, so it would be counted",
             path=_W,
             anchor="                       contractor_page = ?, contractor_evidence_text = ?, ai_rationale = ?\n                   WHERE id = ?\"\"\",\n",
             replacement="                       contractor_page = ?, contractor_evidence_text = ?, ai_rationale = ?,\n                       compliance_status = 'COMPLIANT'\n                   WHERE id = ?\"\"\",\n",
             target=_T, keyword="a_kept_item_is_a_never_counted_pending_draft",
             tags=("honesty", "critical")),
)
