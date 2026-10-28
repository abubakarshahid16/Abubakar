"""The local tool that says what a change to field_synonyms.json did to a sheet's own field names. Invented labels."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import synonym_effect


def _table(tmp_path, name, groups):
    path = tmp_path / name
    path.write_text(
        json.dumps({"groups": groups, "nozzle_attributes": []}), encoding="utf-8"
    )
    return path


def test_it_counts_changed_names_and_merges_and_prints_no_name_without_show(
    tmp_path, capsys
):
    old = _table(tmp_path, "old.json", {"design pressure": ["design press"]})
    new = _table(
        tmp_path,
        "new.json",
        {
            "design pressure": ["design press"],
            "relieving temperature": ["relieving temp", "relief temp"],
        },
    )
    names = tmp_path / "names.csv"
    names.write_text(
        "field name\nRelieving Temp.\nRelief temp\nDesign Press\nSet pressure\n",
        encoding="utf-8",
    )
    assert (
        synonym_effect.main(
            ["--old", str(old), "--new", str(new), "--names", str(names)]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "names: 4" in out
    assert "fold to a different text: 2" in out
    assert "groups that now fold together (merges): 1" in out
    assert "Relief" not in out and "Relieving" not in out
    synonym_effect.main(
        ["--old", str(old), "--new", str(new), "--names", str(names), "--show"]
    )
    shown = capsys.readouterr().out
    assert "merged: ['Relief temp', 'Relieving Temp.']" in shown


def test_an_unchanged_table_changes_and_merges_nothing(tmp_path):
    table = _table(tmp_path, "t.json", {"design pressure": ["design press"]})
    result = synonym_effect.effect(table, table, ["Design Press", "Set pressure"])
    assert result["changed"] == [] and result["merged"] == []
