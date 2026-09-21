# ADR-0009: Idempotent scheduled management summaries

## Decision

Daily and weekly management summaries are an opt-in job function driven by
UTC configuration. Each reporting window is recorded before delivery to make
repeated worker ticks idempotent; failed or disabled delivery releases the
reservation. Delivery reuses the existing SMTP validation and audit event.

## Consequences

The deployment may use its existing worker or an external scheduler without
starting a second daemon in the application process. SMTP remains disabled by
default for the local-only product.
