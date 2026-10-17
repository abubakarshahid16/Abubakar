"""Whole data-folder backup, restore, retention and off-disk copy (#475).

`backup_db.py` copies the database alone. The data folder holds more than
that: uploaded PDFs, the vector index, page images, issued CRS copies,
reports, the approved-documents list, the spend ledger, local checklists.
Losing any of them loses work the database still points at. This tool takes
the whole folder.

THE RULES, each one a function below:

  * SQLITE FILES ARE COPIED WITH THE ONLINE BACKUP API (`backup_db.backup`,
    the project's one implementation), never as bytes: a byte copy of a WAL
    database loses whatever sits in its `-wal` file. Their `-wal` and `-shm`
    sidecars are not copied - the backup API folds them in. A file is SQLite
    by its header, not by its extension.
  * EVERY BACKUP CARRIES A MANIFEST (`MANIFEST.json`): each file's relative
    path, size and sha256, and each database's row count per table. A backup
    without a manifest is not a backup this tool will restore or prune.
  * RESTORE WRITES ONLY INTO AN EMPTY FOLDER, and never into a checkout's
    live `backend/data` folder: moving the restored folder into place is a
    human's step (docs/security/approvals.md). Restore is followed by the
    DRILL, which re-hashes every file, runs `integrity_check` on every
    database and compares its row counts with the manifest. Any difference
    is a named failure, never a silent pass.
  * RETENTION (`prune`) keeps the newest `--keep-daily` backups and the
    newest backup of each of the last `--keep-monthly` months. It deletes
    only folders this tool made (name and manifest), and never the newest.
  * THE OFF-DISK COPY (`offdisk`) refuses a destination on the same device
    as the backup: a "second copy" on the same disk dies with the first.

No network, no model, no document text read or printed: paths, sizes,
hashes and counts only.

Usage:
  python scripts/backup_data.py backup  <data_dir> <backup_root>
  python scripts/backup_data.py restore <backup_folder> <empty_target>
  python scripts/backup_data.py drill   <backup_folder>
  python scripts/backup_data.py prune   <backup_root> [--keep-daily 7] [--keep-monthly 12]
  python scripts/backup_data.py offdisk <backup_folder> <other_disk_root>
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backup_db  # the one database backup implementation

MANIFEST = "MANIFEST.json"
PREFIX = "data-"
FORMAT = 1
SQLITE_HEADER = b"SQLite format 3\x00"
#: Sidecars the online backup folds in, and lock files that mean nothing
#: in a copy. Never copied.
SKIP_SUFFIXES = ("-wal", "-shm", "-journal")
SKIP_NAMES = (".heavy-job.lock",)
#: DERIVED INDEXES, never backed up, and named in the manifest with why: a
#: database holding a virtual table of one of these modules. The vec0 index is
#: rebuilt from `chunk_vectors` (which IS backed up) at startup
#: (`app/vector_store.py`), and a plain `sqlite3` connection cannot even count
#: its rows ("no such module: vec0"), so copying it made every backup fail.
DERIVED_MODULES = {"vec0": "derived vector index, rebuilt from chunk_vectors at startup"}


def _derived(path: Path) -> str | None:
    """Why this database is a derived index (not backed up), or None. Read
    from sqlite_master, which needs no extension."""
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        sql = [r[0] or "" for r in conn.execute("SELECT sql FROM sqlite_master WHERE type='table'")]
    finally:
        conn.close()
    for module, why in DERIVED_MODULES.items():
        if any(f"using {module}" in " ".join(q.lower().split()) for q in sql):
            return why
    return None


class BackupError(RuntimeError):
    """A backup, restore, drill, prune or off-disk copy that must not pass."""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _is_sqlite(path: Path) -> bool:
    with path.open("rb") as f:
        return f.read(len(SQLITE_HEADER)) == SQLITE_HEADER


def _skipped(path: Path) -> bool:
    return path.name in SKIP_NAMES or path.name.endswith(SKIP_SUFFIXES)


def _tables(path: Path) -> dict[str, int]:
    try:
        report = backup_db.verify(str(path))
    except sqlite3.OperationalError as exc:
        # A database this tool cannot read (an extension's virtual table) is
        # named, never a traceback - and never silently left out.
        raise BackupError(f"{path.name}: cannot be verified with plain sqlite3 ({exc})") from exc
    if not report["ok"]:
        raise BackupError(f"{path.name}: integrity_check says {report['integrity']}")
    return report["tables"]


def is_live_data_dir(path: Path) -> bool:
    """Any folder named `backend/data`, by the shape of its path alone: the
    live data folder of a checkout looks like this, and so does a copy of one.
    This is not a liveness check; it refuses both, on purpose."""
    p = Path(path).resolve()
    return p.name == "data" and p.parent.name == "backend"


def _copy_sqlite(source: Path, target: Path) -> None:
    """The online backup into `target`. A database with no tables has no
    WAL content to lose (`backup_db.backup` refuses it as a backup of the
    whole system), so it is copied as it is."""
    conn = sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)
    try:
        tables = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
                              " AND name NOT LIKE 'sqlite_%'").fetchone()[0]
    finally:
        conn.close()
    if tables == 0:
        shutil.copy2(source, target)
        return
    scratch = Path(tempfile.mkdtemp(prefix="backup-data-"))
    try:
        made = Path(backup_db.backup(str(source), str(scratch)))
        shutil.move(str(made), target)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def backup(data_dir: str | os.PathLike, backup_root: str | os.PathLike) -> Path:
    """One backup folder `<backup_root>/data-<stamp>/`, manifest written last
    and verified before returning."""
    source = Path(data_dir)
    if not source.is_dir():
        raise BackupError(f"no data folder at {data_dir}")
    root = Path(backup_root)
    if not root.is_dir():
        raise BackupError(f"no backup folder at {backup_root}: create it first")
    if root.resolve().is_relative_to(source.resolve()):
        raise BackupError("the backup folder is inside the data folder; it would back itself up")
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    dest = root / f"{PREFIX}{stamp}"
    dest.mkdir()                      # exclusive: an existing folder is an error
    files, databases, derived = [], {}, []
    for path in sorted(p for p in source.rglob("*") if p.is_file()):
        if _skipped(path):
            continue
        why = _derived(path) if _is_sqlite(path) else None
        if why:
            derived.append({"path": path.relative_to(source).as_posix(), "why": why})
            continue
        rel = path.relative_to(source).as_posix()
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if _is_sqlite(path):
            _copy_sqlite(path, target)
            databases[rel] = _tables(target)
        else:
            shutil.copy2(path, target)
        files.append({"path": rel, "bytes": target.stat().st_size, "sha256": _sha256(target)})
    if not files:
        shutil.rmtree(dest)
        raise BackupError(f"{data_dir} holds no files; nothing to back up")
    manifest = {"format": FORMAT, "made_at": _dt.datetime.now().isoformat(timespec="seconds"),
                "source": str(source.resolve()), "files": files, "databases": databases,
                "not_backed_up": derived}
    (dest / MANIFEST).write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    drill(dest)
    return dest


def _manifest(folder: Path) -> dict:
    path = Path(folder) / MANIFEST
    if not path.is_file():
        raise BackupError(f"{folder} has no {MANIFEST}; not a backup made by this tool")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise BackupError(f"{folder}: {MANIFEST} is not readable JSON") from exc
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        data = data if isinstance(data, dict) else {}
        raise BackupError(f"{folder}: manifest format {data.get('format')!r}, expected {FORMAT}")
    return data


def drill(folder: str | os.PathLike, manifest: dict | None = None) -> dict:
    """Every file present with its hash, every database whole with the
    manifest's row counts, and no file the manifest does not name. Returns
    the counts; raises `BackupError` naming the first difference."""
    folder = Path(folder)
    manifest = manifest or _manifest(folder)
    named = {f["path"] for f in manifest["files"]}
    for f in manifest["files"]:
        path = folder / f["path"]
        if not path.is_file():
            raise BackupError(f"drill: {f['path']} is missing")
        if _sha256(path) != f["sha256"]:
            raise BackupError(f"drill: {f['path']} does not match its sha256")
    extra = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*")
                   if p.is_file() and p.name != MANIFEST
                   and p.relative_to(folder).as_posix() not in named)
    if extra:
        raise BackupError(f"drill: {len(extra)} file(s) not in the manifest, first {extra[0]}")
    for rel, expected in manifest["databases"].items():
        got = _tables(folder / rel)
        if got != expected:
            raise BackupError(f"drill: {rel} row counts differ from the manifest")
    return {"files": len(manifest["files"]), "databases": len(manifest["databases"]),
            "documents": sum(t.get("documents", 0) for t in manifest["databases"].values())}


def restore(backup_folder: str | os.PathLike, target: str | os.PathLike) -> dict:
    """Copy the backup into an EMPTY folder and drill it there."""
    source, dest = Path(backup_folder), Path(target)
    manifest = _manifest(source)
    if is_live_data_dir(dest):
        raise BackupError(f"refusing to restore into a live data folder ({dest}); restore into "
                          "an empty folder and move it into place yourself")
    if dest.exists() and any(dest.iterdir()):
        raise BackupError(f"{dest} is not empty; restore writes only into an empty folder")
    dest.mkdir(parents=True, exist_ok=True)
    for f in manifest["files"]:
        target_file = dest / f["path"]
        target_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / f["path"], target_file)
    return drill(dest, manifest)


def _made_at(folder: Path) -> _dt.datetime:
    return _dt.datetime.strptime(folder.name[len(PREFIX):], "%Y%m%d-%H%M%S-%f")


def _backups(root: Path) -> list[Path]:
    """This tool's backups under `root`, newest first."""
    out = []
    for p in Path(root).iterdir():
        if p.is_dir() and p.name.startswith(PREFIX) and (p / MANIFEST).is_file():
            try:
                _made_at(p)
                # a manifest this version cannot read (a newer format, or not
                # JSON) is not counted, and so never deleted
                _manifest(p)
            except (ValueError, BackupError):  # a name that is not a stamp, or the manifest
                continue
            out.append(p)
    return sorted(out, key=_made_at, reverse=True)


