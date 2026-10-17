"""#736 (F8): every boolean setting is in docs/flags.md, and a rollout flag
past its decide-by date fails CI."""
from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_flag_expiry.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_flag_expiry", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


HEAD = "| Flag | Default | Kind | Since | Decide by | Note |\n|---|---|---|---|---|---|\n"
ROLL = "| `new_path_enabled` | `False` | rollout | 2026-10-01 | 2026-10-15 | trial |\n"
GATE = "| `egress_enabled` | `False` | permanent | | | egress gate |\n"
FLAGS = {"new_path_enabled": "False", "egress_enabled": "False"}


def test_the_real_register_matches_config_today():
    assert _load().problems(date(2026, 10, 17)) == []


def test_a_rollout_flag_past_its_date_fails_and_on_its_date_passes():
    mod = _load()
    assert mod.problems(date(2026, 10, 15), HEAD + ROLL + GATE, FLAGS) == []
    (found,) = mod.problems(date(2026, 10, 16), HEAD + ROLL + GATE, FLAGS)
    assert "new_path_enabled: EXPIRED on 2026-10-15" in found


def test_a_permanent_flag_never_expires_but_needs_a_reason():
    mod = _load()
    assert mod.problems(date(2030, 1, 1), HEAD + GATE, {"egress_enabled": "False"}) == []
    (found,) = mod.problems(date(2030, 1, 1), HEAD + GATE.replace("egress gate", ""),
                            {"egress_enabled": "False"})
    assert "states why it stays a switch" in found


def test_a_window_longer_than_14_days_is_refused():
    row = ROLL.replace("2026-10-15", "2026-10-16")
    (found,) = _load().problems(date(2026, 10, 2), HEAD + row, {"new_path_enabled": "False"})
    assert "window is 15 days" in found


def test_missing_extra_and_changed_defaults_are_named():
    found = _load().problems(date(2026, 10, 2), HEAD + ROLL,
                             {"new_path_enabled": "True", "unlisted_enabled": "False"})
    assert "flag not in docs/flags.md: unlisted_enabled (default False)" in found
    assert "default differs for new_path_enabled: config.py True, docs/flags.md False" in found
    found = _load().problems(date(2026, 10, 2), HEAD + ROLL + GATE, {"new_path_enabled": "False"})
    assert "docs/flags.md lists a flag config.py does not have: egress_enabled" in found


def test_a_rollout_row_without_dates_and_an_unknown_kind_are_refused():
    mod = _load()
    bad = ("| `new_path_enabled` | `False` | rollout | | | trial |\n"
           "| `egress_enabled` | `False` | someday | | | x |\n")
    found = mod.problems(date(2026, 10, 2), HEAD + bad, FLAGS)
    assert any("needs `since` and `decide by`" in f for f in found)
    assert any("kind must be one of" in f for f in found)


def test_main_exits_1_on_an_expired_register(capsys):
    mod = _load()
    assert mod.main(["--today", "2026-10-17"]) == 0
    assert mod.main(["--today", "2026-11-01"]) == 1
    assert "EXPIRED on 2026-10-31" in capsys.readouterr().out
