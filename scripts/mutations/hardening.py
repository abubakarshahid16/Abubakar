"""Mutations of P5: progress ownership and governed audit writes."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_p5_hardening.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M890", phase=78, description="P5: any caller reads anyone's progress",
             path=APP / "progress.py", anchor="        if not unrestricted and entry.owner != reader:\n            return None\n",
             replacement="", target=_T, keyword="only_by_the_one", tags=("privacy",)),
    Mutation(id="M891", phase=78, description="P5: progress answers an anonymous caller",
             path=APP / "main.py",
             anchor="    if not scope.unrestricted and not scope.user_id:\n        raise HTTPException(status_code=401, detail=errors.safe_error(\n            errors.UNAUTHENTICATED, \"sign in to continue\"))\n    state = progress_mod.read(",
             replacement="    state = progress_mod.read(",
             target=_T, keyword="signed_in_caller", tags=("privacy",)),
    Mutation(id="M892", phase=78, description="P5: a grant is written outside its audit's transaction",
             path=APP / "admin.py",
             anchor="        _audit(\"admin_grant\", actor, \"document\", body.document_id,\n               detail=role[\"name\"], conn=conn)\n",
             replacement="        pass\n    try:\n        _audit(\"admin_grant\", actor, \"document\", body.document_id,\n               detail=role[\"name\"])\n    except Exception:\n        raise\n",
             target=_T, keyword="grant_whose_audit_fails", tags=("audit", "critical")),
    Mutation(id="M893", phase=78, description="P5: a revoke is written outside its audit's transaction",
             path=APP / "admin.py",
             anchor="        _audit(\"admin_revoke\", actor, \"document\", body.document_id,\n               detail=role[\"name\"], conn=conn)\n",
             replacement="        pass\n    _audit(\"admin_revoke\", actor, \"document\", body.document_id,\n           detail=role[\"name\"])\n",
             target=_T, keyword="revoke_whose_audit_fails", tags=("audit",)),
    Mutation(id="M894", phase=78, description="P5: the admin audit swallows failure again",
             path=APP / "admin.py",
             anchor="    own = connect()\n    with own:\n        own.execute(sql, args)\n",
             replacement="    try:\n        own = connect()\n        with own:\n            own.execute(sql, args)\n    except Exception:\n        pass\n",
             target=_T, keyword="outside_a_transaction", tags=("audit",)),
    Mutation(id="M895", phase=78, description="P5: a standards decision's audit failure is swallowed",
             path=APP / "standards.py",
             anchor="    conn = connect()\n    with conn:\n        conn.execute(\n            \"\"\"INSERT INTO audit_events\n                   (at, actor_user_id, actor_username, action,\n                    resource_type, resource_id, outcome, detail)\n               VALUES (?, ?, ?, ?, 'standard', ?, ?, ?)\"\"\",\n",
             replacement="    conn = connect()\n    with __import__('contextlib').suppress(Exception), conn:\n        conn.execute(\n            \"\"\"INSERT INTO audit_events\n                   (at, actor_user_id, actor_username, action,\n                    resource_type, resource_id, outcome, detail)\n               VALUES (?, ?, ?, ?, 'standard', ?, ?, ?)\"\"\",\n",
             target=_T, keyword="standards_decision", tags=("audit",)),
    Mutation(id="M896", phase=78, description="P5: a login audit failure is discarded silently",
             path=APP / "auth.py", anchor="        errors.record_failure(exc, stage=\"auth_audit\")\n",
             replacement="        pass\n", target=_T, keyword="login_survives", tags=("audit",)),
)
