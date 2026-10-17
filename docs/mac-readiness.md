# Mac readiness (#498): what runs on the Mac Studio, checked on the PC

Checked 17 Oct 2026 on main `4fc7e98`, on the Windows PC (no Mac yet). What is checked by
`backend/tests/test_498_mac_readiness.py` stays checked; what needs the Mac itself is listed at the end.

## 1. Windows-only paths and PowerShell

| Where | Finding | Status |
|---|---|---|
| `backend/app` | One Windows path: the heavy-job lock's owner-named default `D:/project/.heavy-job.lock`. Used **only when `os.name == "nt"`**; elsewhere the lock is the temp folder's `rag-intelligence-heavy-job.lock`, and `HEAVY_JOB_LOCK=<path>` overrides both. | OK as is (tested) |
| `backend/app/claude_spend.py` | The spend-ledger lock uses `fcntl.flock` on POSIX and `msvcrt.locking` only where `fcntl` is missing (Windows). | OK as is |
| `backend/app/watch_api.py` | Windows paths appear in comments only: the watcher accepts both separator styles on purpose. | OK as is |
| `backend/` external programs | Only `git` (`hooks_check.py`); no PowerShell, no `.exe`, no `cmd`. | OK as is |
| `scripts/bench_extract.py`, `chunk_report.py`, `killtest.py`, `textsample.py`, `reader_score_standard.py` | Hard-coded `d:\project\...` and `.venv\Scripts\python.exe`. | **Fixed:** repo from the script's own location, interpreter `sys.executable`, database `settings.db_path` |
| `scripts/killtest.py` | Hard-kill with `taskkill /F /T` (Windows only). | **Fixed:** `taskkill` on Windows, SIGKILL to the process group elsewhere |
| `scripts/prove_vision_reader_layouts.py` | Default bench folder `D:\docling-bench\input`. | **Fixed:** `DOCLING_BENCH_DIR`, else `~/docling-bench/input`; `--bench-dir` as before |
| `scripts/killtest.ps1`, `killtest2.ps1` | PowerShell copies of `killtest.py`. | **Deleted** (one version of each part) |
| `scripts/wt_pytest.ps1` | PowerShell, referenced by nothing, an old absolute path carrying the client's old name. | **Deleted** |
| `scripts/start-system.bat` | The one-click launcher; Windows only. | **Added `scripts/start-system.sh`**, the macOS/Linux twin with the same four lessons (venv interpreter, honest "started", `--strictPort`, no console-only wait). Not yet run on a Mac. |
| `eval/**/README.md`, `eval/review/*.md` | Commands written for PowerShell (`.venv\Scripts\python.exe`). | Documentation only; on the Mac use `.venv/bin/python` and `/` paths. |

## 2. Every path from settings

Every path setting in `backend/app/config.py` (`data_dir`, `upload_dir`, `db_path`, `embed_model_dir`,
`ocr_model_dir`, `claude_cache_dir`, `rule_trust_reference_path`, ...) is built from `BACKEND_DIR`, the
code's own location; none is a drive path. A Mac checkout therefore finds its own data and models
wherever it is cloned. The test asserts every `Path` setting resolves under `BACKEND_DIR`.

## 3. OCR (RapidOCR) on Apple Silicon

Checked with pip's platform resolver (`pip install --dry-run --only-binary=:all: --platform
macosx_14_0_arm64 --python-version 3.12`, each pinned line of `backend/requirements.txt`, nothing
installed): **every pinned package has a macOS arm64 build** - 11 native arm64 wheels, 1 universal2,
19 pure-Python wheels, and `antlr4-python3-runtime==4.9.3` (a RapidOCR dependency through omegaconf)
published only as a pure-Python source package, which installs on any platform.

| Package (pinned) | Mac build |
|---|---|
| `rapidocr 3.9.2` | pure Python |
| `onnxruntime 1.30.0` | `macosx_14_0_arm64` (**needs macOS 14 or later**) |
| `opencv-python 5.0.0.93` | `macosx_13_0_arm64` |
| `numpy 2.5.3`, `shapely 2.1.2`, `pymupdf 1.28.2` | `arm64` |
| `pyclipper 1.4.0` | `universal2` |

So RapidOCR installs on Apple Silicon as it is; no replacement is needed. If it ever does not (an older
macOS than 14 for `onnxruntime 1.30`): pin the last `onnxruntime` with a lower macOS floor, or run the
same ONNX models through onnxruntime's CoreML execution provider; Apple's own Vision OCR is a fallback
only, as it would change the engine named in the OCR provenance (`ocr.ENGINE`).

## Needs the Mac itself (cannot be proven here)

- install `backend/requirements.txt` into a Python 3.12 venv and run the suite and P1 (#498 acceptance);
- run `scripts/start-system.sh` once for real and record what it finds, as was done for the `.bat`;
- frontend `npm install` (native packages such as `lightningcss` pick their own platform build);
- the restore drill from a PC backup.
