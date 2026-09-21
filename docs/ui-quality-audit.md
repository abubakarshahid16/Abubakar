# UI and writing quality audit

Reviewed during the final close-out pass. Quick fixes are included in the
current branch; the remaining items need a product/design decision rather than
being hidden as implementation work.

## Fixed in this pass

- The Analysis entry point now explicitly labels the workflow **Document
  submittal review**.
- Traceability request failures now appear as a visible status message instead
  of leaving an empty panel.
- Review findings show an automatic-baseline badge and a manual override
  control when a matching rule exists.
- Baseline lookup failures are shown beside the baseline control.

## Design input still needed

- Focused and Comprehensive analysis currently show elapsed time but no stage
  progress or cancellation. A future UX decision is needed for progress and
  cancel semantics because the backend does not expose durable job stages.
- The browser session intentionally lives in memory, so reload signs the user
  out. Decide whether the client wants that privacy guarantee retained or a
  controlled session persistence model.
- Evidence-heavy review pages can become dense on smaller screens. A design
  pass should decide when conversation history, sources, and the review form
  collapse into drawers or tabs.
- Notification and escalation screens can show policy state without sending
  mail until an approved provider is configured. The UI should keep that
  distinction prominent in production deployments.

## Final screen sweep

On 2026-09-17, the authenticated navigation sweep reached Dashboard,
Documents, Chat, Analysis, Reports, Deliverables, Ingestion, and
Administration. Each screen rendered its expected heading and usable empty or
loaded state; no raw exception text or blank route was observed. The remaining
items above are deliberate design/provider decisions, not silently ignored
screen failures.
