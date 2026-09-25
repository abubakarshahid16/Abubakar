"""Mutations of `.githooks/pre-commit`."""

from __future__ import annotations

from ._base import REPO, Mutation


MUTATIONS: tuple[Mutation, ...] = (
    # ---- from B5_STANDARDS_INVENTORY --------------------------------------
    #: B5 part 2: standard family, licence status, cover-page backfill, and the
    #: "cited by a submittal" flag on the inventory.
    Mutation(
        id="M541", phase=61,
        description="the hook stops reading the local identifier list, so a "
                    "staged client identifier is committed",
        path=REPO / ".githooks" / "pre-commit",
        anchor='    client_ids="${client_ids:+$client_ids|}$pattern"\n',
        replacement="    :\n",
        target="tests/test_client_identifier_hook.py",
        keyword="added_line_matching_a_local_pattern_is_blocked",
        tags=("privacy", "safety"),
    ),
    Mutation(
        id="M542", phase=61,
        description="the hook reads the list but never matches added lines "
                    "against it",
        path=REPO / ".githooks" / "pre-commit",
        anchor='      | grep -E -- "$client_ids" || true)\n',
        replacement="      | grep -E -- 'a^' || true)\n",
        target="tests/test_client_identifier_hook.py",
        keyword="added_line_matching_a_local_pattern_is_blocked",
        tags=("privacy", "safety"),
    ),
    Mutation(
        id="M543", phase=61,
        description="a missing local list blocks every commit instead of "
                    "printing a notice",
        path=REPO / ".githooks" / "pre-commit",
        anchor='  echo "${YLW}notice: no .githooks/client-identifiers.local patterns - client identifier scan skipped${NC}"\n',
        replacement='  echo "${RED}BLOCKED: no client identifier list${NC}"; fail=1\n',
        target="tests/test_client_identifier_hook.py",
        keyword="missing_list_is_a_notice_not_a_block",
        tags=("safety",),
    ),
)
