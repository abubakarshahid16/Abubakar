"""Order 121 C follow-up: the geometry check script reads a stored path that
is relative to the data folder (#1151 stores uploads that way), instead of
skipping every document as "not present on this machine".

Synthetic data only.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pymupdf

from app import db
from app.config import settings

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "verify_geometry_ocr_guard_on_real_docs",
    REPO / "scripts" / "verify_geometry_ocr_guard_on_real_docs.py",
)
script = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = script
_spec.loader.exec_module(script)


def test_the_geometry_check_reads_a_relative_stored_path(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    (tmp_path / "uploads").mkdir(exist_ok=True)
    pdf = pymupdf.open()
    pdf.new_page().insert_text((72, 100), "Design pressure 10 barg")
    pdf.save(str(tmp_path / "uploads" / "a.pdf"))
    pdf.close()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,"
            "page_count,uploaded_at) VALUES ('d1','a.pdf','sha-d1',1,'uploads/a.pdf',"
            "'ready',1,'2026-10-19T00:00:00Z')"
        )
        conn.execute(
            "INSERT INTO document_classification (document_id, document_role, suggested_by)"
            " VALUES ('d1', 'CONTRACTOR_SUBMITTAL', 'test')"
        )
    db.reset_connection()

    script.main(["--limit", "1", "--pages-per-doc", "1"])

    out = capsys.readouterr().out
    assert "SKIP - stored file not present" not in out
    assert "Documents actually read: 1" in out
