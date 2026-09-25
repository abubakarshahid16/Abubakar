"""The register importer, against a fixture PDF this file builds.

THE CLIENT'S REGISTER IS NEVER HERE. It is client material: not committed, not
copied into the repo, and nothing in this suite reads it. The fixture below is
constructed in a temp directory on every run, which is also the only way these
tests can pass on a clean clone.

THE FIXTURE VARIES ITS COLUMN WIDTHS BY PAGE, deliberately, because that is
the property the importer exists to survive. A register whose columns are in
the same place on every page would let a fixed-x-position parser pass this
suite and then mis-split the client's page 7 - quietly, producing a discipline
like "Process (AXE" and a title beginning "NS)". An hour was lost to exactly
that, so the fixture reproduces it.
"""

from __future__ import annotations

# scripts/ is not a package, so it is put on the path explicitly. Done here
# rather than in conftest so this file is self-contained: it is the only test
# module that needs the importer.
import sys
from pathlib import Path

import pymupdf
import pytest

from app import classification, db
from app.config import settings
from app.db import connect

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))
import import_register

# --------------------------------------------------------------- the fixture

#: Three types, NINE disciplines - two carrying a vendor inside the label, as
#: the register writes it.
#:
#: Nine rather than the six this started with, because `MIN_DISCIPLINES` is 8
#: and the guard is right: learning six disciplines from a 1,354-row register
#: would mean the middle column was not found. The fixture was the thing that
#: was unrepresentative, so it grew rather than the guard shrinking. Every one
#: appears at least `MIN_DISCIPLINE_OCCURRENCES` times across the 40 rows.
#:
#: "Process" and "Process (AXENS)" are BOTH here on purpose: they are two
#: different disciplines in the register, not one with a vendor attribute, and
#: a parser that stripped the vendor would collapse them into one.
DISCIPLINES = (
    "Process (AXENS)",
    "Process",
    "Piping",
    "Electrical (SIEMENS)",
    "Instrumentation",
    "Civil",
    "Mechanical",
    "Structural",
    "Telecom",
)

#: Titles carrying subject terms the importer should derive, plus some that
#: carry none - a register is not uniformly tidy and the derivation must not
#: depend on it being so.
TITLES = (
    "Hot Oil System P&ID",
    "Hot Oil Circulation Pump Datasheet",
    "Firewater Ring Main Layout",
    "Firewater Pump House Plot Plan",
    "MEG Regeneration Package Specification",
    "MEG Injection Philosophy",
    "Flare Header Sizing Calculation",
    "Flare Knock Out Drum Datasheet",
    "Substation Single Line Diagram",
    "Substation Earthing Layout",
    "Beach Valve Station Plot Plan",
    "Produced Water Treatment Report",
    "Diesel Storage Tank Datasheet",
    "Seawater Intake Screen Specification",
    "Cooling Water Circulation P&ID",
    "Potable Water Distribution Layout",
    "Instrument Air Compressor Datasheet",
    "Nitrogen Generation Package Specification",
    "Fuel Gas Conditioning Skid P&ID",
    "Condensate Stabilisation Overall Block Diagram",
    "Chemical Injection Skid Datasheet",
    "Methanol Injection Philosophy",
    "HVAC Design Criteria",
    "Gas Detection Layout Example Field",
    "Fire Alarm Cause and Effect North Terminal",
    "Pipeline Route Drawing JV-DEMO",
    "South Ridge Field Overall Block Diagram",
    "Onshore Receiving Facility Scope of Work",
    "Offshore Platform Topside Layout",
    "Wellhead Platform Structural Calculation",
    "Design Basis Memorandum",
    "Overall Project Execution Philosophy",
    "Corrosion Inhibitor Injection Report",
    "Steam Tracing Specification",
    "Emergency Power Generator Datasheet",
    "UPS Distribution Single Line Diagram",
    "Lighting Layout Substation",
    "Telecom Backbone Specification",
    "Water Injection Manifold P&ID",
    "Slug Catcher Sizing Calculation",
)


