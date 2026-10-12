"""Mutations of the pre-re-process ingestion fixes (audit 2026-09-30): the
re-chunk keeping vectors (chunker.py), the embedded count and the legacy
upgrade gate and job finishing (ingest.py), OCR engine failure degrading to
failed pages (ocr.py), and search leaving out documents that stopped without
being answerable (states.py). Target: backend/tests/test_audit_reprocess.py.
"""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_audit_reprocess.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1460", phase=1460,
             description="a re-chunk deletes every vector of the document again "
                         "(the orphan clean-up sees no chunks)",
             path=APP / "chunker.py",
             anchor="               AND chunk_id NOT IN (SELECT id FROM chunks WHERE document_id = ?)\"\"\",\n"
                    "            (doc_id, doc_id),\n"
                    "        )\n"
                    "        orphan_guard.reattach_requirements_after_rechunk(conn, doc_id, detached)\n"
                    "        # chunk_count is the RETRIEVABLE count",
             replacement="               AND chunk_id NOT IN (SELECT id FROM chunks WHERE document_id = ? AND 0)\"\"\",\n"
                         "            (doc_id, doc_id),\n"
                         "        )\n"
                         "        orphan_guard.reattach_requirements_after_rechunk(conn, doc_id, detached)\n"
                         "        # chunk_count is the RETRIEVABLE count",
             target=_T, keyword="keeps_the_vectors_of_unchanged_chunks",
             tags=("reliability",)),
    Mutation(id="M1461", phase=1461,
             description="a kept chunk id whose heading chain changed keeps a vector "
                         "computed from the old chain",
             path=APP / "chunker.py",
             anchor="(not r[12] or old_inputs[r[0]] != (r[6], r[18]))",
             replacement="(not r[12])",
             target=_T, keyword="heading_changed_loses_its_vector",
             tags=("retrieval",)),
    Mutation(id="M1462", phase=1462,
             description="the embedded count includes vectors of excluded chunks, so a "
                         "document is READY with a retrievable chunk unembedded",
             path=APP / "ingest.py",
             anchor="            f\"\"\"SELECT COUNT(*) FROM chunk_vectors v\n"
                    "               JOIN chunks c ON c.id = v.chunk_id AND c.retrievable = 1",
             replacement="            f\"\"\"SELECT COUNT(*) FROM chunk_vectors v\n"
                         "               JOIN chunks c ON c.id = v.chunk_id",
             target=_T, keyword="excluded_chunk_never_counts_toward_ready",
             tags=("honesty",)),
    Mutation(id="M1463", phase=1463,
             description="legacy heading-v1 vectors are upgraded only when some chunk "
                         "has no vector at all (the old count gate)",
             path=APP / "ingest.py",
             anchor="                    self._recount_embedded(doc_id)\n"
                    "                    if self._needs_embedding(doc_id):",
             replacement="                    if self._recount_embedded(doc_id) < row[\"chunk_count\"]:",
             target=_T, keyword="upgrades_legacy_vectors",
             tags=("retrieval",)),
    Mutation(id="M1464", phase=1464,
             description="a missing OCR model is not recognised as an engine failure "
                         "(the page reason no longer says so)",
             path=APP / "ocr.py",
             anchor="    try:\n"
                    "        ocr = _build_engine()\n"
                    "    except Exception as exc:  # noqa: BLE001 - a missing model is every page failing, not the document\n"
                    "        return failed_rows(page_nos, f\"engine_unavailable: {type(exc).__name__}: {exc}\")\n",
             replacement="    ocr = _build_engine()\n",
             target=_T, keyword="missing_ocr_model",
             tags=("reliability",)),
    Mutation(id="M1465", phase=1465,
             description="a worker failure re-raises out of recognise_document and "
                         "fails a readable document",
             path=APP / "ocr.py",
             anchor="                except Exception as exc:  # noqa: BLE001 - the worker, not the document, failed",
             replacement="                except ZeroDivisionError as exc:  # noqa: BLE001",
             target=_T, keyword="killed_ocr_worker",
             tags=("reliability",)),
    Mutation(id="M1466", phase=1466,
             description="a broken OCR pool is not replaced: every later batch "
                         "fails too",
             path=APP / "ocr.py",
             anchor="                    if isinstance(exc, cf.BrokenExecutor):\n"
                    "                        broken = True",
             replacement="                    if False:\n"
                         "                        broken = True",
             target=_T, keyword="killed_ocr_worker",
             tags=("reliability",)),
    Mutation(id="M1467", phase=1467,
             description="the exclusion ledger keeps saying 'recognition has not run' "
                         "about pages it ran on and failed",
             path=APP / "ocr.py",
             anchor="            \" AND rule = 'ocr_not_run'\",\n"
                    "            failed_pages,",
             replacement="            \" AND rule = 'ocr_not_run' AND 0\",\n"
                         "            failed_pages,",
             target=_T, keyword="missing_ocr_model",
             tags=("honesty",)),
    Mutation(id="M1468", phase=1468,
             description="search answers from failed documents again (keyword and dense)",
             path=APP / "states.py",
             anchor="    return frozenset(allowed_document_ids) - stopped",
             replacement="    return frozenset(allowed_document_ids)",
             target=_T, keyword="never_returns_a_chunk_of_a_failed_document",
             tags=("honesty",)),
    Mutation(id="M1469", phase=1469,
             description="finishing a document marks EVERY job of it done, including a "
                         "failed fact extraction and a queued requirement extraction",
             path=APP / "ingest.py",
             anchor="        \" WHERE document_id = ? AND stage IN ('extract', 'chunk')\",\n"
                    "        (_now(), doc_id),",
             replacement="        \" WHERE document_id = ?\",\n"
                         "        (_now(), doc_id),",
             target=_T, keyword="leaves_its_other_jobs_alone",
             tags=("honesty",)),
)
