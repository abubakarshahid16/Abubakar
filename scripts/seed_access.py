"""Create roles, users and document grants for AUTH_MODE=demo_required.

Nothing here has a default password, and there is no demo credential in this
repository to leak into production. That is a stronger guarantee than any scan
for one: a password can only ever arrive by being typed, interactively, twice.

    python scripts/seed_access.py --roles
    python scripts/seed_access.py --user ali@example.com --role engineer
    python scripts/seed_access.py --user ali@example.com --role engineer --force
    python scripts/seed_access.py --grant engineer --document doc_ab12cd34
    python scripts/seed_access.py --verify-only

`--verify-only` reports users with no roles and roles with no grants, because
"seeded but useless" is a state you want to discover before a demo rather than
during one: such a user logs in successfully and then sees an empty corpus,
which looks like a broken search rather than a missing grant.
"""

from __future__ import annotations

import argparse
import getpass
import re
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.db import connect, init_db  # noqa: E402

#: Deliberately small. A role is a name plus a description; everything else is
#: a grant, and grants are per document.
ROLES = {
    "admin": "Full access to every document",
    "engineer": "Documents granted to the engineering role",
    "reviewer": "Read-only access to granted documents",
}

MIN_PASSWORD = 12

#: Rejected outright, whatever else the password contains. Not a strength
#: meter - a list of the passwords that actually get typed at a demo.
FORBIDDEN = {
    "password", "passw0rd", "demo", "demo1234", "nabaa", "changeme",
    "letmein", "welcome", "aramco", "12345678", "qwerty", "admin",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def check_password(password: str, email: str) -> list[str]:
    """Every reason to refuse, so the operator fixes them in one go."""
    problems = []
    if len(password) < MIN_PASSWORD:
        problems.append(f"shorter than {MIN_PASSWORD} characters")
    low = password.lower()
    if low in FORBIDDEN:
        problems.append("is one of the passwords everyone tries first")
    for bad in FORBIDDEN:
        if bad in low and bad not in ("admin",):
            problems.append(f"contains {bad!r}")
            break
    local = re.split(r"[@+]", email)[0].lower()
    if local and len(local) >= 3 and local in low:
        problems.append("contains the email address")
    if password.strip() != password:
        problems.append("starts or ends with whitespace")
    return problems


def prompt_password(email: str) -> str:
    """Interactive only, twice, never echoed.

    There is no --password flag on purpose: it lands in shell history and is
    visible in `ps` to every other user on the machine.
    """
    for _ in range(3):
        first = getpass.getpass(f"Password for {email}: ")
        problems = check_password(first, email)
        if problems:
            print("  refused: " + "; ".join(problems))
            continue
        if first != getpass.getpass("Repeat: "):
            print("  refused: the two entries differ")
            continue
        return first
    raise SystemExit("no acceptable password given")


def seed_roles(conn) -> int:
    made = 0
    with conn:
        for name, description in ROLES.items():
            row = conn.execute("SELECT id FROM roles WHERE name = ?",
                               (name,)).fetchone()
            if row:
                continue
            conn.execute(
                "INSERT INTO roles (id, name, description, created_at) "
                "VALUES (?, ?, ?, ?)",
                (f"role_{secrets.token_hex(6)}", name, description, _now()),
            )
            made += 1
    print(f"roles: {made} created, {len(ROLES) - made} already present")
    return 0


def seed_user(conn, email: str, role: str, force: bool) -> int:
    from app.auth import _hasher
    from app.config import settings

    email = email.strip().lower()
    role_row = conn.execute("SELECT id FROM roles WHERE name = ?",
                            (role,)).fetchone()
    if role_row is None:
        print(f"no such role: {role}. Run --roles first.", file=sys.stderr)
        return 2

    existing = conn.execute("SELECT id FROM users WHERE lower(email) = ?",
                            (email,)).fetchone()
    if existing and not force:
        # Re-seeding is how a known password quietly replaces a real one.
        print(f"{email} already exists. Re-seeding would replace their "
              f"password; pass --force if that is what you mean.",
              file=sys.stderr)
        return 2

    password = prompt_password(email)
    user_id = existing["id"] if existing else f"user_{secrets.token_hex(6)}"
    with conn:
        if existing:
            conn.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                         (_hasher.hash(password), user_id))
        else:
            conn.execute(
                """INSERT INTO users (id, email, display_name, password_hash,
                                      is_active, created_at)
                   VALUES (?, ?, ?, ?, 1, ?)""",
                (user_id, email, email.split("@")[0], _hasher.hash(password),
                 _now()),
            )
        conn.execute(
            "INSERT OR IGNORE INTO user_roles (user_id, role_id, granted_at) "
            "VALUES (?, ?, ?)",
            (user_id, role_row["id"], _now()),
        )
    print(f"{'updated' if existing else 'created'} {email} as {role}")
    if settings.auth_mode == "disabled":
        print("NOTE: AUTH_MODE is 'disabled', so this user is not yet used "
              "for anything. Set AUTH_MODE=demo_required to enforce.")
    return 0


