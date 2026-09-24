# ADR-0023 — Queueing, concurrency and backfill: the AWS large-scale pattern vs the single worker

- **Status:** Accepted (research stage 1)
- **Date:** 2026-09-24
- **Decision:** **ADOPT the pattern, not the products.** Keep SQLite as the
  job store and one process; add an atomic claim, working retries, a
  priority lane and a manifest-driven backfill. **REJECT** a queue product
  (SQS, Redis, Celery, RabbitMQ) and any cloud service.

## Source read

`aws-samples/amazon-textract-serverless-large-scale-document-processing`.
Queues decouple submission from processing; separate fast (sync) and slow
(async) paths; throughput is controlled by batch size and a concurrency cap,
not ad-hoc throttling; **backfill** feeds an inventory list of existing
documents through the *same* pipeline as new arrivals; a job table
(DynamoDB) tracks every task. Used as an **architecture reference only**:
client documents must never be sent to Textract or any cloud service
(ADR-0002).

## The existing weakness

- `backend/app/ingest.py` `IngestionWorker`: one daemon thread, one document
  at a time, next document chosen by `ORDER BY uploaded_at LIMIT 1` — FIFO, no
  priority. A 2 M-page backfill would sit in front of an engineer's urgent
  submittal.
- `standards.next_extraction_job` is a plain `SELECT` with no claim; the claim
  `UPDATE` in `run_extraction_job` never checks its rowcount. Two workers
  duplicate work — reproduced by `backend/tests/test_job_claiming_race.py`.
- `jobs.retries` (`backend/app/db.py`) is written by nothing: a transient
  failure is final.
- No backfill path: the only entry point is upload.

## Evaluation data needed

- Measured per-stage throughput at scale (extract, OCR, chunk, embed) on a
  realistic sample, including the real image-page share (currently 0 pages on
  this machine; 30% is an unmeasured planning assumption).
- `test_job_claiming_race.py` measures the duplicate today; its docstring
  names the claim fix as the change that flips its assertion. The fix must
  land with that test inverted into a regression guard.
- Peak RSS with N OCR processes; ADR-0005 measured 598 MB for one and
  1,399 MB for two against ~1.15 GiB free at demo time.

## Measured benefit on our data

**Not measured.** The race is measured (reproduced); throughput gains are not.

## Cost on the stated hardware (estimate)

For 2 M pages, single worker, from this machine's measured rates: native
extract ~2 h (277.6 pages/s); embedding ~4 days (9.22 chunks/s, ~3.2 M chunks);
OCR on 600 k assumed image pages ~6–9 days (0.90–1.36 s/page). **Roughly two
weeks of continuous CPU, dominated by OCR and embedding** — all estimates.
RAM, not cores, caps concurrency: more than one OCR process does not fit
beside Ollama and the API.

## Integration risk

- Atomic claim is a small change: `UPDATE jobs SET state='running', claimed_at
  = ? WHERE id = (SELECT … WHERE state='queued' ORDER BY priority, created_at
  LIMIT 1) RETURNING …` (SQLite ≥ 3.35), plus a lease for crashed workers.
- Priority: interactive uploads ahead of backfill; backfill runs only when
  the interactive lane is empty.
- Backfill: a manifest (file list) enqueued as ordinary jobs, so the same
  stages, provenance and access grants apply.
- Existing single-worker comment in `standards.py` ("ONE WORKER, NOT A SECOND
  ONE") stays true until the claim fix lands; concurrency stays 1 for OCR.

## Reason for the decision

The weaknesses are concrete and two are measured. The AWS pattern's value is
its shape — job table, claim, retry, priority, backfill through one pipeline —
all expressible in the SQLite store already shipped. A queue product would
add infrastructure without removing the real bottleneck, which is CPU and
RAM on one laptop.
