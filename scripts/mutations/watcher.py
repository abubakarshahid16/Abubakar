"""Mutations of `backend/app/watcher.py`."""

from __future__ import annotations

from ._base import APP, Mutation


MUTATIONS: tuple[Mutation, ...] = (
    # ---- from ROLES_FIX ---------------------------------------------------
    #: Document roles: the watched folder's subfolder convention, and the bulk
    #: assignment endpoint. Not a phase - a contained fix between phases 5B and 6.
    #:
    #: M73 IS THE ONE THAT MATTERS. Every other mutation here breaks something a
    #: user would notice. M73 makes the watcher guess a role from the filename,
    #: which on this corpus is right 272 times out of 280 and would look like an
    #: improvement in a diff.
    Mutation(
        id="M73", phase=8,
        description="guess the role from the filename instead of the subfolder",
        path=APP / "watcher.py",
        # PATCHED ABOVE THE `len(parts) != 1` GUARD, not below it. The first
        # version of this mutation replaced the final return, which a file in
        # the ROOT never reaches - so it changed nothing for the only case the
        # test is about and reported NOT DETECTED against a test that was
        # standing exactly where it should. A mutation that cannot reach the
        # code path is a broken mutation, not a vacuous test, and the harness
        # saying so is the harness working.
        anchor="    parts = relative.parts",
        replacement='    if path.name.upper().startswith("SAES-"):\n'
                    '        return "COMPANY_STANDARD"\n'
                    "    parts = relative.parts",
        target="tests/test_document_roles.py",
        keyword="root_gets_no_role_even_when_it_looks_like_a_standard",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M74", phase=8,
        description="ingest from a role subfolder without applying the role",
        path=APP / "watcher.py",
        anchor="        tagged = self._apply_role(row[\"id\"], role, path.name, source, sha256,\n"
               "                                  only_if_unset=False)",
        replacement="        tagged = False",
        target="tests/test_document_roles.py",
        keyword="dropped_in_standards_is_ingested_as_a_company_standard",
    ),
    Mutation(
        id="M75", phase=8,
        description="skip the role on a duplicate, so an already-ingested "
                    "library can never be tagged by moving it",
        path=APP / "watcher.py",
        anchor='            tagged = self._apply_role(existing["id"], role, path.name, source, sha256)',
        replacement="            tagged = False",
        target="tests/test_document_roles.py",
        keyword="duplicate_dropped_into_standards_tags_the_document",
        tags=("critical",),
    ),
    Mutation(
        id="M76", phase=8,
        description="let a file in a folder overwrite a role a person set",
        path=APP / "watcher.py",
        anchor="source: str, sha256: str, *, only_if_unset: bool = True) -> bool:",
        replacement="source: str, sha256: str, *, only_if_unset: bool = False) -> bool:",
        target="tests/test_document_roles.py",
        keyword="never_overwrites_a_role_a_person_already_set",
        tags=("honesty",),
    ),
    Mutation(
        id="M77", phase=8,
        description="key watched files by bare filename again, so the same "
                    "name in two subfolders collides",
        path=APP / "watcher.py",
        anchor="        return path.resolve().relative_to(folder.resolve()).as_posix()",
        replacement="        return path.name",
        target="tests/test_document_roles.py",
        keyword="same_filename_in_two_subfolders",
    ),
)
