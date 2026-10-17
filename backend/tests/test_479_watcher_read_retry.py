"""#479 item 1: a drop-folder file that cannot be read is tried again.

WHAT WAS WRONG. One failed read (a file locked by whoever is still copying it
in) marked the file handled; it was never looked at again until its size or
mtime changed, so a file that unlocked a minute later was silently never
ingested.

NOW. Up to `READ_ATTEMPTS` reads of the unchanged file on separate scans,
counted as `retrying` with no failure event; only the last failed read writes
the FAILED event, which says how many tries it made.
"""
from __future__ import annotations

import pytest

from app import watcher as watcher_mod
from tests.test_watch_folder import drop_folder, events, pdf_bytes, temp_storage  # noqa: F401


@pytest.fixture
def locked(monkeypatch):
    """`hash_file` fails while `state["locked"]` is true."""
    real = watcher_mod.hash_file
    state = {"locked": True, "reads": 0}

    def hash_file(path):
        state["reads"] += 1
        if state["locked"]:
            raise PermissionError("locked")
        return real(path)

    monkeypatch.setattr(watcher_mod, "hash_file", hash_file)
    return state


def _stable(folder, name="spec.pdf"):
    path = folder / name
    path.write_bytes(pdf_bytes())
    first = watcher_mod.scan_once()          # seen once: not yet stable
    assert first["unstable"] == [name]
    return path


def test_a_file_unlocked_before_the_last_try_is_ingested(drop_folder, locked):  # noqa: F811
    _stable(drop_folder)
    assert watcher_mod.scan_once()[watcher_mod.RETRYING] == ["spec.pdf"]
    assert events() == [], "a retry is not a failure and leaves no event"
    locked["locked"] = False
    result = watcher_mod.scan_once()
    assert result[watcher_mod.INGESTED] == ["spec.pdf"]
    assert events(watcher_mod.FAILED) == []


def test_it_gives_up_after_the_bound_and_says_so(drop_folder, locked):  # noqa: F811
    _stable(drop_folder)
    outcomes = [watcher_mod.scan_once() for _ in range(watcher_mod.READ_ATTEMPTS)]
    for result in outcomes[:-1]:
        assert result[watcher_mod.RETRYING] == ["spec.pdf"]
    assert outcomes[-1][watcher_mod.FAILED] == ["spec.pdf"]
    assert locked["reads"] == watcher_mod.READ_ATTEMPTS
    (failed,) = events(watcher_mod.FAILED)
    assert f"in {watcher_mod.READ_ATTEMPTS} tries" in failed["detail"]
    assert "PermissionError" in failed["detail"]

    # handled now: no fourth read, no second event
    assert watcher_mod.scan_once()["already_handled"] == ["spec.pdf"]
    assert locked["reads"] == watcher_mod.READ_ATTEMPTS
    assert len(events(watcher_mod.FAILED)) == 1


def test_a_changed_file_starts_its_tries_again(drop_folder, locked):  # noqa: F811
    path = _stable(drop_folder)
    for _ in range(watcher_mod.READ_ATTEMPTS):
        watcher_mod.scan_once()
    assert len(events(watcher_mod.FAILED)) == 1
    path.write_bytes(pdf_bytes(b"z" * 6000))           # replaced by its writer
    locked["locked"] = False
    watcher_mod.scan_once()                            # changed: unstable again
    assert watcher_mod.scan_once()[watcher_mod.INGESTED] == ["spec.pdf"]
