"""#475: the whole data folder is backed up, restored into an empty folder
and drilled, kept by retention, and copied to another disk. Invented files
only; no live data folder is touched."""
import json
import pathlib
import sqlite3
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "scripts"))
import backup_data
from backup_data import BackupError, backup, drill, offdisk, prune, restore


def _data_folder(tmp_path: pathlib.Path) -> tuple[pathlib.Path, sqlite3.Connection]:
    """A made-up data folder: a WAL database with rows still in its -wal, a
    second database, an upload, a nested report and a lock file."""
    data = tmp_path / "src" / "data"
    (data / "uploads").mkdir(parents=True)
    (data / "reports" / "2026").mkdir(parents=True)
    conn = sqlite3.connect(data / "rag_intelligence.sqlite")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE documents (id INTEGER)")
    conn.executemany("INSERT INTO documents VALUES (?)", [(i,) for i in range(12)])
    conn.commit()                     # committed, still living in the -wal
    assert (data / "rag_intelligence.sqlite-wal").exists()
    vec = sqlite3.connect(data / "vector_index.sqlite")
    vec.execute("CREATE TABLE vectors (id INTEGER)")
    vec.executemany("INSERT INTO vectors VALUES (?)", [(i,) for i in range(5)])
    vec.commit()
    vec.close()
    (data / "uploads" / "SAMPLE-sheet.pdf").write_bytes(b"%PDF-1.4 invented")
    (data / "reports" / "2026" / "r1.json").write_text('{"n": 1}', encoding="utf-8")
    (data / ".heavy-job.lock").write_text("owner", encoding="utf-8")
    # the open connection keeps the -wal in place while the backup runs
    return data, conn


@pytest.fixture
def world(tmp_path):
    data, conn = _data_folder(tmp_path)
    root = tmp_path / "backups"
    root.mkdir()
    yield data, root
    conn.close()


def test_the_whole_folder_is_backed_up_with_the_wal_rows_and_no_sidecars(world):
    data, root = world
    made = backup(data, root)
    manifest = json.loads((made / "MANIFEST.json").read_text(encoding="utf-8"))
    paths = {f["path"] for f in manifest["files"]}
    assert paths == {"rag_intelligence.sqlite", "vector_index.sqlite",
                     "uploads/SAMPLE-sheet.pdf", "reports/2026/r1.json"}
    assert manifest["databases"]["rag_intelligence.sqlite"] == {"documents": 12}
    assert not list(made.rglob("*-wal")) and not list(made.rglob("*.lock"))
    assert drill(made) == {"files": 4, "databases": 2, "documents": 12}


def test_restore_into_an_empty_folder_passes_the_drill_and_counts_match(world, tmp_path):
    data, root = world
    made = backup(data, root)
    result = restore(made, tmp_path / "restored")
    assert result["documents"] == 12
    back = sqlite3.connect(tmp_path / "restored" / "rag_intelligence.sqlite")
    assert back.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 12
    back.close()
    assert (tmp_path / "restored" / "uploads" / "SAMPLE-sheet.pdf").read_bytes() == b"%PDF-1.4 invented"


def test_restore_refuses_a_folder_with_anything_in_it_and_a_live_data_folder(world, tmp_path):
    data, root = world
    made = backup(data, root)
    busy = tmp_path / "busy"
    busy.mkdir()
    (busy / "keep.txt").write_text("x", encoding="utf-8")
    with pytest.raises(BackupError, match="not empty"):
        restore(made, busy)
    with pytest.raises(BackupError, match="live data folder"):
        restore(made, tmp_path / "checkout" / "backend" / "data")
    assert not (tmp_path / "checkout").exists()


@pytest.mark.parametrize("damage", ["edit", "delete", "extra", "rows"])
def test_the_drill_names_a_damaged_backup_never_a_silent_pass(world, damage):
    data, root = world
    made = backup(data, root)
    if damage == "edit":
        (made / "uploads" / "SAMPLE-sheet.pdf").write_bytes(b"%PDF-1.4 changed")
        expected = "sha256"
    elif damage == "delete":
        (made / "reports" / "2026" / "r1.json").unlink()
        expected = "missing"
    elif damage == "extra":
        (made / "stray.txt").write_text("x", encoding="utf-8")
        expected = "not in the manifest"
    else:
        manifest = json.loads((made / "MANIFEST.json").read_text(encoding="utf-8"))
        manifest["databases"]["rag_intelligence.sqlite"]["documents"] = 13
        with pytest.raises(BackupError, match="row counts differ"):
            drill(made, manifest)
        return
    with pytest.raises(BackupError, match=expected):
        drill(made)


