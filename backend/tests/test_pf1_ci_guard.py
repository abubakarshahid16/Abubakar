"""The PF1 CPU workflow runs only invented tuning sheets in `tests/data/pf1/` (#881, order 171).

The guard is what stands between a GitHub runner and a held-out sheet, a sheet
planted against the library's standards, or a file outside the set folder.
Invented text only; nothing here reads a real document.
"""

from __future__ import annotations

import json

import pytest
from tools import pf1_ci_guard as guard


def _doc(name="pf1-01", **over):
    doc = {
        "id": name,
        "held_out": False,
        "group": "invented",
        "datasheet": f"{name}.datasheet.pdf",
        "standard": f"{name}.standard.pdf",
        "key": f"{name}.key.json",
    }
    doc.update(over)
    return doc


def _set(tmp_path, docs, **over):
    folder = tmp_path / guard.SET_DIR
    folder.mkdir(parents=True)
    for doc in docs:
        for field in ("datasheet", "standard", "key"):
            if doc.get(field) and isinstance(doc[field], str) and "/" not in doc[field]:
                (folder / doc[field]).write_bytes(b"x")
    index = {
        "format": guard.INDEX_FORMAT,
        "source": "invented",
        "documents": docs,
        **over,
    }
    (folder / "index.json").write_text(json.dumps(index))
    return folder


def test_the_tuning_sheets_make_the_matrix(tmp_path):
    folder = _set(tmp_path, [_doc("a"), _doc("b")])
    assert guard.plan(tmp_path, folder) == {"include": [{"id": "a"}, {"id": "b"}]}
    assert guard.plan(tmp_path, folder, ["b"]) == {"include": [{"id": "b"}]}


def test_a_held_out_sheet_stops_the_whole_run(tmp_path):
    folder = _set(tmp_path, [_doc("a"), _doc("b", held_out=True)])
    with pytest.raises(guard.Refused, match="b: held out"):
        guard.plan(tmp_path, folder)


def test_a_sheet_that_does_not_say_it_is_not_held_out_is_refused(tmp_path):
    doc = _doc("a")
    del doc["held_out"]
    folder = _set(tmp_path, [doc])
    with pytest.raises(guard.Refused, match="not stated"):
        guard.plan(tmp_path, folder)


def test_a_library_group_sheet_is_refused_because_it_carries_standard_text(tmp_path):
    folder = _set(tmp_path, [_doc("a", group="library")])
    with pytest.raises(guard.Refused, match="library sheets carry standard text"):
        guard.plan(tmp_path, folder)


@pytest.mark.parametrize(
    "name", ["../secret.pdf", "sub/x.pdf", "/etc/passwd", ".hidden", "", None]
)
def test_a_file_that_is_not_a_plain_name_inside_the_folder_is_refused(tmp_path, name):
    folder = _set(tmp_path, [_doc("a", datasheet=name)])
    with pytest.raises(guard.Refused, match="plain name"):
        guard.plan(tmp_path, folder)


def test_a_file_that_is_missing_is_refused(tmp_path):
    folder = _set(tmp_path, [_doc("a")])
    (folder / "a.key.json").unlink()
    with pytest.raises(guard.Refused, match="not a file inside the set folder"):
        guard.plan(tmp_path, folder)


def test_a_link_out_of_the_folder_is_refused(tmp_path):
    folder = _set(tmp_path, [_doc("a")])
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"real")
    (folder / "a.datasheet.pdf").unlink()
    (folder / "a.datasheet.pdf").symlink_to(outside)
    with pytest.raises(guard.Refused, match="not a file inside the set folder"):
        guard.plan(tmp_path, folder)


def test_only_the_tuning_folder_is_read(tmp_path):
    folder = _set(tmp_path, [_doc("a")])
    elsewhere = tmp_path / "other"
    elsewhere.mkdir()
    (elsewhere / "index.json").write_text((folder / "index.json").read_text())
    with pytest.raises(guard.Refused, match="no other folder goes to a runner"):
        guard.plan(tmp_path, elsewhere)
    with pytest.raises(guard.Refused, match="does not exist"):
        guard.plan(tmp_path / "nowhere", tmp_path / "nowhere" / guard.SET_DIR)


@pytest.mark.parametrize(
    "over", [{"format": "pf1-index/2"}, {"source": "real"}, {"documents": []}]
)
def test_an_index_that_is_not_an_invented_pf1_index_is_refused(tmp_path, over):
    folder = _set(tmp_path, [_doc("a")], **over)
    with pytest.raises(guard.Refused):
        guard.plan(tmp_path, folder)


def test_an_unknown_sheet_id_is_named(tmp_path):
    folder = _set(tmp_path, [_doc("a")])
    with pytest.raises(guard.Refused, match="not in the set: nope"):
        guard.plan(tmp_path, folder, ["nope"])


def test_an_unreadable_index_is_refused_without_its_text(tmp_path):
    folder = _set(tmp_path, [_doc("a")])
    (folder / "index.json").write_text("{not json")
    with pytest.raises(guard.Refused, match="could not be read"):
        guard.plan(tmp_path, folder)


@pytest.mark.parametrize("bad", ["A", "a b", "a;rm", "$(x)", "-a", "a/b", "", None])
def test_a_sheet_id_that_is_not_safe_in_a_job_name_and_a_shell_is_refused(
    tmp_path, bad
):
    folder = _set(tmp_path, [_doc("a", id=bad)])
    with pytest.raises(guard.Refused, match="sheet id"):
        guard.plan(tmp_path, folder)
