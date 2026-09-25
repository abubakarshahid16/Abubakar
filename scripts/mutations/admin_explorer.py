"""Mutations of `backend/app/admin_explorer.py`."""

from __future__ import annotations

from ._base import APP, Mutation


MUTATIONS: tuple[Mutation, ...] = (
    # ---- from ADMIN_EXPLORER ----------------------------------------------
    #: The read-only database explorer: who may look, and what they may see.
    Mutation(
        id="M227", phase=20,
        description="STOP MASKING ENTIRELY, putting every stored password "
                    "hash on the wire",
        path=APP / "admin_explorer.py",
        anchor="    rows = [mask_row(columns, list(r)) for r in cur.fetchall()]",
        replacement="    rows = [list(r) for r in cur.fetchall()]",
        target="tests/test_admin_db_routes.py",
        keyword="password_hash_never_reaches_the_wire",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M228", phase=20,
        description="narrow the rule to EQUALITY, so `password_hash` and "
                    "`setup_token_sha256` sail through unmasked",
        path=APP / "admin_explorer.py",
        anchor="    return any(part in name for part in SENSITIVE_NAME_PARTS)",
        replacement="    return name in SENSITIVE_NAME_PARTS",
        target="tests/test_admin_explorer.py",
        keyword="credential_shaped_name_is_masked",
        tags=("critical",),
    ),
    Mutation(
        id="M229", phase=20,
        description="let the token_count exemption match as a SUBSTRING, a "
                    "hole shaped like a naming convention",
        path=APP / "admin_explorer.py",
        anchor="    if name in NOT_CREDENTIALS:",
        replacement="    if any(x in name for x in NOT_CREDENTIALS):",
        target="tests/test_admin_explorer.py",
        keyword="exemption_is_by_exact_name_and_does_not_spread",
    ),
    Mutation(
        id="M230", phase=20,
        description="mask a NULL too, claiming a secret is stored where none "
                    "is - itself a disclosure about the row",
        path=APP / "admin_explorer.py",
        anchor="        MASK if (is_sensitive(name) and value is not None) else value",
        replacement="        MASK if is_sensitive(name) else value",
        target="tests/test_admin_explorer.py",
        keyword="null_stays_null_rather_than_becoming_a_mask",
        tags=("honesty",),
    ),
    Mutation(
        id="M231", phase=20,
        description="DROP the sensitive column from the listing instead of "
                    "masking it, so the explorer misreports the table's shape",
        path=APP / "admin_explorer.py",
        anchor='            "pk": bool(r[5]), "sensitive": is_sensitive(r[1])}\n'
               '            for r in conn.execute(f\'PRAGMA table_info("{table}")\')]',
        replacement='            "pk": bool(r[5]), "sensitive": is_sensitive(r[1])}\n'
                    '            for r in conn.execute(f\'PRAGMA table_info("{table}")\')\n'
                    '            if not is_sensitive(r[1])]',
        target="tests/test_admin_explorer.py",
        keyword="marks_the_column_without_hiding_it",
        tags=("honesty",),
    ),
)
