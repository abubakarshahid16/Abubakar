"""Which code read which input: provenance for extracted rows (issue #177).

OCR already records its engine, model and dpi. Fact and requirement
extraction recorded only `extraction_method`, so a row could not say which
version of the extractor wrote it or what it was read from - and every fix to
an extractor reaches the corpus by re-running it, so "was this row written
before or after the fix?" had no answer.

THE VERSION IS DERIVED, NEVER TYPED. A hand-maintained `VERSION = "1.2"`
constant is a claim somebody must remember to bump, and the day they forget
it states something false. The version here is a hash of the extractor's own
source files, so it changes exactly when the code does and cannot drift. It
is not a git commit: the machine this runs on need not have git.

THE INPUT HASH is sha256 over the stored file's own sha256 plus the chunk
text the extractor actually read, in order. Same file, same chunks, same
code -> same (version, input_hash), which is what "reproducible" means here.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

_APP = Path(__file__).resolve().parent


@lru_cache(maxsize=None)
def code_version(*modules: str) -> str:
    """`first+second@<12 hex>` over the named `app/` modules' source bytes."""
    digest = hashlib.sha256()
    for name in modules:
        digest.update(name.encode())
        digest.update(b"\0")
        digest.update((_APP / f"{name}.py").read_bytes())
    return f"{'+'.join(modules)}@{digest.hexdigest()[:12]}"


def input_hash(*parts: str | None) -> str:
    """sha256 hex over `parts`, NUL-separated so ("ab","c") != ("a","bc")."""
    digest = hashlib.sha256()
    for part in parts:
        digest.update((part or "").encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()
