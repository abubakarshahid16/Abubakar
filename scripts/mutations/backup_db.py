"""Mutations of `scripts/backup_db.py`."""

from __future__ import annotations

from ._base import REPO, Mutation


MUTATIONS: tuple[Mutation, ...] = (
    # ---- from BACKUP ------------------------------------------------------
    #: The WAL-safe backup: every way it used to succeed on the wrong contents.
    #: THE GUARDS COME IN REDUNDANT PAIRS - an existence check AND a read-only
    #: open; microseconds in the name AND an exclusive create. Deleting one half
    #: of a pair is not observable (audit entry 39), so each mutation below
    #: removes a whole guard, or removes one half to prove the other half turns
    #: a silent failure into a loud one.
    Mutation(
        id="M244", phase=23,
        description="BACK UP A MISTYPED PATH: drop the existence check AND "
                    "the read-only open, so sqlite creates an empty database "
                    "at the typo and verify calls it ok",
        path=REPO / "scripts" / "backup_db.py",
        # Re-anchored by B41: the destination check now sits between the
        # existence check and the read-only open, so the anchor spans it.
        # The replacement still restores BOTH halves of the original defect -
        # no existence check, and a writable connect that CREATES the typo.
        anchor="    if not source.is_file():\n"
               '        raise FileNotFoundError(f"no database at {live_path}")\n'
               "    # BEFORE the source is opened, so a refused backup leaves no handle and\n"
               "    # no connection behind.\n"
               "    destination = pathlib.Path(backup_dir)\n"
               "    if not destination.is_dir():\n"
               "        raise FileNotFoundError(\n"
               '            f"no backup directory at {backup_dir}: create it first, or pass "\n'
               '            "one that exists - this tool does not create it for you")\n'
               '    src = sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)',
        replacement="    destination = pathlib.Path(backup_dir)\n"
                    "    src = sqlite3.connect(live_path)",
        target="tests/test_backup_db.py",
        keyword="missing_source_is_refused_rather_than_created",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M245", phase=23,
        description="back up a database with NO TABLES and report it verified",
        path=REPO / "scripts" / "backup_db.py",
        anchor="    if tables == 0:",
        replacement="    if False:",
        target="tests/test_backup_db.py",
        keyword="source_with_no_tables_is_refused",
        tags=("honesty",),
    ),
    # M246 and M247 were re-anchored by B30. M246 used to drop the microseconds
    # and expect the exclusive create to make the tie a LOUD failure - the very
    # crash B30 removes, so it would now read NOT DETECTED against correct
    # code. Both now mutate `_reserve_name`, and the clock tie is forced by a
    # frozen clock instead of hoped for.
    Mutation(
        id="M246", phase=23,
        description="PUT B30 BACK: a clock tie raises FileExistsError instead "
                    "of taking the next free name",
        path=REPO / "scripts" / "backup_db.py",
        anchor="        except FileExistsError:\n            continue",
        replacement="        except FileExistsError:\n            raise",
        target="tests/test_backup_db.py",
        keyword="clock_tie",
    ),
    Mutation(
        id="M247", phase=23,
        description="SILENTLY OVERWRITE THE EARLIER BACKUP: open the name for "
                    "writing instead of creating it exclusively",
        path=REPO / "scripts" / "backup_db.py",
        anchor='            with open(candidate, "xb"):',
        replacement='            with open(candidate, "wb"):',
        target="tests/test_backup_db.py",
        keyword="clock_tie or never_written_over",
        tags=("critical",),
    ),
    Mutation(
        id="M337", phase=23,
        description="B41: stop checking the destination, so a safety backup "
                    "dies inside _reserve_name naming a file nobody asked for",
        path=REPO / "scripts" / "backup_db.py",
        anchor="    if not destination.is_dir():",
        replacement="    if False:",
        target="tests/test_backup_db.py",
        keyword="does_not_exist or before_the_source",
    ),
    Mutation(
        id="M303", phase=23,
        description="B30: the retry tries the SAME name every time, so a tie "
                    "still fails after a hundred attempts",
        path=REPO / "scripts" / "backup_db.py",
        anchor='        suffix = f"-{attempt}" if attempt else ""',
        replacement='        suffix = ""',
        target="tests/test_backup_db.py",
        keyword="clock_tie",
    ),
    Mutation(
        id="M304", phase=23,
        description="B30: with every name taken, hand back a taken one and let "
                    "sqlite write over it instead of failing loudly",
        path=REPO / "scripts" / "backup_db.py",
        anchor="    raise FileExistsError(\n"
               '        f"no free backup name for stamp {stamp} in {backup_dir} "',
        replacement="    return candidate\n    raise FileExistsError(\n"
                    '        f"no free backup name for stamp {stamp} in {backup_dir} "',
        target="tests/test_backup_db.py",
        keyword="running_out_of_names",
        tags=("critical",),
    ),
)
