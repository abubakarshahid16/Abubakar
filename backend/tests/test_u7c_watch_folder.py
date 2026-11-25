"""Update 7, builder C (review of update 6a, M1): a configured folder never moves. A missing absolute watch folder (an unmounted
share) stays missing; it is never swapped for a folder of the app's own data directory that only shares its last name.
A stored FILE written on another machine still finds its tail. Invented paths only."""

from __future__ import annotations

from app import stored_paths
from app.config import settings


def test_a_missing_absolute_folder_is_not_swapped_for_a_data_folder_of_the_same_name(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    (tmp_path / "uploads").mkdir()
    missing = "/no-such-share/invented/uploads"
    assert stored_paths.local(missing, directory=True) == missing


def test_a_relative_folder_is_read_whole_under_the_data_directory(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    assert stored_paths.local("inbox/watched", directory=True) == str(
        tmp_path / "inbox" / "watched"
    )


def test_a_stored_file_from_another_machine_still_finds_its_tail(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    (tmp_path / "uploads").mkdir()
    (tmp_path / "uploads" / "a.pdf").write_bytes(b"%PDF-1.7")
    assert stored_paths.local("/other-machine/data/uploads/a.pdf") == str(
        tmp_path / "uploads" / "a.pdf"
    )
