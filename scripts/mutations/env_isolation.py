"""Mutations of `backend/tests/env_isolation.py` and the conftest that uses it.

The suite must never run on the developer's egress switches, keys, proxy or
data paths (honesty audit entry 77: real paid Anthropic calls from the suite
on the owner's laptop). Each entry deletes one part of that isolation.
"""

from __future__ import annotations

from ._base import BACKEND, Mutation

_ISO = BACKEND / "tests" / "env_isolation.py"
_CONFTEST = BACKEND / "tests" / "conftest.py"
_TARGET = "tests/test_env_isolation.py"


MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1350", phase=97,
        description="conftest no longer isolates settings at import, so the "
                    "developer's .env and environment reach every test",
        path=_CONFTEST,
        anchor="_REMOVED_ENV = env_isolation.isolate(settings)",
        replacement="_REMOVED_ENV = []",
        target=_TARGET,
        keyword="real_conftest or live_session",
        tags=("safety", "egress"),
    ),
    Mutation(
        id="M1351", phase=97,
        description="keep reading the env file, so a fresh Settings() in a "
                    "test still sees backend/.env",
        path=_ISO,
        anchor='    Settings.model_config["env_file"] = None\n',
        replacement="",
        target=_TARGET,
        keyword="isolate_closes or live_session",
        tags=("safety", "egress"),
    ),
    Mutation(
        id="M1352", phase=97,
        description="leave the egress variables in os.environ, where "
                    "reader_api and claude_unavailable read them directly",
        path=_ISO,
        anchor="            del env[name]\n            removed.append(name)",
        replacement="            pass",
        target=_TARGET,
        keyword="isolate_closes or real_conftest",
        tags=("safety", "egress"),
    ),
    Mutation(
        id="M1353", phase=97,
        description="build clean settings but never copy them onto the live "
                    "singleton",
        path=_ISO,
        anchor="    for name in Settings.model_fields:\n"
               "        setattr(target, name, getattr(clean, name))",
        replacement="    for name in ():\n"
                    "        setattr(target, name, getattr(clean, name))",
        target=_TARGET,
        keyword="isolate_closes or real_conftest",
        tags=("safety", "egress"),
    ),
    Mutation(
        id="M1354", phase=97,
        description="leave the Claude spend ledger at backend/data, so a test "
                    "reads and writes the owner's real USD ledger",
        path=_CONFTEST,
        anchor='    settings.claude_spend_log = session_dir / "claude_spend.jsonl"\n',
        replacement="",
        target=_TARGET,
        keyword="live_session",
        tags=("safety", "spend"),
    ),
    Mutation(
        id="M1355", phase=97,
        description="network guard lets a non-loopback connect through",
        path=_ISO,
        anchor="            if not _loopback_host(host):\n",
        replacement="            if False:\n",
        target=_TARGET,
        keyword="non_loopback_connect or swallows_the_refusal",
        tags=("safety", "egress"),
    ),
    Mutation(
        id="M1356", phase=97,
        description="network guard lets a DNS lookup of a real name through",
        path=_ISO,
        anchor="        if not (_loopback_host(host) or _ip_literal(host)):\n",
        replacement="        if False:\n",
        target=_TARGET,
        keyword="dns_lookup",
        tags=("safety", "egress"),
    ),
    Mutation(
        id="M1357", phase=97,
        description="a test that swallows the guard's OSError is no longer "
                    "failed by name",
        path=_CONFTEST,
        anchor='        pytest.fail("this test tried to leave the machine: " + "; ".join(attempts))',
        replacement="        pass",
        target=_TARGET,
        keyword="swallows_the_refusal",
        tags=("safety", "egress"),
    ),
    Mutation(
        id="M1358", phase=97,
        description="leave HTTP(S)_PROXY set, so a loopback proxy can carry a "
                    "request past the loopback-only guard",
        path=_ISO,
        anchor="    for name in removed:\n        del env[name]\n",
        replacement="    removed = []\n",
        target=_TARGET,
        keyword="real_conftest",
        tags=("safety", "egress"),
    ),
    Mutation(
        id="M1359", phase=97,
        description="the safety check reports nothing unsafe, whatever the "
                    "settings hold",
        path=_ISO,
        anchor="    return sorted(n for n, safe in EGRESS_SAFE.items()\n"
               "                  if (getattr(target, n) not in safe if isinstance(safe, OneOf)\n"
               "                      else getattr(target, n) != safe))",
        replacement="    return []",
        target=_TARGET,
        keyword="hostile_machine_really or real_conftest",
        tags=("safety", "egress"),
    ),
)
