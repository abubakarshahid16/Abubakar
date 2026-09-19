# Gold set

Hand-checked ground truth: what a standard actually says, written down by an
engineer, so the extractor can be measured against it.

- **Filling one in:** `docs/gold-set.md`. Written for the engineer; no code.
- **Scoring:** `python scripts/gold_score.py <database> gold/*.csv`

## Why the filled files are not committed

`.gitignore` keeps `gold/*.csv` out of the repository except `TEMPLATE.csv`.
The format asks for a clause number and a page rather than the sentence, so a
filled sheet holds no standard text - but it is still a description of a
client's standards, and this project's rule is that such material lives in the
local database and not in git. Keep the filled sheets beside the database.

Nothing in the test suite depends on a filled sheet existing.
