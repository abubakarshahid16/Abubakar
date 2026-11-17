"""General only (CLAUDE.md rule 13) and one number reader (no second one): checks on the general review's own source."""

from __future__ import annotations

import json
import re
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
PACKAGE = APP / "aim_review"
REF = APP / "reference"


def _source() -> str:
    return "\n".join(
        p.read_text(encoding="utf-8") for p in sorted(PACKAGE.glob("*.py"))
    )


def _equipment_words() -> set[str]:
    tax = json.loads((REF / "equipment_taxonomy.json").read_text(encoding="utf-8"))
    ids = {t["id"] for fam in tax["families"] for t in fam.get("types") or []}
    names = set(
        json.loads((REF / "equipment_mapping.json").read_text(encoding="utf-8"))["map"]
    )
    return ids | {i.replace("_", " ") for i in ids} | names


def _standard_names() -> set[str]:
    gov = json.loads((REF / "governing_standards.json").read_text(encoding="utf-8"))[
        "equipment_types"
    ]
    roles = json.loads((REF / "standard_roles.json").read_text(encoding="utf-8"))
    out = {s for books in gov.values() for s in books}
    out |= {
        s for books in (roles.get("method_standards") or {}).values() for s in books
    }
    return out | set(roles.get("standards") or {})


def test_the_package_names_no_equipment_type():
    src = _source().lower()
    words = _equipment_words()
    assert len(words) > 20, "the vocabulary was read"
    hits = [
        w
        for w in sorted(words)
        if re.search(r"(?<![a-z0-9_])" + re.escape(w.lower()) + r"(?![a-z0-9_])", src)
    ]
    assert hits == []


def test_the_package_names_no_standard():
    src = _source().lower()
    names = _standard_names()
    assert len(names) > 10, "the standards were read"
    assert [n for n in sorted(names) if n.lower() in src] == []
    families = {re.match(r"[A-Za-z]+", n).group(0) for n in names}
    numbered = [
        f
        for f in sorted(families)
        if re.search(r"(?<![a-z])" + f.lower() + r"[\s-]*(rp\s*)?\d", src)
    ]
    assert numbered == []


def test_the_vocabulary_check_would_catch_a_name(tmp_path):
    """The check is not vacuous: a forged source naming one type is caught by the same expression."""
    word = sorted(_equipment_words())[0]
    forged = f"def f():\n    return '{word}'\n".lower()
    assert re.search(
        r"(?<![a-z0-9_])" + re.escape(word.lower()) + r"(?![a-z0-9_])", forged
    )


def test_no_second_number_reader_in_the_package():
    """The CI rule (`test_w2_number_parser`) scans only `app/*.py`; this applies the SAME pattern to the package's files."""
    import importlib.util
    import sys

    test = Path(__file__).resolve().parent / "test_w2_number_parser.py"
    sys.path.insert(0, str(test.parents[1]))
    spec = importlib.util.spec_from_file_location("_w2_rules_for_aim", test)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    offenders = [
        p.name
        for p in sorted(PACKAGE.glob("*.py"))
        if module._PRIVATE_PARSER.search(p.read_text(encoding="utf-8"))
    ]
    assert offenders == []
    assert module._PRIVATE_PARSER.search('x = unicodedata.normalize("NFKC", s)\n'), (
        "the pattern is the real one"
    )


def test_the_package_converts_no_unit_itself():
    """Units go through the app's unit code (`claims`), never a table or a formula of the package's own."""
    src = _source()
    assert "claims.compare_across_units" in src and "claims._compatible" in src
    assert not re.search(r"\*\s*5\.0\s*/\s*9|273\.15|\b14\.50", src)
