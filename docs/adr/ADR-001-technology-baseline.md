# ADR-001: BusinessOS Technology Baseline

Status: Superseded by ADR-008

This ADR records the original planning baseline. ADR-008 supersedes it before implementation began.

## Context

BusinessOS requires an enterprise-grade technology baseline that performs well, supports self-hosting, remains understandable to external developers and can evolve without coupling business modules to infrastructure products.

## Decision

Use:

- Go as primary backend/worker language
- Gin as HTTP transport adapter
- PostgreSQL as transactional source of truth
- pgx + explicit/generated SQL as primary database-access strategy
- Redis for cache/transient state
- NATS JetStream for durable events/jobs
- S3-compatible object storage for files
- React + TypeScript + React Router + Vite for enterprise backoffice
- optional Next.js for public SSR/SEO experiences
- OpenTelemetry for instrumentation
- Docker Compose for development/small installs
- Kubernetes + Helm for enterprise HA

## Consequences

Business/domain code remains transport and infrastructure neutral through platform interfaces. Infrastructure implementations may evolve without requiring business-module rewrites.