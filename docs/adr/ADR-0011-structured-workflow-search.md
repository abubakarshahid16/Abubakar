# ADR-0011: Structured workflow search

Search over EPC workflow records is separate from passage retrieval. The
structured endpoint searches WBS/deliverable fields and review finding fields,
and applies the caller's document scope before returning rows.
