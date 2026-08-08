# ADR-002: Modular Monolith First

Status: Accepted

## Context

BusinessOS contains many bounded contexts but premature microservice decomposition would increase operational and development complexity before workload boundaries are measured.

## Decision

Start as a domain-structured modular monolith with strict ownership and published contracts.

Extract a module/service only when justified by measurable independent scaling, failure/security isolation, runtime conflict, high-concurrency/streaming requirements or independently managed lifecycle.

## Consequences

Module boundaries must be enforceable in code and data ownership from day one. In-process calls use published application interfaces so later service extraction can replace transport without redesigning domain contracts.