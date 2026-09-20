"""The first real call: SAES-A-105 pages 8-10 through the reader, scored.

WHAT THIS DOES, IN ORDER
  1. scores the PARSER's rows for SAES-A-105 against gold/SAES-A-105.csv on
     the LIVE database, read-only - the baseline the reader has to beat;
  2. copies the database (backup API) and, on the COPY ONLY, deletes the
     parser's unconfirmed rows for this one document;
  3. feeds every sentence on pages 8-10 to `reader_api.read_sentences` via
     `reader_transport.transport()` - the real socket, two calls per sentence;
  4. writes the ACCEPTED proposals into the copy through the real writer,
     `standards.create_requirement`, marked extraction_method='model' and
     held below the verification threshold;
  5. scores the copy against the same gold sheet;
  6. prints what it cost, from the API's own usage block.

The live database is never written. No standard sentence is printed.

    python reader_score_a105.py <scratch dir>
"""
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(r"D:\project\Rag_chatbot")
LIVE = REPO / "backend" / "data" / "rag_intelligence.sqlite"
GOLD = REPO / "gold" / "SAES-A-105.csv"
DOC = "doc_a835c3a15e04"
PAGES = (8, 10)
OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
PY = sys.executable

sys.path.insert(0, str(REPO / "backend"))


def score(db: Path, label: str) -> str:
    print(f"\n{'=' * 90}\n{label}\n{'=' * 90}")
    out = subprocess.run(
        [PY, str(REPO / "scripts" / "gold_score.py"), str(db), str(GOLD), "--verbose"],
        capture_output=True, text=True, encoding="utf-8", cwd=str(REPO))
    print(out.stdout.strip() or out.stderr.strip())
    return out.stdout


# ------------------------------------------------------- 1. the baseline
baseline = score(LIVE, "PARSER (live database, read-only) vs gold/SAES-A-105.csv")

# ------------------------------------------------------- 2. the copy
copy = OUT / f"a105-reader-{time.strftime('%Y%m%d-%H%M%S')}.sqlite"
src = sqlite3.connect(f"file:{LIVE}?mode=ro", uri=True)
dst = sqlite3.connect(str(copy))
src.backup(dst)
src.close()
dst.close()
print(f"\ncopy: {copy.name}")

from app.config import settings  # noqa: E402

settings.db_path = copy
from app import claims, db, reader_api, reader_transport, standards  # noqa: E402
from app.standards import (  # noqa: E402
    _INLINE_CLAUSE,
    clause_number,
    strip_page_furniture,
)

conn = db.connect()
removed = conn.execute(
    "DELETE FROM standard_requirements WHERE standard_document_id = ? "
    "AND confirmed_by IS NULL", (DOC,)).rowcount
conn.commit()
print(f"copy: removed the parser's {removed} unconfirmed rows for SAES-A-105")

# ------------------------------------------------------- 3. the sentences
chunks = [dict(r) for r in conn.execute(
    "SELECT id, section, page_start, text FROM chunks WHERE document_id = ? "
    "AND retrievable = 1 AND page_start BETWEEN ? AND ? ORDER BY ordinal",
    (DOC, *PAGES))]
work = []   # (sentence, chunk_id, clause, page)
for ch in chunks:
    heading = clause_number(ch["section"])
    # THE LAST INLINE CLAUSE CARRIES FORWARD within a chunk. Splitting into
    # sentences first is what cost the four SAES-A-105 exceptions their
    # clause on the first scored run: "5.3.3 New equipment shall not..." is
    # one sentence carrying the number, and the four numbered exceptions that
    # follow it are separate sentences carrying none, so they fell back to
    # the chunk's heading (5.3.1) and scored as four MISSED plus four EXTRA.
    # The parser does not have this problem because `_requirement_parts`
    # splits the exceptions out of the parent sentence, which already matched
    # `_INLINE_CLAUSE`. This reproduces that inheritance.
    current = None
    for sentence in claims.split_sentences(strip_page_furniture(ch["text"] or "")):
        inline = _INLINE_CLAUSE.match(sentence)
        if inline:
            current = inline.group("clause")
        work.append((sentence, ch["id"], current or heading, ch["page_start"]))
print(f"sentences to read: {len(work)} from {len(chunks)} chunks on pages {PAGES[0]}-{PAGES[1]}")
print(f"expected calls   : {2 * len(work)} (rule 5 reads each sentence twice)")

# ------------------------------------------------------- the lane
send = reader_transport.transport()
if send is None:
    print("\nREFUSED: the lane is shut - both STANDARDS_READER flags must be true.")
    sys.exit(2)
try:
    cfg = reader_api.ReaderSettings.from_env()
    reader_api.build_request("probe", cfg=cfg)
