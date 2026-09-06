# ADR-004: Customer and Marketplace Extension Execution

Status: Accepted

## Context

Enterprise customers must create private modules and receive future BusinessOS upgrades without maintaining core source forks. Marketplace code also requires stronger trust isolation than arbitrary in-process execution provides.

## Decision

Use a layered extension model:

1. configuration
2. metadata
3. workflow/rules
4. controlled extension hooks
5. declarative modules
6. isolated executable service modules

Customer/marketplace executable modules normally run as separate OCI containers/processes and communicate through versioned REST, gRPC, event, provider and frontend-extension contracts.

Untrusted customer or marketplace Python packages are not loaded into the protected runtime.

## Consequences

The platform must provide strong SDK/contracts and a module host/lifecycle manager. Third-party code can evolve independently and may be polyglot while protected kernel upgrades remain decoupled from third-party compilation/runtime details.