def build_register_pdf(path: Path, rows: list[tuple[str, str, str]],
                       rows_per_page: int = 12) -> None:
    """A three-column register whose column x positions CHANGE per page.

    Page 0 uses one set of x offsets, page 1 a noticeably different set, and so
    on. The gaps stay wider than `COLUMN_GAP` so the clustering can still find
    three columns - which is the point: the parser must find them from each
    page rather than from a remembered position.
    """
    layouts = [
        (40, 130, 300),
        (30, 190, 380),
        (55, 150, 260),
    ]
    document = pymupdf.open()
    for start in range(0, len(rows), rows_per_page):
        page = document.new_page(width=612, height=792)
        x_type, x_disc, x_title = layouts[
            (start // rows_per_page) % len(layouts)]
        y = 70.0
        page.insert_text((x_type, 40), "Type", fontsize=9)
        page.insert_text((x_disc, 40), "Discipline", fontsize=9)
        page.insert_text((x_title, 40), "Title", fontsize=9)
        for doc_type, discipline, title in rows[start:start + rows_per_page]:
            page.insert_text((x_type, y), doc_type, fontsize=8)
            page.insert_text((x_disc, y), discipline, fontsize=8)
            page.insert_text((x_title, y), title, fontsize=8)
            y += 18.0
    document.save(path)
    document.close()


def register_rows() -> list[tuple[str, str, str]]:
    """40 rows: every discipline used enough times to be learned, and all
    three types present."""
    types = ("Document", "Drawing", "LicensorFinalBEP")
    out: list[tuple[str, str, str]] = []
    for index, title in enumerate(TITLES):
        out.append((types[index % 3], DISCIPLINES[index % len(DISCIPLINES)],
                    title))
    return out


#: Facility names are the client's, read at import time from a local,
#: git-ignored config (scripts/register_facilities.local.json) that will not
#: exist on every machine this suite runs on. Fixed here so the suite is
#: deterministic regardless of what, if anything, that file contains.
FAKE_FACILITIES = ("Example Field", "North Terminal", "JV-DEMO", "South Ridge",
                    "onshore", "offshore")


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    monkeypatch.setattr(import_register, "CANDIDATE_FACILITIES", FAKE_FACILITIES)
    db.reset_connection()
    db.init_db()
    yield
    db.reset_connection()


@pytest.fixture
def register_pdf(tmp_path):
    path = tmp_path / "register-fixture.pdf"
    build_register_pdf(path, register_rows())
    return path


# ------------------------------------------------------------- the parse


def test_the_fixture_really_does_vary_its_columns_by_page(register_pdf):
    """A GUARD ON THE FIXTURE. If the layouts ever collapse to one, every
    test below would pass on a fixed-x parser and prove nothing about the
    property they exist for."""
    document = pymupdf.open(register_pdf)
    try:
        starts = []
        for page in document:
            rows = import_register.columns_on_page(page)
            data = [r for r in rows if r and r[0][1].strip() in
                    {"Document", "Drawing", "LicensorFinalBEP"}]
            assert data, "a page produced no data rows"
            starts.append(round(data[0][1][0]))
        assert len(set(starts)) > 1, (
            f"every page puts the discipline column at the same x ({starts}); "
            f"the fixture no longer exercises varying widths")
    finally:
        document.close()


def test_the_three_columns_parse_with_the_vendor_inside_the_label(register_pdf):
    rows, disciplines, problems, _unknown = import_register.parse(register_pdf)

    assert len(rows) == len(TITLES), (len(rows), problems[:5])
    assert problems == [], problems
    assert sorted({r["doc_type"] for r in rows}) == [
        "Document", "Drawing", "LicensorFinalBEP"]

    # THE VENDOR IS INSIDE THE DISCIPLINE, exactly as the register writes it.
    labels = {r["discipline"] for r in rows}
    assert "Process (AXENS)" in labels, sorted(labels)
    assert "Electrical (SIEMENS)" in labels, sorted(labels)
    # ...and is NOT split out of it: "Process" and "Process (AXENS)" are two
    # different disciplines, not one with a vendor attribute.
    assert "Process" in labels and "Process (AXENS)" in labels

    vendored = {r["discipline"]: r["vendor"] for r in rows}
    assert vendored["Process (AXENS)"] == "AXENS"
    assert vendored["Electrical (SIEMENS)"] == "SIEMENS"
    assert vendored["Piping"] is None
    assert set(disciplines) == set(DISCIPLINES), sorted(disciplines)


def test_a_title_is_kept_whole_across_column_clustering(register_pdf):
    rows, _d, _p, _u = import_register.parse(register_pdf)
    titles = {r["title"] for r in rows}
    for expected in ("Hot Oil System P&ID",
                     "Condensate Stabilisation Overall Block Diagram",
                     "Fire Alarm Cause and Effect North Terminal"):
        assert expected in titles, (expected, sorted(titles)[:5])


# ------------------------------------------------------- the derived subjects


def test_the_subject_vocabulary_is_derived_and_contains_project_wide(
        register_pdf):
    rows, _d, _p, _u = import_register.parse(register_pdf)
    subjects = import_register.derive_subjects([r["title"] for r in rows], [])

    names = {s["name"] for s in subjects}
    kinds = {s["name"]: s["kind"] for s in subjects}

    assert classification.PROJECT_WIDE in names, sorted(names)
    assert kinds[classification.PROJECT_WIDE] == "project_wide"

    # Systems the titles actually contain.
    for system in ("hot oil", "firewater", "MEG", "flare", "substation",
                   "beach valve station", "produced water", "diesel"):
        assert system in names, (system, sorted(names))
        assert kinds[system] == "system"

    # Facilities, kinded separately - they are places, not systems, and gap
    # analysis treats them differently.
    for facility in ("Example Field", "JV-DEMO", "South Ridge", "onshore", "offshore"):
        assert facility in names, (facility, sorted(names))
        assert kinds[facility] == "facility"

    assert len(subjects) >= import_register.MIN_SUBJECTS, len(subjects)


def test_a_term_absent_from_every_title_is_not_emitted():
    """DERIVED, not asserted. The candidate list is what is looked FOR; the
    vocabulary is what the titles actually contain."""
    subjects = import_register.derive_subjects(
        ["Hot Oil System P&ID", "Firewater Ring Main Layout"], [])
    names = {s["name"] for s in subjects}
    assert "hot oil" in names and "firewater" in names
    for absent in ("MEG", "flare", "South Ridge", "nitrogen"):
        assert absent not in names, (
            f"{absent!r} was emitted although no title mentions it")


def test_extra_candidate_terms_are_honoured():
    subjects = import_register.derive_subjects(
        ["Sulphur Recovery Unit P&ID"], ["sulphur recovery"])
    assert "sulphur recovery" in {s["name"] for s in subjects}


# --------------------------------------------------------------- refusals


def test_an_unknown_type_is_refused(tmp_path):
    """A type outside the register's three means the parse has gone wrong or
    the register has changed. Both need a human."""
    rows = register_rows()
    rows[0] = ("Datasheet", "Piping", "Something Or Other")
    path = tmp_path / "bad-type.pdf"
    build_register_pdf(path, rows)

    parsed, disciplines, problems, unknown = import_register.parse(path)

    # The bad row never becomes a register row...
    assert all(r["doc_type"] in import_register.KNOWN_TYPES for r in parsed)
    # ...and it is REPORTED rather than folded into the row count. That
    # distinction is the whole point: one dropped row of 1,354 is 0.07%, well
    # inside the 5% tolerance, so a register that had quietly grown a fourth
    # type would otherwise import clean and nobody would learn about it.
    assert unknown == ["Datasheet"], (unknown, problems[:3])

    with pytest.raises(SystemExit, match="outside the register's three"):
        import_register.check(parsed, disciplines,
                              import_register.derive_subjects(
                                  [r["title"] for r in parsed], []),
                              problems, expected=len(parsed),
                              unknown_types=unknown)


def test_a_type_that_reaches_the_row_list_is_refused_by_name():
    """The guard itself, independent of parsing: if a fourth type ever gets
    past the parser, `check` names it and writes nothing."""
    rows = [{"doc_type": "Datasheet", "discipline": "Piping",
             "vendor": None, "title": "x"}]
    with pytest.raises(SystemExit, match="outside the register's three"):
        import_register.check(rows, list(DISCIPLINES),
                              [{"name": f"s{i}", "kind": "system"}
                               for i in range(25)], [], expected=1)


def test_a_short_row_count_is_refused(register_pdf):
    """A HALF-PARSED REGISTER IMPORTED SILENTLY IS WORSE THAN A FAILED
    IMPORT: everything downstream classifies against a corpus quietly missing
    rows."""
    rows, disciplines, _p, _u = import_register.parse(register_pdf)
    subjects = import_register.derive_subjects([r["title"] for r in rows], [])
    with pytest.raises(SystemExit, match="parsed 40 rows, expected about 1354"):
        import_register.check(rows, disciplines, subjects, [], expected=1354)


def test_a_thin_subject_vocabulary_is_refused(register_pdf):
    rows, disciplines, _p, _u = import_register.parse(register_pdf)
    thin = [{"name": "hot oil", "kind": "system"},
            {"name": classification.PROJECT_WIDE, "kind": "project_wide"}]
    with pytest.raises(SystemExit, match="derived only 2 subjects"):
        import_register.check(rows, disciplines, thin, [], expected=len(TITLES))


def test_an_implausible_discipline_count_is_refused(register_pdf):
    """Learning two disciplines from a 1,354-row register means the middle
    column was not found. Refused rather than imported as a two-discipline
    project."""
    rows, _d, _p, _u = import_register.parse(register_pdf)
    subjects = import_register.derive_subjects([r["title"] for r in rows], [])
    with pytest.raises(SystemExit, match="learned 2 disciplines"):
        import_register.check(rows, ["Piping", "Civil"], subjects, [],
                              expected=len(TITLES))


def test_a_one_off_string_never_becomes_a_discipline(tmp_path):
    """MIN_DISCIPLINE_OCCURRENCES. A mis-split or a typo appears once; a real
    discipline labels dozens of deliverables."""
    rows = register_rows()
    rows[0] = ("Document", "Prcoess (AXENS)", "Typo Discipline Row")
    path = tmp_path / "typo.pdf"
    build_register_pdf(path, rows)

    parsed, disciplines, problems, _unknown = import_register.parse(path)
    assert "Prcoess (AXENS)" not in disciplines, disciplines
    # The row is reported rather than imported with a broken discipline.
    assert any("not in the learned vocabulary" in p for p in problems), problems
    assert all(r["discipline"] != "Prcoess (AXENS)" for r in parsed)


# ------------------------------------------------------------- idempotence


def test_importing_the_same_revision_twice_is_idempotent(register_pdf):
    rows, _disciplines, _p, _u = import_register.parse(register_pdf)
    subjects = import_register.derive_subjects([r["title"] for r in rows], [])

    first = import_register.store(rows, subjects, "rev-A")
    second = import_register.store(rows, subjects, "rev-A")
    assert first == second, (first, second)

    conn = connect()
    assert conn.execute(
        "SELECT COUNT(*) FROM deliverables_register WHERE register_revision='rev-A'"
    ).fetchone()[0] == len(rows)
    assert conn.execute(
        "SELECT COUNT(*) FROM subjects WHERE register_revision='rev-A'"
    ).fetchone()[0] == len(subjects)


def test_a_new_revision_keeps_the_old_one(register_pdf):
    """Documents already classified against rev-A must keep the register they
    were classified against, or the record of what they were compared with
    changes underneath them."""
    rows, _d, _p, _u = import_register.parse(register_pdf)
    subjects = import_register.derive_subjects([r["title"] for r in rows], [])

    import_register.store(rows, subjects, "rev-A")
    import_register.store(rows[:20], subjects, "rev-B")

    conn = connect()
    counts = {r[0]: r[1] for r in conn.execute(
        "SELECT register_revision, COUNT(*) FROM deliverables_register"
        " GROUP BY register_revision")}
    assert counts == {"rev-A": len(rows), "rev-B": 20}, counts

    # And the newest revision is the one classification reads.
    assert classification.register_revision() == "rev-B"


def test_the_end_to_end_import_writes_and_reports(register_pdf, capsys):
    """`main` with the fixture's own expected count, which is what makes the
    1,354 guard testable rather than something to be disabled."""
    code = import_register.main([str(register_pdf), "rev-C",
                                 "--expect", str(len(TITLES))])
    assert code == 0
    out = capsys.readouterr().out
    assert f"parsed          : {len(TITLES)} rows" in out, out
    assert "Process (AXENS)" in out and "[vendor: AXENS]" in out, out
    assert classification.register_revision() == "rev-C"

    vocabulary = classification.vocabulary()
    assert set(vocabulary["types"]) == {"Document", "Drawing", "LicensorFinalBEP"}
    assert "Process (AXENS)" in vocabulary["disciplines"]
    assert classification.PROJECT_WIDE in {s["name"] for s in vocabulary["subjects"]}


def test_a_dry_run_writes_nothing(register_pdf, capsys):
    code = import_register.main([str(register_pdf), "rev-D",
                                 "--expect", str(len(TITLES)), "--dry-run"])
    assert code == 0
    assert "nothing written" in capsys.readouterr().out
    assert connect().execute(
        "SELECT COUNT(*) FROM deliverables_register").fetchone()[0] == 0