except reader_api.ReaderRefused as exc:
    print(f"\nREFUSED before any call: {exc}")
    sys.exit(2)
print(f"model            : {cfg.model}   host: api.anthropic.com   timeout {cfg.timeout_seconds}s")

# EVERY RAW ANSWER IS CACHED, so re-scoring never costs a second paid run.
# The cache is keyed by model and prompt; `--replay` reads it and makes no
# call at all. A scoring change must not be a reason to spend money again,
# and a number nobody can reproduce without paying is not a measurement.
import hashlib  # noqa: E402
import json as _json  # noqa: E402

CACHE = OUT / "reader-cache.json"
cache = _json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
REPLAY = "--replay" in sys.argv
raw_call = reader_api.model_call_via(send, cfg=cfg)
misses = [0]


#: How many times this run has asked each prompt. THE KEY MUST INCLUDE IT.
#: Keying on the prompt alone made rule 5 vacuous: `read_sentence` asks the
#: same prompt twice on purpose, so the second ask hit the cache and the
#: stability check compared an answer with itself. 70 expected calls became
#: 32 and `model_unstable` went from 2 rejections to 0 - a guard switched off
#: by an optimisation, which is this project's most-repeated defect shape.
asked: dict = {}


def model_call(prompt: str) -> str:
    n = asked[prompt] = asked.get(prompt, 0) + 1
    key = hashlib.sha256(
        f"{cfg.model}\x00{n}\x00{prompt}".encode()).hexdigest()
    if key in cache:
        return cache[key]
    if REPLAY:
        raise SystemExit("--replay: a prompt is not in the cache; run without it first")
    misses[0] += 1
    answer = raw_call(prompt)
    cache[key] = answer
    return answer


t0 = time.perf_counter()
by_sentence = {s: (cid, cl, pg) for s, cid, cl, pg in work}
result = reader_api.read_sentences([w[0] for w in work], model_call)
elapsed = time.perf_counter() - t0
CACHE.write_text(_json.dumps(cache), encoding="utf-8")
print(f"cache: {len(cache)} answers held, {misses[0]} paid for on this run")

# ------------------------------------------------------- 4. write, via the real writer
written = 0
for p in result["accepted"]:
    cid, clause, page = by_sentence[p["sentence"]]
    limit = {}
    if p["kind"] == "limit":
        m = claims.normalise(str(p["value"]), str(p.get("unit") or ""))
        limit = {"operator": p["operator"], "raw_value": str(p["value"]),
                 "raw_unit": p.get("unit") or None,
                 "value": m.normalized_value, "unit": m.normalized_unit}
    elif p.get("value") not in (None, ""):
        limit = {"raw_value": str(p["value"]), "raw_unit": p.get("unit") or None}
    standards.create_requirement(
        standard_document_id=DOC, chunk_id=cid,
        requirement_text=p["sentence"], source_text=p["sentence"],
        clause=clause, page=page,
        extraction_method="model",
        confidence=0.5,   # below VERIFICATION_THRESHOLD: a model row awaits a person
        structured={"requirement_type": reader_api.requirement_type_of(p),
                    "subject": p.get("subject") or None, **limit})
    written += 1

# ------------------------------------------------------- the reader's own account
print(f"\n{'=' * 90}\nREADER on the copy\n{'=' * 90}")
print(f"  calls made       : {send.usage['calls']}   in {elapsed:.0f}s")
print(f"  tokens           : in {send.usage['input_tokens']}   out {send.usage['output_tokens']}"
      f"   bytes sent {send.usage['bytes_sent']}")
print(f"  errors (malformed): {len(result['errors'])}")
print(f"  accepted         : {len(result['accepted'])}   written {written}")
print(f"  rejected         : {len(result['rejected'])}   by reason: {result['counts']}")
kinds = {}
for p in result["accepted"]:
    kinds[p["kind"]] = kinds.get(p["kind"], 0) + 1
print(f"  accepted by kind : {kinds}")
print("\n  accepted limits (clause / op / value / unit / subject):")
for p in result["accepted"]:
    if p["kind"] == "limit":
        _, clause, page = by_sentence[p["sentence"]]
        print(f"    {clause!s:<8} p{page}  {p['operator']:<3} {p['value']:<7} "
              f"{p.get('unit')!s:<7} {p.get('subject')}")
print("\n  rejections (clause / reason):")
for r in result["rejected"]:
    _, clause, page = by_sentence[r["sentence"]]
    print(f"    {clause!s:<8} p{page}  {r['reason']}")

# ------------------------------------------------------- 5. score the reader
after = score(copy, "READER (disposable copy) vs gold/SAES-A-105.csv")

print(f"\ncopy left at {copy} - delete when done; the live database was not written.")
