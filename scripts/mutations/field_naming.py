"""Mutations of `backend/app/field_naming.py` (#193 plan B4, 5.2/5.3)."""

from __future__ import annotations

from ._base import APP, Mutation


MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id='M591', phase=63,
        description='B4 5.3: numeric requirements are never named',
        path=APP / 'field_naming.py',
        anchor='    numeric = [r for r in requirements if r.get("requirement_type") in NUMERIC_TYPES]\n',
        replacement='    numeric = []\n',
        target='tests/test_field_naming.py',
        keyword='numeric_requirements_are_named',
        tags=('honesty',),
    ),
    Mutation(
        id='M597', phase=63,
        description='B4 5.2 gate 2: an unverified quote still maps a label',
        path=APP / 'field_naming.py',
        anchor='    if not quote_verified(quote, items[i][1]):\n',
        replacement='    if False:\n',
        target='tests/test_field_naming.py',
        keyword='unverified_quote',
        tags=('honesty', 'critical'),
    ),
    Mutation(
        id='M598', phase=63,
        description='B4 5.2 gate 3: a quote that does not name the field still maps it',
        path=APP / 'field_naming.py',
        anchor='    if not names_the_field(quote, dictionary[field]):\n',
        replacement='    if False:\n',
        target='tests/test_field_naming.py',
        keyword='does_not_name_the_field',
        tags=('honesty', 'critical'),
    ),
    Mutation(
        id='M654', phase=64,
        description='B4 item 2: a fact is no longer its own name (no code identity mapping)',
        path=APP / 'field_naming.py',
        anchor='            named = next((n for n in own_names(f) if n in received), None)\n',
        replacement='            named = None\n',
        target='tests/test_b4_quality.py', keyword='blank_fields_are_named',
    ),
)
