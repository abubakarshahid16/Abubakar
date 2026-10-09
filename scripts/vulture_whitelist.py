"""Names vulture (the dead-code check in CI, #661) must not report.

Run as: python -m vulture backend/app scripts/vulture_whitelist.py --min-confidence 80

Each line below is a name that looks unused and is not. A bare name counts as a
use. Add one only with the reason, and only after proving it is used some other
way; a real unused variable gets deleted, not listed here.
"""
mtime_ns   # lru_cache KEY: the file's mtime makes a changed file miss the cache (datasheet_inputs)
mtime      # lru_cache KEY: same idiom (subject_scope vocabulary file, doc_router cues)
rect_num   # parameter the PDF library calls `rectfn` with; it must be accepted, not used (reports)