def prune(backup_root: str | os.PathLike, *, keep_daily: int = 7, keep_monthly: int = 12) -> list[Path]:
    """Delete the backups outside the retention; returns what was deleted.
    The newest is always kept, whatever the numbers say."""
    if keep_daily < 1 or keep_monthly < 0:
        raise BackupError("keep at least one backup (--keep-daily 1 or more)")
    backups = _backups(Path(backup_root))
    keep = set(backups[:keep_daily])
    months: list[tuple[int, int]] = []
    for b in backups:
        month = (_made_at(b).year, _made_at(b).month)
        if month not in months:
            months.append(month)
            if len(months) <= keep_monthly:
                keep.add(b)
    deleted = [b for b in backups if b not in keep]
    for b in deleted:
        shutil.rmtree(b)
    return deleted


def _device(path: Path) -> int:
    return Path(path).stat().st_dev


def offdisk(backup_folder: str | os.PathLike, other_root: str | os.PathLike) -> Path:
    """Copy one backup to another disk and drill the copy there."""
    source, root = Path(backup_folder), Path(other_root)
    manifest = _manifest(source)
    if not root.is_dir():
        raise BackupError(f"no folder at {other_root}: connect the other disk and create it first")
    if _device(root) == _device(source):
        raise BackupError(f"{other_root} is on the same disk as {backup_folder}; "
                          "an off-disk copy must be on another device")
    dest = root / source.name
    if dest.exists():
        raise BackupError(f"{dest} already exists")
    shutil.copytree(source, dest)
    drill(dest, manifest)
    return dest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, *positional in (("backup", "data_dir", "backup_root"), ("restore", "backup", "target"),
                              ("drill", "backup"), ("prune", "backup_root"),
                              ("offdisk", "backup", "other_root")):
        command = sub.add_parser(name)
        for arg in positional:
            command.add_argument(arg)
        if name == "prune":
            command.add_argument("--keep-daily", type=int, default=7)
            command.add_argument("--keep-monthly", type=int, default=12)
    args = parser.parse_args(argv)
    try:
        if args.cmd == "backup":
            print(backup(args.data_dir, args.backup_root))
        elif args.cmd == "restore":
            print(json.dumps(restore(args.backup, args.target)))
        elif args.cmd == "drill":
            print(json.dumps(drill(args.backup)))
        elif args.cmd == "prune":
            print(f"deleted {len(prune(args.backup_root, keep_daily=args.keep_daily, keep_monthly=args.keep_monthly))}")
        else:
            print(offdisk(args.backup, args.other_root))
    except BackupError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
