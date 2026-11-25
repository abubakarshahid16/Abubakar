"""The plan's "These will not be sent" list says each standard not held once (planner 18 Nov 23:40-7, seen on the live plan panel). Invented names."""

from __future__ import annotations

from app import review_leaving as RL


def _nh(name):
    return {"name": name, "kind": "rule book", "why": "w", "reason": RL.NOT_HELD}


def test_a_standard_not_held_is_listed_once_whatever_its_spelling():
    out = {
        "leaving": [],
        "not_sent": [
            _nh("QX 100 Part II"),
            _nh("QX 200"),
            _nh("QX 100 Pt-2"),  # the same part spelled another way
            _nh("QX-200"),  # the same number with a dash
            _nh("ZY 300 Invented Title"),
        ],
    }
    got = RL._finish(out)["not_sent"]
    assert [n["name"] for n in got] == [
        "QX 100 Part II",
        "QX 200",
        "ZY 300 Invented Title",
    ]


def test_a_document_not_sent_for_another_reason_is_never_dropped():
    held_not_sent = {
        "id": "doc_1",
        "title": "QX 200 held copy",
        "kind": "rule book",
        "why": "w",
        "reason": "a contract: the owner approves it",
    }
    out = {"leaving": [], "not_sent": [_nh("QX 200"), held_not_sent, _nh("QX-200")]}
    got = RL._finish(out)["not_sent"]
    assert held_not_sent in got and [
        n for n in got if n.get("reason") == RL.NOT_HELD
    ] == [_nh("QX 200")]
