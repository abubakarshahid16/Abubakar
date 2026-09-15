"""Create roles, users and document grants for AUTH_MODE=demo_required.

Nothing here has a default password, and there is no demo credential in this
repository to leak into production. That is a stronger guarantee than any scan
for one: a password can only ever arrive by being typed, interactively, twice.

    python scripts/seed_access.py --roles
    python scripts/seed_access.py --user ali@example.com --role "Civil Engineering"
    python scripts/seed_access.py --user ali@example.com --role "Civil Engineering" --force
    python scripts/seed_access.py --user ali@example.com --role IT --role admin
    python scripts/seed_access.py --grant "Civil Engineering" --document doc_ab12cd34
    python scripts/seed_access.py --verify-only

`--verify-only` reports users with no discipline and disciplines with no grants,
because "seeded but useless" is a state you want to discover before a demo
rather than during one: such a user logs in successfully and then sees an empty
corpus, which looks like a broken search rather than a missing grant.

THE MODEL. There are four disciplines - Civil Engineering, Mechanical,
Chemical-Process, IT - and `admin` is a CAPABILITY, not a fifth discipline. An
administrator also works somewhere; an IT administrator is IT *and* admin.
Modelling admin as a discipline forces a false choice and means an admin cannot
see their own documents. See `docs/design-admin-screen.md`. `--role` may
therefore be given more than once, and the natural seeding of an administrator
is one discipline plus the capability.
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

#: The four engineering disciplines the demonstration dataset needs
#: (RAG-INTELLIGENCE-POC-EXECUTION.md sec.1) plus the one capability. A role is a
#: name, a kind and a description; everything else is a grant, and grants are
#: per document.
#:
#: `kind` is what makes admin-as-capability a property of the data rather than
#: a convention held in this file: any caller can split disciplines from
#: capabilities with a WHERE clause instead of importing this constant.
DISCIPLINE = "discipline"
CAPABILITY = "capability"

ROLES = {
    "Civil Engineering": (DISCIPLINE, "Civil engineering documents"),
    "Mechanical": (DISCIPLINE, "Mechanical engineering documents"),
    "Chemical-Process": (DISCIPLINE, "Chemical and process engineering documents"),
    "IT": (DISCIPLINE, "IT and information-security documents"),
    # NOT a fifth discipline. Orthogonal to all four: an administrator holds
    # this AND the discipline they work in.
    "admin": (CAPABILITY, "Administer users, roles and grants"),
}

DISCIPLINES = [n for n, (k, _d) in ROLES.items() if k == DISCIPLINE]

MIN_PASSWORD = 12

#: Rejected outright, whatever else the password contains. Not a strength
#: meter - a list of the passwords that actually get typed at a demo.
FORBIDDEN = {
    "password", "passw0rd", "demo", "demo1234", "changeme",
    "letmein", "welcome", "12345678", "qwerty", "admin",
    #: Product names, current and former. A product name is the password people
    #: actually type at a demo, so the new one is blocked from the start. The
    #: two former names STAY blocked: everyone who worked on this build still
    #: has them in their fingers, which makes them a better guess after the
    #: rename, not a worse one. This list is a blocklist of guessable strings,
    #: not branding - do not "finish the rename" by deleting them.
    "ragintel", "ragintelligence", "rag", "ragintelligencesystem",
    "nabaa", "aramco",
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

    There is no flag for this on purpose: a secret given on a command line
    lands in shell history and is visible in `ps` to every other user on the
    machine. Not an environment variable and not a file either.
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
    """Additive and idempotent. Never deletes a role.

    A role that already exists keeps its id, and with it every grant and every
    membership hanging off that id. The one thing that is corrected in place is
    `kind`, because a database seeded before the four disciplines existed has
    `admin` sitting in the same undifferentiated pool as everyone else.
    """
    made = corrected = 0
    with conn:
        for name, (kind, description) in ROLES.items():
            row = conn.execute(
                "SELECT id, kind FROM roles WHERE name = ?", (name,)).fetchone()
            if row:
                if row["kind"] != kind:
                    conn.execute("UPDATE roles SET kind = ? WHERE id = ?",
                                 (kind, row["id"]))
                    corrected += 1
                continue
            conn.execute(
                "INSERT INTO roles (id, name, description, kind, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (f"role_{secrets.token_hex(6)}", name, description, kind, _now()),
            )
            made += 1
    print(f"roles: {made} created, {len(ROLES) - made} already present"
          + (f", {corrected} kind corrected" if corrected else ""))
    print(f"  disciplines: {', '.join(DISCIPLINES)}")
    print("  capability:  admin (held alongside a discipline, never instead of one)")
    return 0


def _role_row(conn, role: str):
    """Case-insensitive so `--role it` finds `IT` at 22:40 the night before."""
    return conn.execute(
        "SELECT id, name, kind FROM roles WHERE lower(name) = lower(?)",
        (role,)).fetchone()


def seed_user(conn, email: str, roles: list[str], force: bool) -> int:
    from app.auth import _hasher
    from app.config import settings

    email = email.strip().lower()
    role_rows = []
    for role in roles:
        row = _role_row(conn, role)
        if row is None:
            known = ", ".join(sorted(ROLES))
            print(f"no such role: {role}. Run --roles first. Known: {known}",
                  file=sys.stderr)
            return 2
        role_rows.append(row)

    if all(r["kind"] == CAPABILITY for r in role_rows):
        # The exact "seeded but useless" state --verify-only exists to catch,
        # caught one step earlier, at the point it would be created. Refused
        # BEFORE any prompt, so nobody is asked for a secret about to be
        # thrown away.
        print("refusing: every role given is a capability, so this user would "
              "have no discipline and would sign in to an empty corpus. "
              f"Add one of: {', '.join(DISCIPLINES)}", file=sys.stderr)
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
        for row in role_rows:
            conn.execute(
                "INSERT OR IGNORE INTO user_roles (user_id, role_id, granted_at) "
                "VALUES (?, ?, ?)",
                (user_id, row["id"], _now()),
            )
    names = ", ".join(r["name"] for r in role_rows)
    print(f"{'updated' if existing else 'created'} {email} as {names}")
    if settings.auth_mode == "disabled":
        print("NOTE: AUTH_MODE is 'disabled', so this user is not yet used "
              "for anything. Set AUTH_MODE=demo_required to enforce.")
    return 0


def grant(conn, role: str, document_id: str) -> int:
    role_row = _role_row(conn, role)
    if role_row is None:
        print(f"no such role: {role}", file=sys.stderr)
        return 2
    if role_row["kind"] == CAPABILITY:
        # ALLOWED, and the refusal that used to stand here was wrong on the
        # facts. It said a grant to a capability "is silently useless: nobody
        # holds `admin` *as* their discipline, so the document reaches no one
        # through it while looking, in the tables, granted."
        #
        # That assumed a filter `access.scope_for_user` does not have. It joins
        # user_roles to document_role_access on role_id and never looks at
        # `kind`, so a document granted to the admin capability reaches every
        # user holding it. Measured: granting one document to `admin` took the
        # administrator's scope from 6 documents to 7.
        #
        # It is the honest way to give an administrator corpus-wide READ
        # access, which the execution plan (line 1001) makes an explicit choice
        # rather than a default: "Administrator status grants management UI/API
        # permission but does not automatically grant the right to read every
        # confidential document." Granting it here puts that decision in the
        # grant tables, where `--verify-only` shows it and a single DELETE
        # revokes it, instead of in a branch of access.py that no query can
        # see.
        print(f"note: {role_row['name']} is a capability, not a discipline. "
              f"This grants the document to everyone holding it.",
              file=sys.stderr)
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
    print(f"granted {doc['filename']} to {role_row['name']}")
    return 0


def verify(conn) -> int:
    """Report what is seeded but useless.

    A user with no DISCIPLINE logs in successfully and sees an empty corpus,
    which reads as a broken search rather than a missing grant. A discipline
    with no grants does the same to everyone in it.

    A capability with no document grants is NOT a problem and must not be
    reported as one: `admin` is not how anybody reaches a document, and a check
    that cries wolf about it is a check people learn to skip.
    """
    problems = 0
    users = conn.execute(
        """SELECT u.email, u.is_active,
                  COUNT(ur.role_id) AS roles,
                  SUM(CASE WHEN r.kind = 'discipline' THEN 1 ELSE 0 END) AS disciplines,
                  SUM(CASE WHEN r.kind = 'capability' THEN 1 ELSE 0 END) AS capabilities
           FROM users u
           LEFT JOIN user_roles ur ON ur.user_id = u.id
           LEFT JOIN roles r ON r.id = ur.role_id
           GROUP BY u.id ORDER BY u.email"""
    ).fetchall()
    roles = conn.execute(
        """SELECT r.name, r.kind, COUNT(dra.document_id) AS grants,
                  (SELECT COUNT(*) FROM user_roles ur WHERE ur.role_id = r.id) AS members
           FROM roles r
           LEFT JOIN document_role_access dra ON dra.role_id = r.id
           GROUP BY r.id ORDER BY r.kind DESC, r.name"""
    ).fetchall()
    documents = conn.execute("SELECT COUNT(*) AS n FROM documents").fetchone()["n"]

    seeded = {r["name"] for r in roles}
    missing = [n for n in ROLES if n not in seeded]
    unseen = sorted(n for n in seeded if n not in ROLES)

    print(f"{len(users)} user(s), {len(roles)} role(s), {documents} document(s)")
    for u in users:
        flags = []
        if not (u["disciplines"] or 0):
            if u["capabilities"]:
                flags.append("NO DISCIPLINE (admin only) - will see an empty corpus")
            else:
                flags.append("NO ROLES - will see an empty corpus")
            problems += 1
        if not u["is_active"]:
            flags.append("inactive")
        print(f"  {u['email']:32} {u['disciplines'] or 0} discipline(s), "
              f"{u['capabilities'] or 0} capability(ies)"
              f"{'  <- ' + '; '.join(flags) if flags else ''}")
    for r in roles:
        flag = ""
        if r["kind"] == DISCIPLINE and not r["grants"]:
            flag = "  <- NO DOCUMENT GRANTS - members will see nothing"
            problems += 1
        label = f"{r['kind']} {r['name']}"
        print(f"  {label:36} {r['grants']} grant(s), {r['members']} member(s){flag}")

    if missing:
        print(f"\nNot seeded yet: {', '.join(missing)}. Run --roles.")
        problems += 1
    if unseen:
        # Reported, never deleted: dropping a role would cascade away its
        # grants and its members, which is a data loss no seeding script
        # should be able to cause.
        print(f"\nRoles in the database that are not in the seed set: "
              f"{', '.join(unseen)}. Left alone - deleting one would cascade "
              f"away its grants and members.")
    if not users:
        print("\nNo users. Under AUTH_MODE=demo_required nobody can sign in.")
        problems += 1
    print(f"\n{problems} problem(s)")
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--roles", action="store_true", help="create the roles")
    ap.add_argument("--user", help="email address")
    ap.add_argument("--role", action="append", default=None,
                    help="role to place the user in; repeat for several, e.g. "
                         "--role IT --role admin")
    ap.add_argument("--force", action="store_true",
                    help="replace an existing user's password")
    ap.add_argument("--grant", help="discipline to grant a document to")
    ap.add_argument("--document", help="document id to grant")
    ap.add_argument("--verify-only", action="store_true",
                    help="report users with no discipline and disciplines "
                         "with no grants")
    args = ap.parse_args(argv)

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


# `raise SystemExit(main())`, as fetch_models.py does it - but guarded, because
# an unguarded one makes every function above unimportable and therefore
# untestable, and this is the script that decides who can see what. Running the
# file is unchanged.
if __name__ == "__main__":
    raise SystemExit(main())