def test_an_unreadable_manifest_is_named_not_a_traceback(tmp_path):
    folder = tmp_path / "data-20261017-000000-000000"
    folder.mkdir()
    (folder / "MANIFEST.json").write_text("not json", encoding="utf-8")
    with pytest.raises(BackupError, match="not readable JSON"):
        drill(folder)


def test_a_folder_without_a_manifest_is_not_a_backup(tmp_path):
    (tmp_path / "data-20261017-000000-000000").mkdir()
    with pytest.raises(BackupError, match="no MANIFEST"):
        drill(tmp_path / "data-20261017-000000-000000")


def test_backup_refuses_a_missing_source_or_destination_and_a_root_inside_the_data(world, tmp_path):
    data, root = world
    with pytest.raises(BackupError, match="no data folder"):
        backup(tmp_path / "nope", root)
    with pytest.raises(BackupError, match="no backup folder"):
        backup(data, tmp_path / "missing")
    inside = data / "backups"
    inside.mkdir()
    with pytest.raises(BackupError, match="inside the data folder"):
        backup(data, inside)


def _fake(root: pathlib.Path, stamp: str) -> pathlib.Path:
    folder = root / f"data-{stamp}"
    folder.mkdir()
    (folder / "MANIFEST.json").write_text(json.dumps({"format": 1, "files": [], "databases": {}}),
                                          encoding="utf-8")
    return folder


def test_retention_keeps_the_newest_days_and_one_per_month(tmp_path):
    stamps = ["20260801-010000-000000", "20260815-010000-000000", "20260901-010000-000000",
              "20261001-010000-000000", "20261010-010000-000000", "20261015-010000-000000",
              "20261016-010000-000000", "20261017-010000-000000"]
    for s in stamps:
        _fake(tmp_path, s)
    (tmp_path / "data-not-a-stamp").mkdir()          # not this tool's: never touched
    (tmp_path / "data-20250101-000000-000000").mkdir()  # no manifest: never touched
    deleted = prune(tmp_path, keep_daily=3, keep_monthly=2)
    left = sorted(p.name for p in tmp_path.iterdir())
    # kept: the newest 3, and the newest of each of the last 2 months
    # (October's is already among the 3; September's is 0901)
    assert sorted(d.name for d in deleted) == [
        "data-20260801-010000-000000", "data-20260815-010000-000000",
        "data-20261001-010000-000000", "data-20261010-010000-000000"]
    assert left == ["data-20250101-000000-000000", "data-20260901-010000-000000",
                    "data-20261015-010000-000000", "data-20261016-010000-000000",
                    "data-20261017-010000-000000", "data-not-a-stamp"]


def test_retention_keeps_one_per_month_back_to_the_limit(tmp_path):
    for s in ["20260801-010000-000000", "20260815-010000-000000", "20260901-010000-000000",
              "20261017-010000-000000"]:
        _fake(tmp_path, s)
    prune(tmp_path, keep_daily=1, keep_monthly=3)
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "data-20260815-010000-000000", "data-20260901-010000-000000", "data-20261017-010000-000000"]
    with pytest.raises(BackupError, match="keep at least one"):
        prune(tmp_path, keep_daily=0)


@pytest.mark.parametrize("manifest", ['{"format": 2, "files": [], "databases": {}}', "not json"])
def test_retention_never_deletes_a_backup_whose_manifest_it_cannot_read(tmp_path, manifest):
    old = tmp_path / "data-20200101-000000-000000"
    old.mkdir()
    (old / "MANIFEST.json").write_text(manifest, encoding="utf-8")
    _fake(tmp_path, "20261017-010000-000000")
    assert prune(tmp_path, keep_daily=1, keep_monthly=0) == []
    assert old.is_dir()


def test_the_off_disk_copy_refuses_the_same_disk_and_drills_the_copy(world, tmp_path, monkeypatch):
    data, root = world
    made = backup(data, root)
    other = tmp_path / "other-disk"
    other.mkdir()
    with pytest.raises(BackupError, match="same disk"):
        offdisk(made, other)
    devices = {other.resolve(): 2}
    monkeypatch.setattr(backup_data, "_device", lambda p: devices.get(pathlib.Path(p).resolve(), 1))
    copy = offdisk(made, other)
    assert drill(copy)["documents"] == 12
    with pytest.raises(BackupError, match="already exists"):
        offdisk(made, other)


def test_the_command_line_says_refused_and_exits_non_zero(tmp_path, capsys):
    assert backup_data.main(["drill", str(tmp_path)]) == 1
    assert "REFUSED" in capsys.readouterr().err
