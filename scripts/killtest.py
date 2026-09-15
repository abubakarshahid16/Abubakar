"""Hard-kill / resume proof for step 2.

Spawns the real extraction worker, polls SQLite until a batch has committed
but the document is NOT finished, then hard-kills the whole process tree with
taskkill /F /T (no signal handling, no cleanup - the same as pulling power).
Then restarts and proves the resume.
"""
import os, sqlite3, subprocess, sys, time

DOC = "doc_b02fb622b193"
BACKEND = r"d:\project\Rag_chatbot\backend"
PY = r"d:\project\Rag_chatbot\.venv\Scripts\python.exe"
DB = os.path.join(BACKEND, "data", "rag_intelligence.sqlite")


def q():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=10)
    c.row_factory = sqlite3.Row
    d = c.execute("SELECT page_count,pages_done,needs_ocr_pages,status FROM documents WHERE id=?", (DOC,)).fetchone()
    j = c.execute("SELECT state,pages_total,pages_done,last_completed_batch FROM jobs WHERE document_id=? ORDER BY started_at DESC LIMIT 1", (DOC,)).fetchone()
    p = c.execute("SELECT COUNT(*) n, COUNT(DISTINCT page_no) u, MIN(page_no) lo, MAX(page_no) hi, MAX(batch_no) mb FROM pages WHERE document_id=?", (DOC,)).fetchone()
    have = {r[0] for r in c.execute("SELECT page_no FROM pages WHERE document_id=?", (DOC,))}
    c.close()
    return d, j, p, have


def show(label):
    d, j, p, have = q()
    total = d["page_count"]
    missing = [x for x in range(1, (total or 0) + 1) if x not in have] if total else []
    print(f"\n===== {label} =====")
    print(f"  documents : page_count={d['page_count']} pages_done={d['pages_done']} needs_ocr={d['needs_ocr_pages']} status={d['status']}")
    print(f"  jobs      : state={j['state']} pages_total={j['pages_total']} last_completed_batch={j['last_completed_batch']}")
    print(f"  pages rows: count={p['n']} distinct={p['u']} min_page={p['lo']} max_page={p['hi']} max_batch={p['mb']}")
    print(f"  integrity : duplicate_pages={p['n'] - p['u']}  missing_pages={len(missing)}{(' ' + str(missing[:8])) if missing else ''}")
    return d, j, p


def main():
    subprocess.run([PY, r"..\scripts\resetdoc.py", DOC], cwd=BACKEND, capture_output=True)
    show("BEFORE — nothing extracted")

    print("\n===== starting worker; will hard-kill the tree the moment a batch commits mid-document =====")
    proc = subprocess.Popen([PY, "-m", "app.worker", DOC], cwd=BACKEND,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    caught = None
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 30:
        d, j, p, _ = q()
        lcb, total, done = j["last_completed_batch"], d["page_count"], d["pages_done"]
        if lcb is not None and total and 0 < done < total:
            caught = (lcb, done, total)
            break
        if proc.poll() is not None:
            break
        time.sleep(0.005)

    if caught is None:
        print("  !! could not catch a mid-document state; document finished first")
        proc.kill(); return 1

    lcb, done, total = caught
    print(f"  caught at last_completed_batch={lcb}, pages_done={done}/{total} after {time.perf_counter()-t0:.2f}s")
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    proc.wait(timeout=10)
    print(f"  process tree killed (exit={proc.returncode})")
    time.sleep(0.3)

    _, j_after, p_after = show("AFTER HARD KILL")
    killed_lcb = j_after["last_completed_batch"]
    killed_pages = p_after["n"]

    print(f"\n===== RESTART — must resume from batch {killed_lcb + 1}, not page 1 =====")
    r = subprocess.run([PY, "-m", "app.worker", DOC], cwd=BACKEND, capture_output=True, text=True)
    for line in r.stdout.splitlines():
        if "[done]" in line:
            print("  " + line.strip())

    d2, j2, p2 = show("AFTER RESUME")

    print("\n===== VERDICT =====")
    ok = True
    checks = [
        ("resumed from the checkpoint, not page 1", killed_lcb is not None and killed_pages > 0),
        ("no page processed twice", p2["n"] == p2["u"]),
        ("no page skipped", p2["n"] == d2["page_count"]),
        ("final count matches the document", d2["pages_done"] == d2["page_count"] == 546),
        ("job marked done", j2["state"] == "done"),
    ]
    for name, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok &= passed
    print(f"\n  pages already committed before the kill : {killed_pages}")
    print(f"  pages extracted by the resumed run      : {p2['n'] - killed_pages}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
