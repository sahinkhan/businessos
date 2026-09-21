# Phase 1 tenant provider and durable-delivery boundary

Cache and object-storage calls retain their public `(tenant_id, key, ...)` signatures, but
the built-in Redis and S3 adapters now require the tenant ID to match the active trusted
`RequestContext`. Missing or mismatched context is rejected before any Redis or S3 request.
The framework also injects request-scoped tenant-bound views for these capabilities, including
deployment-supplied adapters, so an injected provider cannot be used for another tenant or
reused under a later request context. Infrastructure readiness and lifecycle operations remain
outside tenant data access. Direct command/query and job dispatch bind their supplied trusted
contexts while invoking handlers; HTTP and durable event delivery already bind their contexts.

Existing handlers that pass the current tenant ID need no signature change. A caller that used
an unbound adapter for tenant data must use a trusted framework request/delivery context or an
explicitly designed privileged operations path; a caller-supplied UUID alone is not authority.
No Phase 2 contract or schema changes are required.

New JetStream durables start at the beginning of retained stream history (`DeliverPolicy.ALL`),
so a first subscription or a deliberate durable-name change can receive messages published
before its creation. Existing durables retain their server-owned acknowledgement cursor on
reattachment, including durables originally created with `DeliverPolicy.NEW`. The framework
inbox makes replay idempotent. This change cannot reconstruct messages already removed from the
stream or retroactively recover messages skipped when an old `NEW` durable was first created;
those cases require operational reconciliation from authoritative state.
