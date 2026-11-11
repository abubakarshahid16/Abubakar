"""Shared helpers of the rule finishing line tests (no tests here). Every text is INVENTED."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app import rule_finish_guard as guard


@pytest.fixture(autouse=True)
def marker_key(tmp_path, monkeypatch):
    """A throw-away signing key, so no test touches the real key file."""
    monkeypatch.setenv("RULE_FINISH_MARKER_KEY_FILE", str(tmp_path / "marker.key"))


def rule(**kw):
    base = {
        "rule_id": "r1",
        "rule_key": "rulekey-invented-1",
        "version_id": "v1",
        "standard": "X.pdf",
        "kind": "no_figure",
        "field": "wall thickness",
        "comparator": None,
        "value": None,
        "value_low": None,
        "value_high": None,
        "unit": None,
        "quote": "Widgets shall be painted.",
        "page": 1,
        "standard_document_id": "d",
        "applicability": [("subject", "pumps")],
    }
    base.update(kw)
    return base


def make_copy(
    path: Path,
    quote="The wall shall be at least 10 mm and at most 20 mm thick.",
    marked=True,
    key="keyabc12345",
):
    conn = sqlite3.connect(path)
    conn.executescript(
        """CREATE TABLE rulebook_rule (id TEXT, rule_key TEXT, standard TEXT);
        CREATE TABLE rulebook_version (id TEXT, rule_id TEXT, version_no INT, kind TEXT, field TEXT, comparator TEXT,
          value REAL, value_low REAL, value_high REAL, value_text TEXT, unit TEXT, unit_dimension TEXT, strength TEXT,
          sentence_strength TEXT, context_flag TEXT);
        CREATE TABLE rulebook_provenance (id INTEGER PRIMARY KEY, rule_version_id TEXT, standard_document_id TEXT,
          edition TEXT, clause TEXT, page INT, quote TEXT, quote_start INT, quote_end INT, page_source TEXT);
        CREATE TABLE rulebook_applicability (id INTEGER PRIMARY KEY, rule_version_id TEXT, key_type TEXT, value TEXT);"""
    )
    conn.execute("INSERT INTO rulebook_rule VALUES ('r1',?,'X.pdf')", (key,))
    conn.execute(
        "INSERT INTO rulebook_version VALUES ('v1','r1',1,'no_figure','wall thickness',NULL,NULL,NULL,NULL,NULL,NULL,NULL,'shall',NULL,NULL)"
    )
    conn.execute(
        "INSERT INTO rulebook_provenance (rule_version_id, standard_document_id, clause, page, quote) VALUES ('v1','d','4.1',1,?)",
        (quote,),
    )
    conn.execute(
        "INSERT INTO rulebook_applicability (rule_version_id, key_type, value) VALUES ('v1','subject','pumps')"
    )
    conn.commit()
    if marked:  # what prepare_work_copy does for a copy it made
        guard._write_marker(conn, guard._real(path), "source-of-this-copy")
    return conn


def make_pages_db(path: Path, pages: dict[int, str], document="d") -> Path:
    conn = sqlite3.connect(path)
    conn.executescript(
        """CREATE TABLE pages (document_id TEXT, page_no INT, text TEXT);
        CREATE TABLE page_ocr (document_id TEXT, page_no INT, text TEXT, min_conf REAL, alphabet_violations INT,
          alphabet_sample TEXT);"""
    )
    conn.executemany(
        "INSERT INTO pages VALUES (?,?,?)", [(document, n, t) for n, t in pages.items()]
    )
    conn.commit()
    conn.close()
    return path
