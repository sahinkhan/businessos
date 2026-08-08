# BusinessOS Upgrade and Compatibility Architecture

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

Undocumented internal Go packages, private SQL tables and private frontend internals are not public compatibility contracts.

## Upgrade Flow

```text
Discover release
-> verify signature/checksum/SBOM/provenance
-> inventory installed modules
-> compatibility/capability preflight
-> migration preflight
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

Target channels:

- preview
- stable
- LTS
- security-only maintenance where commercially supported

## Module Compatibility

Every module declares supported platform and SDK ranges.

The update runtime blocks activation when mandatory compatibility requirements are not satisfied.

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