# Backup, restore and off-disk copy (#475)

The whole data folder (`backend/data`) is backed up, not the database alone: uploaded PDFs, the vector index, page images, issued CRS copies, reports, the approved-documents list, the spend ledger and local checklists live there too. Tool: `scripts/backup_data.py`. Test: `backend/tests/test_backup_data.py`.

| Step | Command (from the repository root) | When |
|---|---|---|
| Back up | `python scripts/backup_data.py backup backend\data D:\project\Rag_chatbot-backups` | Daily |
| Copy to the second disk | `python scripts/backup_data.py offdisk <backup folder> E:\rag-backups` | Daily, after the backup |
| Keep | `python scripts/backup_data.py prune D:\project\Rag_chatbot-backups --keep-daily 7 --keep-monthly 12` | Daily, after the copy |
| Restore drill | `python scripts/backup_data.py restore <backup folder> D:\project\restore-drill\<date>` | Monthly |

(Owner decision on #475, 8 Oct: an off-disk copy daily, a restore drill monthly. `E:` stands for whatever the second disk is.)

What each step guarantees, or refuses with `REFUSED: ...` and exit code 1:

- **Backup:** every SQLite file is copied with the online backup API, so rows still in a `-wal` file are kept; `-wal`, `-shm` and lock files are not copied. A `MANIFEST.json` lists every file's size and sha256 and every database's row count per table, and the new backup is drilled before the command returns.
- **Restore** writes only into an **empty** folder, never into a checkout's live `backend\data`. Putting the restored folder in place is a person's step with the backend stopped (S6, [approvals.md](approvals.md)). The restore then runs the drill.
- **Drill:** every file present with the manifest's sha256, no file the manifest does not name, every database passes `integrity_check` with the manifest's row counts. Any difference is named; nothing passes silently.
- **Off-disk copy:** refused when the destination is on the same disk as the backup. The copy is drilled on the other disk.
- **Prune:** keeps the newest `--keep-daily` backups and the newest backup of each of the last `--keep-monthly` months; the newest is always kept. It deletes only folders this tool made (`data-<stamp>` with a manifest).

Record each monthly drill on #692: the backup's name, the file and database counts the drill printed, pass or fail.
