# BusinessOS Events, Jobs and Workflow Architecture

## Synchronous vs Asynchronous

Use the simplest correct communication style.

- In-process published application interfaces: synchronous modular-monolith calls.
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

## Compatibility

Published event schemas are public contracts. Breaking event changes require versioning and a coexistence/migration strategy.