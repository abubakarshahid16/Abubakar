"""Two questions in the same conversation at the same moment.

Found by scripts/load_test.py (feat/load-test, 2026-09-29): at 20 concurrent
engineers the chat route answered HTTP 500 with
`sqlite3.IntegrityError: UNIQUE constraint failed: messages.conversation_id,
messages.ordinal` - 2 of 200 requests in one run, 7 in another. The next
ordinal was read with a SELECT before the INSERT took the write lock, so two
writers could read the same MAX(ordinal) and the second INSERT collided. When
the collision hit the ANSWER turn, the question was stored with no answer.
Real trigger: a second question sent before the first returns, or the same
chat open in two tabs.
"""
from __future__ import annotations

import sys
import threading

import pytest

from app import chat, db
from app.config import settings

THREADS = 8
ROUNDS = 15


@pytest.fixture
def conversation(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "chat.sqlite")
    db.reset_connection()
    db.init_db()
    conv = chat.create_conversation(title="race")["id"]
    db.reset_connection()
    yield conv
    db.reset_connection()


def test_concurrent_messages_in_one_conversation_all_land_in_order(conversation):
    old = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    failures: list[BaseException] = []
    lock = threading.Lock()
    try:
        for _ in range(ROUNDS):
            barrier = threading.Barrier(THREADS)

            def worker():
                db.reset_connection()   # each thread its own connection, as the server's
                try:
                    barrier.wait(timeout=30)
                    chat._insert_message(db.connect(), conversation,
                                         role="user", text="q")
                except BaseException as exc:  # noqa: BLE001 - recorded
                    with lock:
                        failures.append(exc)

            workers = [threading.Thread(target=worker) for _ in range(THREADS)]
            for w in workers:
                w.start()
            for w in workers:
                w.join(timeout=60)
    finally:
        sys.setswitchinterval(old)

    assert not failures, f"{len(failures)} of {THREADS * ROUNDS} inserts raised: {failures[0]!r}"
    conn = db.connect()
    ordinals = [r[0] for r in conn.execute(
        "SELECT ordinal FROM messages WHERE conversation_id = ? ORDER BY ordinal",
        (conversation,))]
    assert ordinals == list(range(1, THREADS * ROUNDS + 1))
    count = conn.execute("SELECT message_count FROM conversations WHERE id = ?",
                         (conversation,)).fetchone()[0]
    assert count == THREADS * ROUNDS


def test_the_returned_message_carries_the_ordinal_it_was_stored_under(conversation):
    first = chat._insert_message(db.connect(), conversation, role="user", text="a")
    second = chat._insert_message(db.connect(), conversation, role="assistant", text="b")
    assert (first["ordinal"], second["ordinal"]) == (1, 2)
