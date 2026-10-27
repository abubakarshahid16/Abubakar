"""One review of invented data, dumped as JSON (order 228.10).

Run in a subprocess by `test_228_10_stability.py` under different PYTHONHASHSEED
values: the same input must give the same facts, findings and verdicts, byte for
byte. Ids are replaced by what they stand for, so only real differences show.
Usage: python tests/stability_probe.py OUT.json
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

STANDARD = (
    "Design pressure shall not exceed 10 barg. "
    "Design temperature shall not exceed 120 C. "
    "Noise level shall not exceed 85 dB(A). "
    "Vibration shall not exceed 4.5 mm/s. "
    "Rated flow shall be at least 20 m3/h. "
    "Operating temperature shall not exceed 90 C. "
    "Test pressure shall be at least 15 barg. "
    "Casing material shall be duplex stainless steel. "
    "Bearing life shall be at least 25000 hours. "
    "Differential head shall not be less than 50 m. "
    "Motor power shall not exceed 22 kW. "
    "Seal flush plan shall be Plan 11."
)
FACTS = [
    ("Design pressure", "9", "barg"),
    ("Design pressure", "12", "barg"),  # a second, different value: a conflict
    ("Design temperature", "110", "C"),
    ("Noise level", "92", "dB(A)"),
    ("Vibration", "4.2", "mm/s"),
    ("Rated flow", "24.8", "m3/h"),
    ("Rated flow", "22.6", "m3/h"),
    ("Operating temperature", "76.7", "C"),
    ("Test pressure", "13", "barg"),
    ("Casing material", "Duplex stainless steel", None),
    ("Bearing life", "30000", "hours"),
    ("Differential head", "48", "m"),
    ("Motor power", "18.5", "kW"),
    ("Seal flush plan", "Plan 32", None),
]


def _pdf(path: Path) -> str:
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=600, height=800)
    y = 60
    for index, (label, value, unit) in enumerate(FACTS, start=1):
        page.draw_rect(pymupdf.Rect(40, y - 14, 300, y + 6), color=(0, 0, 0), width=0.7)
        page.draw_rect(
            pymupdf.Rect(300, y - 14, 560, y + 6), color=(0, 0, 0), width=0.7
        )
        page.insert_text((44, y), label, fontsize=9)
        page.insert_text((304, y), f"{value} {unit or ''}".strip(), fontsize=9)
        y += 26
    doc.save(str(path))
    doc.close()
    return str(path)


def _ingest_pdf(doc_id: str, path: str, now: str) -> None:
    import pymupdf

    from app import db, fts_index

    pdf = pymupdf.open(path)
    text = pdf[0].get_text()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,"
            "uploaded_at) VALUES (?,?,?,1,?,'ready',1,?)",
            (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", path, now),
        )
        conn.execute(
            "INSERT INTO document_classification (document_id,suggested_by,document_role)"
            " VALUES (?,?,?)",
            (doc_id, "probe", "CONTRACTOR_SUBMITTAL"),
        )
        conn.execute(
            "INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,section,"
            "kind,text,token_count,content_hash,retrievable) VALUES (?,?,?,0,1,1,'1','prose',"
            "?,1,?,1)",
            (f"{doc_id}-c1", doc_id, f"{doc_id}.pdf", text, f"h-{doc_id}"),
        )
    fts_index.index_document(doc_id)


class _ScriptedEngine:
    """An engine that answers from the page text, the same way every time (no model)."""

    engine = "scripted"
    model = "scripted-1"

    def __call__(self, prompt: str) -> str:
        if "FIELDS:" in prompt:
            return json.dumps({"fields": []})
        lines = [ln for ln in prompt.split("PAGE 1:")[-1].splitlines() if ln.strip()]
        facts = []
        for label, value, unit in FACTS[:6]:
            for ln in lines:
                if label in ln and value in ln:
                    facts.append(
                        {
                            "field": label,
                            "value": value,
                            "unit": unit,
                            "quote": ln.strip(),
                            "kind": "offered",
                        }
                    )
                    break
        return json.dumps({"facts": facts})


def main(out: str) -> None:
    from app import comparison, datasheets, db, fts_index, standards, submittal_review
    from app.config import settings

    root = Path(tempfile.mkdtemp(prefix="stability-"))
    settings.data_dir = root
    settings.ollama_url = (
        "http://127.0.0.1:9"  # no engine is reachable: no model is ever asked
    )
    settings.db_path = root / "s.sqlite"
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    fts_index.ensure_schema()
    now = "2026-10-27T00:00:00Z"

    def doc(doc_id, role, text):
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,"
                "uploaded_at) VALUES (?,?,?,1,'/x','ready',1,?)",
                (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", now),
            )
            conn.execute(
                "INSERT INTO document_classification (document_id,suggested_by,document_role)"
                " VALUES (?,?,?)",
                (doc_id, "probe", role),
            )
            conn.execute(
                "INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,section,"
                "kind,text,token_count,content_hash,retrievable) VALUES (?,?,?,0,1,1,'1','prose',"
                "?,1,?,1)",
                (f"{doc_id}-c1", doc_id, f"{doc_id}.pdf", text, f"h-{doc_id}"),
            )
        fts_index.index_document(doc_id)

    doc("std_a", "COMPANY_STANDARD", STANDARD)
    pdf = _pdf(root / "sub_a.pdf")
    _ingest_pdf("sub_a", pdf, now)
    with db.connect() as conn:
        conn.execute(
            "UPDATE document_classification SET document_number = 'API 610' "
            "WHERE document_id = 'std_a'"
        )
    standards.extract_requirements("std_a", allowed_document_ids=frozenset({"std_a"}))
    from app import datasheet_ai

    settings.datasheet_ai_reader = "ollama"
    with datasheet_ai.using_model_call(_ScriptedEngine()):
        datasheets.extract_facts(
            "sub_a", allowed_document_ids=frozenset({"std_a", "sub_a"})
        )
    scope = frozenset({"std_a", "sub_a"})
    run_id = submittal_review.create_review_run(
        submittal_document_id="sub_a", allowed_document_ids=scope
    )
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_applicable_standards (id,review_run_id,standard_document_id,"
            "selection_method,included,created_at) VALUES ('sel-1',?,?,'rule',1,?)",
            (run_id, "std_a", now),
        )
    comparison.run_comparison(run_id, allowed_document_ids=scope)
    conn = db.connect()
    reqs = {
        r["id"]: r["source_text"] or r["requirement_text"]
        for r in conn.execute(
            "SELECT id, source_text, requirement_text FROM standard_requirements"
        )
    }
    facts = {
        r["id"]: f"{r['field_name']}={r['field_value']}"
        for r in conn.execute("SELECT id, field_name, field_value FROM submittal_facts")
    }
    rows = []
    for r in conn.execute(
        "SELECT requirement_id, fact_id, compliance_status, ai_rationale, requirement,"
        " finding, contractor_evidence_text FROM review_findings WHERE review_run_id = ?"
        " ORDER BY rowid",
        (run_id,),
    ):
        rows.append(
            [
                reqs.get(r["requirement_id"]),
                facts.get(r["fact_id"]),
                r["compliance_status"],
                r["ai_rationale"],
                r["finding"],
                r["contractor_evidence_text"],
            ]
        )
    print("requirements", len(reqs), "findings", len(rows), file=sys.stderr)
    outcome = comparison.run_outcome(run_id, allowed_document_ids=scope) or {}
    dump = {
        "findings": rows,
        "facts": list(facts.values()),
        "code": outcome.get("recommended_code"),
    }
    if os.environ.get(
        "STABILITY_PROBE_BREAK"
    ):  # the harness's own check: this MUST differ
        dump["unordered"] = list(
            {"alpha", "bravo", "charlie", "delta", "echo", "foxtrot"}
        )
    Path(out).write_text(json.dumps(dump, indent=1, sort_keys=False))


if __name__ == "__main__":
    main(sys.argv[1])
