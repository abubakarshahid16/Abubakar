"""Copy that describes a shipped capability as missing.

WHY THIS FILE EXISTS. The Dashboard told readers "OCR is detected but NOT
implemented, so those pages are not searchable" for as long as OCR had been
shipped, while the Documents screen on the same build said "89 of 89 pages read
by OCR". Two screens contradicting each other about a working feature.

It survived because NOTHING TESTS COPY AGAINST REALITY. It is also the SECOND
instance: an "OCR is not implemented" tooltip was removed from the amber badge
earlier, and that fix did not sweep wide enough - it fixed the string someone
had noticed rather than the class of string.

This test is the sweep. It scans the source for phrases that assert a
capability is absent, and fails if one appears anywhere a reader could see it.
Adding a genuinely-unimplemented feature means adding it to ALLOWED with a
reason, which is a line somebody has to write on purpose.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

#: Phrases that assert something does not exist. Matched case-insensitively.
DENIALS = [
    r"not implemented",
    r"isn't implemented",
    r"is not available",
    r"not yet available",
    r"no OCR",
    r"OCR is deliberately",
]

#: Where a reader can see text: API messages and rendered components.
SEARCHED = [
    ROOT / "backend" / "app",
    ROOT / "frontend" / "src",
    ROOT / "contracts",
]

#: This file names the phrases in order to search for them.
ALLOWED = {"test_copy_matches_reality.py"}

#: (filename, phrase, reason) - a SINGLE phrase in a single file, never the
#: whole file. A file-level exemption is what re-admitted this defect once
#: before: the original string lived in `metrics.py`, and excluding
#: `metrics.py` would have hidden the string along with the comment explaining
#: it.
#:
#: Every entry must carry the condition under which it stops being true, and
#: `test_no_exemption_outlives_its_reason` FAILS once the string is gone - so
#: an entry cannot quietly become a permanent licence. Deleting the entry is
#: part of landing the capability, and the suite says so rather than a comment
#: hoping somebody remembers.
EXEMPTIONS = [
    (
        "SummaryCard.tsx",
        r"is not available",
        "True until stage 3 (single-batch synthesis) lands. The component "
        "renders it ONLY when not_implemented_sections includes 'synthesis', "
        "so the string is driven by the API and stops appearing the moment the "
        "backend claims the capability. Remove this entry when stage 3 "
        "commits.",
    ),
]

#: A COMMENT may say a claim used to be made - that is the fix, not the bug.
#: Excluding whole FILES instead would have been useless here: the original
#: string lived in metrics.py, and metrics.py now also carries the comment
#: explaining it, so a file-level exception would have re-admitted exactly the
#: defect this test exists to catch. Only the comment is exempt, never the
#: string a reader can see.
_COMMENT = re.compile(r"^\s*(#|//|\*|/\*)")

#: Block comments span lines, so a continuation line inside `{/* ... */}` or
#: a docstring does not itself start with a marker. They are blanked out
#: BEFORE scanning, preserving line numbers so a hit still reports where it is.
_JSX_BLOCK = r"\{?/\*.*?\*/\}?"
_PY_DOC = '\"\"\".*?\"\"\"'
_BLOCK = re.compile(_JSX_BLOCK + '|' + _PY_DOC, re.S)


def _without_block_comments(text: str) -> str:
    NL = chr(10)
    return _BLOCK.sub(lambda m: NL * m.group(0).count(NL), text)


def _sources():
    for root in SEARCHED:
        for path in root.rglob("*"):
            if path.suffix not in {".py", ".ts", ".tsx"}:
                continue
            if ".test." in path.name or "__pycache__" in str(path):
                continue
            yield path


@pytest.mark.parametrize("phrase", DENIALS)
def test_no_shipped_capability_is_described_as_missing(phrase):
    rx = re.compile(phrase, re.I)
    hits = []
    for path in _sources():
        if path.name in ALLOWED:
            continue
        if any(name == path.name and pattern == phrase
               for name, pattern, _ in EXEMPTIONS):
            continue
        body = _without_block_comments(path.read_text(encoding="utf-8"))
        for n, line in enumerate(body.splitlines(), 1):
            if _COMMENT.match(line):
                continue
            if rx.search(line):
                hits.append(f"{path.relative_to(ROOT)}:{n}: {line.strip()[:90]}")
    assert not hits, (
        f"copy asserts a capability is absent ({phrase!r}). If it genuinely is "
        f"absent, add (filename, phrase, reason) to EXEMPTIONS - the reason "
        f"must say when it stops being true:\n  "
        + "\n  ".join(hits)
    )


@pytest.mark.parametrize("name,phrase,reason", EXEMPTIONS)
def test_no_exemption_outlives_its_reason(name, phrase, reason):
    """An exemption whose string has gone is a licence nobody is using.

    This is the expiry mechanism. When stage 3 lands and SummaryCard stops
    saying the synthesis is unavailable, this test goes red and the entry has
    to be deleted - which is the point. A comment saying "remove this later"
    is not a mechanism, and this file already records what happens to
    documented hazards that are not guards.
    """
    rx = re.compile(phrase, re.I)
    for path in _sources():
        if path.name != name:
            continue
        body = _without_block_comments(path.read_text(encoding="utf-8"))
        if any(rx.search(line) for line in body.splitlines()
               if not _COMMENT.match(line)):
            return
    pytest.fail(
        f"EXEMPTIONS still allows {phrase!r} in {name}, but the string is no "
        f"longer there. Delete the entry. Its reason was: {reason}"
    )


def test_every_exemption_states_when_it_expires():
    """A reason without a condition is a permanent exemption in disguise."""
    for name, phrase, reason in EXEMPTIONS:
        assert len(reason) > 60, f"{name}: {phrase!r} has no real reason"
        assert "when" in reason.lower() or "until" in reason.lower(), (
            f"{name}: {phrase!r} does not say when it stops being true"
        )


def test_the_dashboard_ocr_alert_never_claims_ocr_is_unimplemented(tmp_path,
                                                                   monkeypatch):
    """The specific string, asserted by ABSENCE at its source.

    The parametrised sweep above catches the phrase in source text. This one
    catches it in a generated message, which is where it actually lived - the
    Dashboard renders whatever the API sends, so the copy was never in the
    frontend at all.
    """
    from app import db, metrics
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    conn = db.connect()
    with conn:
        conn.execute(
            """INSERT INTO documents (id, filename, sha256, size_bytes,
                   stored_path, page_count, status, needs_ocr_pages,
                   recognised_pages, uploaded_at)
               VALUES ('d1','s.pdf','x',1,'/x',89,'ready',89,89,
                       '2026-01-01T00:00:00Z')""")

    messages = " ".join(a["message"] for a in metrics.warnings())
    assert "not implemented" not in messages.lower(), messages
    assert "not searchable" not in messages.lower(), (
        "89 of 89 pages were recognised and the alert still says they are not "
        f"searchable: {messages}")
    db.reset_connection()


def test_pages_still_awaiting_recognition_do_produce_a_warning(tmp_path,
                                                               monkeypatch):
    """The other half: narrowing the alert must not silence it. Work that is
    genuinely outstanding is still a warning."""
    from app import db, metrics
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "t2.sqlite")
    db.reset_connection()
    db.init_db()
    conn = db.connect()
    with conn:
        conn.execute(
            """INSERT INTO documents (id, filename, sha256, size_bytes,
                   stored_path, page_count, status, needs_ocr_pages,
                   recognised_pages, uploaded_at)
               VALUES ('d1','s.pdf','y',1,'/y',89,'ready',89,2,
                       '2026-01-01T00:00:00Z')""")
    codes = {a["code"]: a for a in metrics.warnings()}
    assert "needs_ocr" in codes, "outstanding recognition work was silenced"
    assert "87" in codes["needs_ocr"]["message"], codes["needs_ocr"]["message"]
    db.reset_connection()