def grant(conn, role: str, document_id: str) -> int:
    role_row = conn.execute("SELECT id FROM roles WHERE name = ?",
                            (role,)).fetchone()
    if role_row is None:
        print(f"no such role: {role}", file=sys.stderr)
        return 2
    doc = conn.execute("SELECT id, filename FROM documents WHERE id = ?",
                       (document_id,)).fetchone()
    if doc is None:
        print(f"no such document: {document_id}", file=sys.stderr)
        return 2
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO document_role_access "
            "(document_id, role_id, granted_at) VALUES (?, ?, ?)",
            (document_id, role_row["id"], _now()),
        )
    print(f"granted {doc['filename']} to {role}")
    return 0


def verify(conn) -> int:
    """Report what is seeded but useless.

    A user with no roles logs in successfully and sees an empty corpus, which
    reads as a broken search rather than a missing grant. A role with no
    grants does the same to everyone in it.
    """
    problems = 0
    users = conn.execute(
        """SELECT u.email, u.is_active, COUNT(ur.role_id) AS roles
           FROM users u LEFT JOIN user_roles ur ON ur.user_id = u.id
           GROUP BY u.id ORDER BY u.email"""
    ).fetchall()
    roles = conn.execute(
        """SELECT r.name, COUNT(dra.document_id) AS grants
           FROM roles r
           LEFT JOIN document_role_access dra ON dra.role_id = r.id
           GROUP BY r.id ORDER BY r.name"""
    ).fetchall()
    documents = conn.execute("SELECT COUNT(*) AS n FROM documents").fetchone()["n"]

    print(f"{len(users)} user(s), {len(roles)} role(s), {documents} document(s)")
    for u in users:
        flags = []
        if not u["roles"]:
            flags.append("NO ROLES - will see an empty corpus")
            problems += 1
        if not u["is_active"]:
            flags.append("inactive")
        print(f"  {u['email']:32} {u['roles']} role(s) "
              f"{'  <- ' + '; '.join(flags) if flags else ''}")
    for r in roles:
        flag = ""
        if not r["grants"]:
            flag = "  <- NO DOCUMENT GRANTS - members will see nothing"
            problems += 1
        print(f"  role {r['name']:27} {r['grants']} grant(s){flag}")

    if not users:
        print("\nNo users. Under AUTH_MODE=demo_required nobody can sign in.")
        problems += 1
    print(f"\n{problems} problem(s)")
    return 1 if problems else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--roles", action="store_true", help="create the roles")
    ap.add_argument("--user", help="email address")
    ap.add_argument("--role", help="role to place the user in")
    ap.add_argument("--force", action="store_true",
                    help="replace an existing user's password")
    ap.add_argument("--grant", help="role to grant a document to")
    ap.add_argument("--document", help="document id to grant")
    ap.add_argument("--verify-only", action="store_true",
                    help="report users with no roles and roles with no grants")
    args = ap.parse_args()

    init_db()
    conn = connect()

    if args.verify_only:
        return verify(conn)
    if args.roles:
        return seed_roles(conn)
    if args.user:
        if not args.role:
            ap.error("--user needs --role")
        return seed_user(conn, args.user, args.role, args.force)
    if args.grant:
        if not args.document:
            ap.error("--grant needs --document")
        return grant(conn, args.grant, args.document)
    ap.print_help()
    return 2


raise SystemExit(main())
