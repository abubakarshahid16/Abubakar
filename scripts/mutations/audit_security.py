"""Mutations for the security audit of 2026-09-30 (M1480-M1499).

Each puts one verified defect back. Every target is in
`backend/tests/test_access_audit_security.py`, which must go red.
"""

from __future__ import annotations

from ._base import APP, REPO, Mutation

_T = "tests/test_access_audit_security.py"
_MAIN = APP / "main.py"
_CONFIG = APP / "config.py"
_ADMIN = APP / "admin.py"
_PHASE = 90


def _drop_admin(signature_head: str, indent: str) -> tuple[str, str]:
    """Anchor/replacement pair that removes the admin gate from one route."""
    anchor = (signature_head + "\n" + indent
              + "_actor: dict | None = Depends(admin_mod.current_admin)):")
    replacement = signature_head[:-1] + "):"
    return anchor, replacement


_SCHEDULE = _drop_admin(
    "                         scope: access.AccessScope = Depends(access.current_scope),",
    "                         ")
_ESCALATION = _drop_admin(
    "                           scope: access.AccessScope = Depends(access.current_scope),",
    "                           ")

MUTATIONS: tuple[Mutation, ...] = (
    # ---- 1. DNS rebinding / bind ------------------------------------------
    Mutation(
        id="M1480", phase=_PHASE,
        description="the Host header is no longer checked (DNS rebinding reopens)",
        path=_MAIN,
        anchor="    if host_header_name(request.headers.get(\"host\", \"\")) not in trusted_host_names(settings):",
        replacement="    if False:",
        target=_T, keyword="foreign_host_header",
        tags=("privacy", "security"),
    ),
    Mutation(
        id="M1481", phase=_PHASE,
        description="the TestClient's name becomes a production default",
        path=_CONFIG,
        anchor='LOOPBACK_HOST_HEADERS = frozenset({"localhost", "127.0.0.1", "::1"})',
        replacement='LOOPBACK_HOST_HEADERS = frozenset({"localhost", "127.0.0.1", "::1", "testserver", "rag.lan"})',
        target=_T, keyword="allowed_hosts_adds_a_name",
        tags=("security",),
    ),
    Mutation(
        id="M1482", phase=_PHASE,
        description="HOST=0.0.0.0 with AUTH_MODE=disabled starts",
        path=_CONFIG,
        anchor='        if (self.auth_mode == "disabled" and not is_loopback_bind(self.host)',
        replacement='        if (False and not is_loopback_bind(self.host)',
        target=_T, keyword="unauthenticated_network_bind",
        tags=("privacy", "security"),
    ),
    # ---- 2. deliverable PATCH ---------------------------------------------
    Mutation(
        id="M1483", phase=_PHASE,
        description="the deliverable PATCH writes before it checks the scope",
        path=_MAIN,
        anchor=("    existing = deliverables_mod.get(deliverable_id)\n"
                "    if existing is None or not _deliverable_visible(existing, scope):"),
        replacement=("    existing = deliverables_mod.get(deliverable_id)\n"
                     "    if False:"),
        target=_T, keyword="hidden_deliverable",
        tags=("security",),
    ),
    # ---- 3. POST /api/risks -----------------------------------------------
    Mutation(
        id="M1484", phase=_PHASE,
        description="an anonymous caller can write a risk again",
        path=_MAIN,
        anchor=("    owner. Length limits live on `schemas.RiskCreate`.\n"
                "    \"\"\"\n"
                "    _require_identity_to_write(scope)\n"),
        replacement=("    owner. Length limits live on `schemas.RiskCreate`.\n"
                     "    \"\"\"\n"),
        target=_T, keyword="anonymous_caller_cannot_write_a_risk",
        tags=("security",),
    ),
    Mutation(
        id="M1485", phase=_PHASE,
        description="a risk may point at a document outside the caller's scope",
        path=_MAIN,
        anchor=("    if body.document_id:\n"
                "        require_document(body.document_id, scope)\n"
                "    if body.deliverable_id:\n"),
        replacement="    if body.deliverable_id:\n",
        target=_T, keyword="risk_on_a_hidden_document",
        tags=("security",),
    ),
    Mutation(
        id="M1486", phase=_PHASE,
        description="a risk description is unbounded again",
        path=APP / "schemas.py",
        anchor="    description: str = Field(max_length=5000)\n    severity: str = Field(default=\"medium\", max_length=50)",
        replacement="    description: str\n    severity: str = Field(default=\"medium\", max_length=50)",
        target=_T, keyword="length_limited",
        tags=("security",),
    ),
    # ---- 4. global settings, admin only -----------------------------------
    Mutation(
        id="M1487", phase=_PHASE,
        description="any signed-in user changes the summary schedule",
        path=_MAIN, anchor=_SCHEDULE[0], replacement=_SCHEDULE[1],
        target=_T, keyword="summary_schedule",
        tags=("security",),
    ),
    Mutation(
        id="M1488", phase=_PHASE,
        description="any signed-in user changes an escalation rule",
        path=_MAIN, anchor=_ESCALATION[0], replacement=_ESCALATION[1],
        target=_T, keyword="escalation_rule",
        tags=("security",),
    ),
    Mutation(
        id="M1489", phase=_PHASE,
        description="any signed-in user creates a baseline rule",
        path=_MAIN,
        anchor=("def create_review_baseline_rule(body: schemas.ReviewBaselineRuleCreate,\n"
                "                                scope: access.AccessScope = Depends(access.current_scope),\n"
                "                                _actor: dict | None = Depends(admin_mod.current_admin)):"),
        replacement=("def create_review_baseline_rule(body: schemas.ReviewBaselineRuleCreate,\n"
                     "                                scope: access.AccessScope = Depends(access.current_scope)):"),
        target=_T, keyword="create_a_baseline_rule",
        tags=("security",),
    ),
    Mutation(
        id="M1490", phase=_PHASE,
        description="any signed-in user edits a baseline rule",
        path=_MAIN,
        anchor=("def update_review_baseline_rule(rule_id: str, body: schemas.ReviewBaselineRuleCreate,\n"
                "                                scope: access.AccessScope = Depends(access.current_scope),\n"
                "                                _actor: dict | None = Depends(admin_mod.current_admin)):"),
        replacement=("def update_review_baseline_rule(rule_id: str, body: schemas.ReviewBaselineRuleCreate,\n"
                     "                                scope: access.AccessScope = Depends(access.current_scope)):"),
        target=_T, keyword="edit_a_baseline_rule",
        tags=("security",),
    ),
    Mutation(
        id="M1491", phase=_PHASE,
        description="any signed-in user registers a review template",
        path=_MAIN,
        anchor=("    body: schemas.ReviewTemplateCreate,\n"
                "    scope: access.AccessScope = Depends(access.current_scope),\n"
                "    _actor: dict | None = Depends(admin_mod.current_admin),\n"),
        replacement=("    body: schemas.ReviewTemplateCreate,\n"
                     "    scope: access.AccessScope = Depends(access.current_scope),\n"),
        target=_T, keyword="review_template",
        tags=("security",),
    ),
    # ---- 5. password reset ------------------------------------------------
    Mutation(
        id="M1492", phase=_PHASE,
        description="redeeming a reset token leaves earlier sessions valid",
        path=_ADMIN,
        anchor='            "UPDATE users SET password_hash = ?, token_epoch = token_epoch + 1 "',
        replacement='            "UPDATE users SET password_hash = ? "',
        target=_T, keyword="redeeming_a_reset_token",
        tags=("security",),
    ),
    Mutation(
        id="M1493", phase=_PHASE,
        description="an admin password reset leaves the user's sessions valid",
        path=_ADMIN,
        anchor=('        conn.execute(\n'
                '            "UPDATE users SET token_epoch = token_epoch + 1 WHERE id = ?",\n'
                '            (user_id,))\n'
                '    _audit("admin_password_reset_issued", actor, "user", user_id)'),
        replacement='    _audit("admin_password_reset_issued", actor, "user", user_id)',
        target=_T, keyword="admin_password_reset_ends",
        tags=("security",),
    ),
    # ---- 6. categorize_documents ------------------------------------------
    Mutation(
        id="M1494", phase=_PHASE,
        description="categorize_documents posts chunk text with a bare httpx.post "
                    "(proxy-honouring, unchecked URL) again",
        path=REPO / "scripts" / "categorize_documents.py",
        anchor='    data = model_transport.post_json(\n        "/api/chat",\n',
        replacement=('    data = (lambda path, body, timeout: __import__("httpx").post(\n'
                     '        f"{settings.ollama_url}{path}", json=body, timeout=timeout).json())(\n'
                     '        "/api/chat",\n'),
        target=_T, keyword="only_through_the_model_transport",
        tags=("privacy",),
    ),
    # ---- 8. LOW -----------------------------------------------------------
    Mutation(
        id="M1495", phase=_PHASE,
        description="a CRS reply workbook is opened without the upload limits",
        path=APP / "crs_reply.py",
        anchor="        validate_xlsx(io.BytesIO(data))\n",
        replacement="        pass\n",
        target=_T, keyword="expands_past_the_upload_limit",
        tags=("security",),
    ),
    Mutation(
        id="M1496", phase=_PHASE,
        description="/docs and /openapi.json are public under demo_required",
        path=_MAIN,
        anchor="    if request.url.path in _API_DOC_PATHS and not _api_docs_served():",
        replacement="    if False:",
        target=_T, keyword="not_public_under_demo_required",
        tags=("security",),
    ),
    # ---- 7. CI guards -----------------------------------------------------
    Mutation(
        id="M1497", phase=_PHASE,
        description="the CI synthetic-fixture exclusion names a path that does not exist",
        path=REPO / ".github" / "workflows" / "secret-scan.yml",
        anchor="            | grep -v '^backend/tests/fixtures/synthetic/' \\\n",
        replacement="            | grep -v '^tests/fixtures/synthetic/' \\\n",
        target=_T, keyword="synthetic_fixture_exclusion",
        tags=("privacy",),
    ),
    Mutation(
        id="M1498", phase=_PHASE,
        description="the CI identifier check finds tokens but never reports them",
        path=REPO / "scripts" / "check_client_identifiers.py",
        anchor="            found.append(token)\n",
        replacement="            pass\n",
        target=_T, keyword="identifier_check_blocks_new_tokens",
        tags=("privacy",),
    ),
    Mutation(
        id="M1499", phase=_PHASE,
        description="gitleaks allowlists every line of .env.example again",
        path=REPO / ".gitleaks.toml",
        anchor="  '''(^|/)package-lock\\.json$''',\n",
        replacement="  '''\\.env\\.example$''',\n  '''(^|/)package-lock\\.json$''',\n",
        target=_T, keyword="gitleaks_no_longer_allowlists",
        tags=("privacy", "security"),
    ),
)
