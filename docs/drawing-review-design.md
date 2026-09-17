# Drawing review design (GPU-gated)

This is a design boundary for a future drawing/diagram review capability. It is
not an implementation and does not claim that the current CPU-only deployment
can interpret engineering drawings.

## Ingestion boundary

The existing PDF ingestion pipeline extracts each page and records page-level
quality metadata. A page whose extraction is primarily an image, has low text
coverage, or contains a drawing classification should be marked
`vision_required=true`. The page remains searchable by its extracted text and
is queued for a future vision worker; normal text pages continue through the
existing keyword, embedding, and review paths.

## Review contract

The future vision worker should accept a document id, page number, page image
hash, drawing classification, and optional project discipline. It should return
structured observations, not an unbounded paragraph:

```json
{
  "document_id": "doc_...",
  "page": 12,
  "observations": [{
    "type": "missing_dimension",
    "severity": "major",
    "location": {"x": 0.42, "y": 0.31, "width": 0.18, "height": 0.08},
    "description": "Dimension is not shown for the identified opening.",
    "required_action": "Provide or reference the governing dimension.",
    "confidence": 0.86
  }],
  "model": "vision-model-id",
  "model_version": "..."
}
```

Each observation becomes a normal review finding. Its citation is a drawing
citation (`document`, `page`, `region`, and image hash) rather than a quoted
text span. The UI should show a page thumbnail with the highlighted region,
the finding severity, confidence, required action, owner, and response state.
The existing traceability chain remains unchanged after the citation node:
Finding → Drawing page/region → Baseline → Deliverable → Owner → Action.

## Comparison and safety rules

Drawing findings must be compared against an explicitly selected baseline or
standard drawing. The system must not invent a baseline. Low-confidence
observations are marked for engineer review and must not be presented as a
compliance conclusion. The qualified engineer remains the approver.

## Hardware gate

The current deployment has no GPU and this design intentionally stops at the
queue/API boundary. Implementation requires an approved vision model,
GPU-capable worker sizing, retention rules for rendered page images, and a
client-approved drawing test set.
