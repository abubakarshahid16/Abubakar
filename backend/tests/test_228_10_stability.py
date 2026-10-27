"""Order 228.10: the same input gives the same facts, findings and verdicts.

One review of invented data (rule readers over a drawn PDF, a scripted engine,
the comparison against twelve requirements, two of them with conflicting values)
runs in separate processes under different PYTHONHASHSEED values and twice under
one. The dumps must match byte for byte. A difference means some step orders its
output by something that is not the input (a set, a dict built from one, a tie
decided by arrival), which is exactly what makes a client's second review of one
sheet differ from the first.

NOT covered, by design: the model. With a real engine two answers to one prompt
can differ (batching, floating point); the app already stores each answer and
reuses it for the same question (`AI_ANSWER_REUSE_ENABLED`), and a run-to-run
measurement with it off is s2's (counts only). No model is asked here.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PROBE = Path(__file__).resolve().parent / "stability_probe.py"


def _dump(tmp_path: Path, name: str, hashseed: int, **env) -> str:
    out = tmp_path / f"{name}.json"
    run = subprocess.run(
        [sys.executable, "-I", str(PROBE), str(out)],
        env={**os.environ, "PYTHONHASHSEED": str(hashseed), **env},
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert run.returncode == 0, run.stderr[-800:]
    return out.read_text()


def test_the_same_review_gives_the_same_facts_findings_and_verdicts(tmp_path):
    first = _dump(tmp_path, "a", 0)
    again = _dump(tmp_path, "b", 0)
    others = [_dump(tmp_path, f"h{seed}", seed) for seed in (1, 2, 3)]
    body = json.loads(first)
    # not vacuous: real facts, a finding per requirement, the conflicts sent to the engineer
    assert len(body["facts"]) >= 10 and len(body["findings"]) >= 12
    statuses = {row[0].split(" shall")[0]: row[2] for row in body["findings"] if row[0]}
    assert (
        statuses["Design pressure"] == "NEEDS_ENGINEER_REVIEW"
    )  # 9 and 12 barg: two values
    assert statuses["Noise level"] == "NON_COMPLIANT"
    assert first == again
    for other in others:
        assert other == first


def test_the_harness_itself_notices_a_difference(tmp_path):
    """A set of strings is ordered by the hash seed: the dumps must then differ,
    or the comparison above compares nothing."""
    dumps = {
        _dump(tmp_path, f"x{seed}", seed, STABILITY_PROBE_BREAK="1")
        for seed in (0, 1, 2, 3)
    }
    assert len(dumps) > 1
