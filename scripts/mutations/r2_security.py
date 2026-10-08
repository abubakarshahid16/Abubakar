"""Mutations for the r2 security fixes (2026-10-05, M1980-M1989).

Each puts one defect back; the named test file must turn red. Files:
backend/app/{main,review,submittal_review,deliverables,risks,reports,
claude_api,claude_spend}.py.
"""

from __future__ import annotations

from ._base import APP, Mutation

_TAG = ("r2_security",)
_T1 = "tests/test_r2_security_s1_admin_only.py"
_T2 = "tests/test_r2_security_s2_standard_withheld.py"
_T3 = "tests/test_r2_security_s3_unscoped_rows.py"
_T4 = "tests/test_r2_security_s4_report_ownership.py"
_T5 = "tests/test_r2_security_s5_reasoning_provider.py"
_T6 = "tests/test_r2_security_s6_ledger_torn_line.py"
_T7 = "tests/test_r2_security_s7_identity_required.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1980", phase=1980,
             description="DELETE /api/documents/{id} no longer requires an admin",
             path=APP / "main.py",
             anchor='    _admin: dict | None = Depends(admin_mod.current_admin),\n'
                    '):\n    """Remove a document and everything derived from it.',
             replacement='):\n    """Remove a document and everything derived from it.',
             target=_T1, keyword="reader_cannot_delete", tags=_TAG),
    Mutation(id="M1981", phase=1981,
             description="a finding keeps the standard's fields although the caller holds no grant on it",
             path=APP / "review.py",
             anchor='        if f.get("standard_document_id") not in existing:\n            continue',
             replacement='        if True:\n            continue',
             target=_T2, keyword="withholds", tags=_TAG),
    Mutation(id="M1982", phase=1982,
             description="a run's findings (CRS preview and workbook) are no longer redacted",
             path=APP / "submittal_review.py",
             anchor='    return review.withhold_unreadable_standards(out, allowed_document_ids)',
             replacement='    return out',
             target=_T2, keyword="crs", tags=_TAG),
    Mutation(id="M1983", phase=1983,
             description="a deliverable with no document is open to a caller with no grant",
             path=APP / "main.py",
             anchor='    return scope.is_admin or bool(scope.allowed_document_ids)',
             replacement='    return True',
             target=_T3, keyword="no_grants_cannot_write", tags=_TAG),
    Mutation(id="M1984", phase=1984,
             description="an expectation inferred from a hidden document is returned",
             path=APP / "deliverables.py",
             anchor='        where.append(f"(e.source_document_id IS NULL OR e.source_document_id IN ({marks}))")',
             replacement='        pass',
             target=_T3, keyword="inferred_from_a_hidden_document", tags=_TAG),
    Mutation(id="M1985", phase=1985,
             description="POST /api/reports skips the conversation-ownership check",
             path=APP / "reports.py",
             anchor='    if owner is None or not scope.owns_conversation(owner["owner_user_id"]):',
             replacement='    if owner is None:',
             target=_T4, keyword="another_users_message", tags=_TAG),
    Mutation(id="M1986", phase=1986,
             description="the Claude review routes ignore REASONING_PROVIDER again",
             path=APP / "claude_api.py",
             anchor='    code, why = rp_mod.claude_unavailable()',
             replacement='    code, why = None, ""',
             target=_T5, keyword="provider_is_not_claude or only_for_provider_claude", tags=_TAG),
    Mutation(id="M1987", phase=1987,
             description="a torn ledger line is skipped again (the cap is lifted)",
             path=APP / "claude_spend.py",
             anchor='                out.append({"step": CORRUPT_STEP, "corrupt": True,',
             replacement='                continue\n                out.append({"step": CORRUPT_STEP, "corrupt": True,',
             target=_T6, keyword="torn_line or invalid_line", tags=_TAG),
    Mutation(id="M1988", phase=1988,
             description="the identity gate on corpus-derived routes is switched off",
             path=APP / "main.py",
             anchor='            and not await run_in_threadpool(access.request_identity, request)):',
             replacement='            and False):',
             target=_T7, keyword="no_identity_is_401", tags=_TAG),
    Mutation(id="M1989", phase=1989,
             description="an overdue-deliverable risk drops the source document again",
             path=APP / "risks.py",
             anchor='"document_id": (by_id.get(alert["deliverable_id"]) or {}).get("document_id")}))',
             replacement='"document_id": None}))',
             target=_T3, keyword="overdue_risk", tags=_TAG),
)
