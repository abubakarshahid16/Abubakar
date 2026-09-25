"""Mutations of `backend/app/upload.py`."""

from __future__ import annotations

from ._base import APP, Mutation


MUTATIONS: tuple[Mutation, ...] = (
    # ---- from PHASE_2 -----------------------------------------------------
    Mutation(
        id="M15", phase=2,
        description="let the upload route overwrite an existing stored original",
        path=APP / "upload.py",
        anchor="    if final_path.exists():",
        replacement="    if False:",
        target="tests/test_document_original_file.py",
        keyword="never_rewrites or guards_the_stored_path",
        tags=("immutability",),
    ),
    # ---- from PHASE_2_XLSX ------------------------------------------------
    #: Phase 2 continued: the workbook upload path.
    Mutation(
        id="M16", phase=2,
        description="accept any zip as a workbook (drop the xl/workbook.xml proof)",
        path=APP / "upload.py",
        anchor="            if _XLSX_REQUIRED_ENTRY not in names:",
        replacement="            if False:",
        target="tests/test_xlsx_upload.py",
        keyword="not_a_workbook or docx",
        tags=("validation", "upload"),
    ),
    Mutation(
        id="M17", phase=2,
        description="remove the decompression-bomb ceiling",
        path=APP / "upload.py",
        anchor="            if declared > MAX_XLSX_UNCOMPRESSED_BYTES:",
        replacement="            if False:",
        target="tests/test_xlsx_upload.py",
        keyword="decompression_bomb",
        tags=("validation", "upload"),
    ),
    Mutation(
        id="M18", phase=2,
        description="queue a workbook for indexing like a PDF",
        path=APP / "upload.py",
        anchor="    indexed = kind != KIND_XLSX",
        replacement="    indexed = True",
        target="tests/test_xlsx_upload.py",
        keyword="terminal_state or worker_never_selects",
        tags=("pipeline", "upload"),
    ),
    Mutation(
        id="M19", phase=2,
        description="hardcode the stored suffix back to .pdf, so an xlsx "
                    "overwrites or misses the immutability guard",
        path=APP / "upload.py",
        anchor='    final_path = settings.upload_dir / f"{sha256}{_SUFFIX_FOR_KIND[kind]}"',
        replacement='    final_path = settings.upload_dir / f"{sha256}.pdf"',
        target="tests/test_xlsx_upload.py",
        keyword="never_rewrites or suffix_comes_from_the_bytes",
        tags=("immutability", "upload"),
    ),
    Mutation(
        id="M20", phase=2,
        description="accept macro-enabled workbooks",
        path=APP / "upload.py",
        anchor='            if any(n.lower().startswith("xl/vbaproject") for n in names):',
        replacement="            if False:",
        target="tests/test_xlsx_upload.py",
        keyword="macros",
        tags=("validation", "upload"),
    ),
)
