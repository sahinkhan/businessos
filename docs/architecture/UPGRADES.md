# BusinessOS Upgrade and Compatibility Architecture

Release versioning, channel promises, compatibility classification, approval authority, and
release eligibility are governed by
[RELEASES.md](../governance/RELEASES.md). This document defines the technical upgrade model that
implements that policy.

## Objective

Enterprise customers must be able to upgrade BusinessOS without maintaining permanent core forks and without silently activating incompatible customer modules.

## Protected Contracts

The following are versioned compatibility surfaces when published:

- public REST APIs
- event schemas
- provider interfaces
- module manifests
- module SDK contracts
- entity/metadata contracts
- frontend extension slots
- CLI automation interfaces

Undocumented internal Python modules, SQLAlchemy mappings, private SQL tables and private frontend internals are not public compatibility contracts.

## Upgrade Flow

```text
Discover release
-> verify signature/checksum/SBOM/provenance
-> inventory installed modules
-> Python/platform/SDK/dependency compatibility preflight
-> module capability and lifecycle preflight
-> Alembic migration graph preflight
-> verify backup/restore checkpoint
-> apply expand migrations
-> deploy compatible runtime
-> run resumable backfills
-> health/smoke/conformance checks
-> shift/continue traffic
-> monitor
-> perform contract cleanup only in a later compatible release
```

## Release Channels

The governed channels are development, preview, stable, LTS, and explicitly offered
security-only maintenance. Their guarantees and eligibility gates are defined in
[RELEASES.md](../governance/RELEASES.md). A channel label alone does not create a support promise.

## Module Compatibility

Every module declares supported platform and SDK ranges.

The BusinessOS framework upgrade coordinator validates Python runtime, platform, SDK, dependency, capability and migration compatibility before changing module state. It orders module-owned Alembic revisions according to the validated dependency graph and blocks activation when mandatory requirements are not satisfied.

No incompatible module is silently enabled.

## Database Evolution

Use expand-contract:

1. add new compatible structure
2. deploy code that can coexist
3. backfill/migrate data
4. move readers/writers to new contract
5. verify
6. remove old structure only after compatibility window

Do not assume database downgrade is always possible. For irreversible data migrations, forward repair and tested restore are the recovery strategies.

Production upgrades never use SQLAlchemy metadata synchronization. Only reviewed Alembic revisions may change authoritative schemas.

## Self-Hosted Operation

Enterprise self-hosted customers must be able to:

- inspect available release metadata
- stage upgrades
- run preflight
- schedule maintenance
- retain backups
- use signed offline bundles for air-gapped environments

The customer data plane must not require continuous vendor control-plane availability for ordinary business operations.

## Deprecation

Every deprecated public contract must document:

- deprecation version
- replacement
- migration guidance
- earliest removal version

Breaking changes require explicit major-version or contract-version treatment and compatibility planning.
Pre-1.0 versions are governed by the same compatibility analysis and may not silently break a
published or frozen contract. The complete support-window and removal gates are defined in
[RELEASES.md](../governance/RELEASES.md).
