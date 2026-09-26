"""Mutations of `backend/app/ingest.py`."""

from __future__ import annotations

from ._base import (
    APP,
    _B176_TARGET,
    _B3_TEST,
    _EQUIPMENT_TYPE_TEST,
    _INGEST_FACTS_TEST,
    Mutation,
)


MUTATIONS: tuple[Mutation, ...] = (
    # ---- from INGEST_FACT_WIRING ------------------------------------------
    #: B19's other half: fact extraction wired into ingestion completion (upload
    #: + watched folder), never a manually-started review run.
    Mutation(
        id="M356", phase=45,
        description="PUT THE WIRING BACK: drop the ingestion-side call, so a "
                    "submittal that only ever gets uploaded never gets facts",
        path=APP / "ingest.py",
        anchor="            _queue_extraction_if_standard(doc_id)\n"
               "            _extract_facts_if_contractor_submittal(doc_id)",
        replacement="            _queue_extraction_if_standard(doc_id)",
        target=_INGEST_FACTS_TEST,
        keyword="gets_facts_from_ingestion_alone",
        tags=("critical",),
    ),
    Mutation(
        id="M357", phase=45,
        description="drop the CONTRACTOR_SUBMITTAL role gate, so a "
                    "COMPANY_STANDARD is read by the datasheet extractor too",
        path=APP / "ingest.py",
        anchor='    role = (record or {}).get("document_role")\n'
               '    if role != "CONTRACTOR_SUBMITTAL":\n        return',
        replacement='    role = (record or {}).get("document_role")\n'
                    '    if False:\n        return',
        target=_INGEST_FACTS_TEST,
        keyword="a_company_standard_never_gets_datasheet_facts or "
                "an_unclassified_document_gets_no_facts",
        tags=("critical",),
    ),
    # ---- from B9_EQUIPMENT_TYPE -------------------------------------------
    #: B9: automated, evidence-based `equipment_type` for CONTRACTOR_SUBMITTAL,
    #: wired into the same ingestion-completion point as B19's fact extraction.
    Mutation(
        id="M359", phase=46,
        description="PUT THE WIRING BACK: drop the ingestion-side call, so a "
                    "submittal that only ever gets uploaded never gets an "
                    "equipment_type",
        path=APP / "ingest.py",
        anchor="            _extract_facts_if_contractor_submittal(doc_id)\n"
               "            _classify_equipment_type_if_contractor_submittal(doc_id)",
        replacement="            _extract_facts_if_contractor_submittal(doc_id)",
        target=_EQUIPMENT_TYPE_TEST,
        keyword="test_a_pump_datasheet_is_classified_as_a_pump_not_a_vessel"
                " or test_a_psv_datasheet_is_classified_as_a_valve_not_a_pump",
        tags=("critical",),
    ),
    # ---- from B176_SUBMITTAL_METADATA -------------------------------------
    Mutation(
        id="M429", phase=54,
        description="unwire the title-block classifier from ingestion, so "
                    "every submittal keeps NULL fields however clearly its "
                    "title block states them (#176)",
        path=APP / "ingest.py",
        anchor="            _classify_metadata_if_contractor_submittal(doc_id)\n",
        replacement="",
        target=_B176_TARGET,
        keyword="ingestion_writes",
        tags=("critical",),
    ),
    # ---- from B177_JOB_CLAIM_RETRY_PRIORITY -------------------------------
    Mutation(
        id="M412", phase=53,
        description="the ingestion claim no longer checks who holds the "
                    "document, so two IngestionWorkers take the same one "
                    "(#177 gap 1, document side)",
        path=APP / "ingest.py",
        anchor="        free_d = (\"(d.claimed_by IS NULL OR d.claimed_by = :me\"\n"
               "                  \" OR d.claimed_at IS NULL OR d.claimed_at < :stale)\")\n"
               "        free = (\"(claimed_by IS NULL OR claimed_by = :me\"\n"
               "                \" OR claimed_at IS NULL OR claimed_at < :stale)\")\n",
        replacement="        free_d = \"(1 = 1)\"\n"
                    "        free = \"(1 = 1)\"\n",
        target="tests/test_job_claiming_race.py",
        keyword="two_ingestion_workers",
        tags=("critical",),
    ),
    Mutation(
        id="M413", phase=53,
        description="a stale claim is never taken over, so a document held "
                    "by a worker that died mid-job is stranded forever after "
                    "a restart (#177 restart recovery)",
        path=APP / "ingest.py",
        anchor="        free_d = (\"(d.claimed_by IS NULL OR d.claimed_by = :me\"\n"
               "                  \" OR d.claimed_at IS NULL OR d.claimed_at < :stale)\")\n"
               "        free = (\"(claimed_by IS NULL OR claimed_by = :me\"\n"
               "                \" OR claimed_at IS NULL OR claimed_at < :stale)\")\n",
        replacement="        free_d = (\"(d.claimed_by IS NULL OR d.claimed_by = :me)\")\n"
                    "        free = (\"(claimed_by IS NULL OR claimed_by = :me)\")\n",
        target="tests/test_job_queue_177.py",
        keyword="held_by_a_dead_worker",
    ),
    Mutation(
        id="M417", phase=53,
        description="documents are claimed oldest-first again, so an "
                    "interactive upload waits behind a backfill (#177 gap 3)",
        path=APP / "ingest.py",
        anchor="                                ORDER BY d.priority DESC, d.uploaded_at LIMIT 1)",
        replacement="                                ORDER BY d.uploaded_at LIMIT 1)",
        target="tests/test_job_queue_177.py",
        keyword="outranks_an_earlier_backfill",
    ),
    # ---- from B3_PAGE_LEDGER ----------------------------------------------
    #: Master order B3: the page ledger, and a review that never calls an unread
    #: page the contractor's omission. Phase 57.
    Mutation(
        id="M456", phase=57,
        description="ingestion finishes without accounting for the document's "
                    "pages (B3)",
        path=APP / "ingest.py",
        anchor="            # LAST, after fact extraction, so the ledger carries its outcome.\n"
               "            _refresh_page_ledger(doc_id)\n",
        replacement="",
        target=_B3_TEST, keyword="ingestion_builds_the_ledger",
    ),
    Mutation(
        id="M460", phase=57,
        description="a document with nothing searchable finishes with its pages "
                    "unaccounted for - the pages most at risk of vanishing (B3)",
        path=APP / "ingest.py",
        anchor="                    (_now(), doc_id),\n"
               "                )\n"
               "            _refresh_page_ledger(doc_id)\n"
               "            return\n",
        replacement="                    (_now(), doc_id),\n"
                    "                )\n"
                    "            return\n",
        target=_B3_TEST, keyword="nothing_searchable_still_has_its_pages",
        tags=("honesty",),
    ),
    Mutation(
        id="M797", phase=68, description="B6B E1: ingestion embeds the body alone - the heading is dropped from the vector",
        path=APP / "ingest.py",
        anchor='                [embedder.passage_input(r["section"], r["text"]) for r in window])\n',
        replacement='                [r["text"] for r in window])\n',
        target="tests/test_b6b_e1_heading_embedding.py", keyword="heading_aware_vector",
    ),
)
