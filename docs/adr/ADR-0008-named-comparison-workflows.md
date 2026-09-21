# ADR-0008: Named engineering comparison workflows

## Decision

Gap analysis accepts an explicit comparison intent from a controlled vocabulary:
baseline vs submittal, requirements vs submittal, revision delta, and
discipline coordination. The intent is metadata for the review and report; it
does not override evidence or invent a baseline.

## Consequences

The UI and report templates can present a review-specific workflow instead of
asking engineers to encode intent in free text. Unknown workflow labels fail
validation at the API boundary.
