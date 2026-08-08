# ADR-005: Transactional Outbox for Domain Events

Status: Accepted

## Context

BusinessOS must not lose domain/integration events when a database transaction commits but a message broker publish fails.

## Decision

When a PostgreSQL transaction produces a durable event, write the authoritative state and outbox record atomically in the same transaction. Publish to NATS JetStream asynchronously after commit.

Consumers must be idempotent and maintain durable deduplication state for duplicate-sensitive side effects.

## Consequences

Event delivery is at-least-once. Consumers cannot assume exactly-once broker delivery. Operational tooling must expose outbox backlog, retries and failed publications.