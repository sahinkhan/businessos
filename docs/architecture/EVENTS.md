# BusinessOS Events, Jobs and Workflow Architecture

## Synchronous vs Asynchronous

Use the simplest correct communication style.

- BusinessOS command/query dispatch or published application interfaces: synchronous modular-monolith calls.
- REST/OpenAPI: public/partner APIs and ordinary isolated-module calls.
- gRPC/Protobuf: high-throughput, streaming or strongly typed internal service boundaries after extraction.
- NATS JetStream: durable asynchronous events, commands and work distribution.

## Transactional Outbox

Business events produced from a PostgreSQL transaction use the transactional outbox pattern.

```text
Application command
    -> domain invariant
    -> PostgreSQL transaction
       -> owned state changes
       -> outbox record
    -> commit
    -> outbox publisher
    -> NATS JetStream
```

Do not publish an event before the authoritative database transaction commits.

## Event Contract

Published events require:

- stable event type/name
- owning module
- schema/version
- event ID
- occurred-at timestamp
- tenant context
- correlation/causation information
- payload contract

Use CloudEvents-compatible metadata conventions where practical and AsyncAPI for published messaging contracts.

## Idempotency

Consumers must be idempotent.

Side-effecting consumers must maintain durable deduplication/idempotency state where redelivery could otherwise duplicate business effects.

The framework durable-consumer boundary claims `(tenant_id, consumer, event_id)` in the inbox
and executes the subscriber's relational side effects through the same tenant-scoped Unit of Work.
The inbox receipt and those effects commit or roll back together. External effects must additionally
use a deterministic idempotency key; an inbox receipt is committed only after the handler succeeds.
Concurrent redelivery therefore admits one transaction and makes every later delivery a no-op.

The standalone framework event worker is the supported durable delivery process. It publishes
outbox rows with the limited cross-tenant operations role, while every subscriber transaction uses
the non-owner, `NOBYPASSRLS` application role. The web process never receives operations-role
credentials. A JetStream message is acknowledged only after every admitted subscriber has either
committed its inbox receipt and side effect or was already durably claimed. Retryable failures are
negatively acknowledged; malformed envelopes are terminated without entering a tenant transaction.

Authoritative worker tenant context is established only when the framework-owned subject, headers
and validated event payload agree on the tenant UUID, event UUID, type, version and correlation ID.
The worker service-account installation/principal identity comes from its isolated deployment
configuration. No HTTP tenant header or one unverified broker header can select a tenant.

Tenant-owned events use subjects shaped as
`businessos.events.tenant.<tenant_uuid>.<event_type>`. The tenant segment comes from the persisted
outbox row, never from an arbitrary publish call or client header. The envelope also preserves
correlation/causation data and W3C `traceparent`/`tracestate` fields for producer-to-consumer span
continuation.

## Commands vs Events

Command: request that something happen. It may fail.

Event: fact that already happened in the owning domain.

Do not use ambiguous event names that describe intentions rather than facts.

## Background Jobs

Modules use a BusinessOS job abstraction that provides:

- tenant scope
- job type/version
- scheduling
- retries/backoff
- timeout
- priority
- progress
- cancellation where safe
- concurrency limits
- tenant quotas
- dead-letter/failure handling
- correlation/telemetry

A module should not introduce its own queue framework without an approved ADR.

## Durable Workflow

Long-running processes that survive process restarts/network failures use the BusinessOS workflow abstraction.

The implementation engine may evolve, but business modules depend on the platform workflow contract rather than directly coupling to a workflow product.

## Framework Ownership

The custom BusinessOS framework owns command/query handler registration and dispatch, event contract registration, middleware execution, dependency scopes, trusted context propagation and Unit of Work integration. A command that changes authoritative state and emits durable events executes inside one framework-owned transaction; event publication occurs through the outbox only after commit.

Modules must not create parallel in-process buses or bypass framework event and transaction coordination.
Command dispatch never calls subscribers directly after commit. Durable event handlers run only
through the framework inbox consumer after the outbox publisher has delivered the committed event.

## Compatibility

Published event schemas are public contracts. Breaking event changes require versioning and a coexistence/migration strategy.
