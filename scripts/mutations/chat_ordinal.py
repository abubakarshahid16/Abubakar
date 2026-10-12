"""Mutations of the chat message ordinal (load-test finding, 2026-09-29)."""
from __future__ import annotations

from ._base import APP, Mutation

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1384", phase=1384,
             description="every message in a conversation takes ordinal 1",
             path=APP / "chat.py",
             anchor="               SELECT ?, ?, COALESCE(MAX(ordinal), 0) + 1, ?, ?, ?, ?, ?, ?, ?, ?, ?",
             replacement="               SELECT ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?",
             target="tests/test_chat_message_ordinal_race.py",
             keyword="all_land_in_order or carries_the_ordinal", tags=("reliability",)),
)
