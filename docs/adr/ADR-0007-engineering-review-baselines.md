# ADR-0007: Configurable engineering-review baselines

## Decision

Baseline selection for engineering gap analysis is rule-driven, not inferred
from filenames or upload order. Rules match the classified submittal document
type and discipline to a baseline type and optional discipline, and are ordered
by explicit priority. Only searchable documents in the caller's access scope
are eligible. A manual baseline supplied by the reviewer always wins.

## Consequences

The product can provide a useful default for repeatable submittal reviews while
keeping authority auditable. A project administrator must configure mappings,
and an unmatched submittal still reports no baseline rather than inventing one.
