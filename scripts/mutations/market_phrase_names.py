"""Honesty audit 67: a file name typed with spaces, hyphens, underscores or dots never leaves."""
from __future__ import annotations

from ._base import APP, Mutation

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1011", phase=86, description='a file name typed with separators is not removed',
             path=APP / 'market_phrase.py',
             anchor='        pattern = _flexible_name(str(raw or ""))\n        if pattern is not None:\n            text = pattern.sub(" ", text)\n',
             replacement='        pass\n',
             target='tests/test_phrase_filename_variants.py', keyword='every_typed_form or never_offers', tags=("privacy", "critical")),
    Mutation(id="M1012", phase=86, description='hyphens, underscores and dots are not treated as separators',
             path=APP / 'market_phrase.py',
             anchor='_NAME_GAP = r"[\\s._-]*"\n',
             replacement='_NAME_GAP = r"[\\s]*"\n',
             target='tests/test_phrase_filename_variants.py', keyword='every_typed_form', tags=("privacy", "critical")),
    Mutation(id="M1013", phase=86, description='the public-standard exception swallows any file starting with a standard',
             path=APP / 'market_phrase.py',
             anchor='    return all(p.lower() in _SERIES or re.fullmatch(r"[A-Za-z]{0,3}\\d{1,6}[A-Za-z]?", p)\n               for p in parts[1:])\n',
             replacement='    return True\n',
             target='tests/test_phrase_filename_variants.py', keyword='exception_stops_at_the_standard', tags=("privacy", "critical")),
)
