# ADR-007: Upgrade and Backward Compatibility Strategy

Status: Accepted

## Decision

BusinessOS protects published contracts through explicit versioning/deprecation and uses preflighted upgrades.

Database evolution uses explicit migrations and expand-contract for compatibility-sensitive changes. Destructive cleanup is delayed until old contracts/runtimes are outside the supported compatibility window.

Installed module compatibility is checked before activation. An incompatible module is never silently enabled.

## Consequences

Releases require compatibility metadata, migration planning and conformance tests. Database downgrade is not universally guaranteed; tested restore and forward repair are required recovery strategies for irreversible migrations.