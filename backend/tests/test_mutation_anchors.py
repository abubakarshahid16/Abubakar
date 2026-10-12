"""Every mutation anchor matches its target file exactly once.

`scripts/mutation_check.py` reports a mutation whose anchor matches 0 or 2+
times as a harness error, but only when that one mutation is run. Refactors
left about 17 such stale entries unnoticed. `scripts/check_mutation_anchors.py`
does the cheap part (no tests run) and this suite keeps the registry at zero
stale. Re-anchor a stale entry (see the dated "Re-anchored" notes in
`scripts/mutations/`) instead of weakening this test.
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import check_mutation_anchors as checker  # noqa: E402
import mutation_check  # noqa: E402
from mutations._base import Mutation  # noqa: E402


def _mutation(mid: str, path: Path, anchor: str) -> Mutation:
    return Mutation(id=mid, phase=0, description="synthetic", path=path,
                    anchor=anchor, replacement="x", target="tests/none.py")


def test_the_real_registry_has_no_stale_anchor():
    stale = checker.find_stale(mutation_check.ALL)
    assert [(m.id, why) for m, why in stale] == []
    assert len(mutation_check.ALL) > 1500, "the registry did not load"


def test_the_checker_reports_zero_one_many_and_missing_matches(tmp_path):
    target = tmp_path / "target.py"
    target.write_text("alpha = 1\nbeta = 2\nbeta = 2\n", encoding="utf-8")
    entries = (
        _mutation("S1", target, "alpha = 1"),              # exactly once: fine
        _mutation("S2", target, "gamma = 3"),              # zero matches
        _mutation("S3", target, "beta = 2"),               # two matches
        _mutation("S4", tmp_path / "gone.py", "alpha"),    # file missing
    )
    stale = {m.id: why for m, why in checker.find_stale(entries)}
    assert set(stale) == {"S2", "S3", "S4"}
    assert "0 times" in stale["S2"]
    assert "2 times" in stale["S3"]
    assert "file not found" in stale["S4"]


def test_the_checker_exits_nonzero_on_a_stale_registry(monkeypatch, tmp_path, capsys):
    target = tmp_path / "t.py"
    target.write_text("one\n", encoding="utf-8")
    monkeypatch.setattr(mutation_check, "ALL", (_mutation("S9", target, "two"),))
    assert checker.main() == 1
    assert "S9" in capsys.readouterr().out
