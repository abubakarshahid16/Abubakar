# ADR-0018: Preserve recommendation refusal provenance

When advisory generation does not produce a recommendation, the backend's
reason is part of the typed response and is rendered directly by Analysis.
This distinguishes insufficient evidence, model refusal, and operational
limits without inventing a new explanation at the presentation layer.
