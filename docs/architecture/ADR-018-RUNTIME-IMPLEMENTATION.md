# ADR-018 neutral runtime implementation

Status: implementation candidate for [ADR-018](../adr/ADR-018-canonical-resource-ownership-and-owner-operation-boundary.md).

Runtime implementation commit: `9d0f85718cc823291ab8907c778aaef1b055395e`.

Changed files in that runtime commit: `platform/src/businessos/bootstrap.py`,
`platform/src/businessos/dependencies.py`, `platform/src/businessos/messages.py`,
`platform/src/businessos/modules/__init__.py`,
`platform/src/businessos/modules/artifact.py`,
`platform/src/businessos/modules/manifest.py`,
`platform/src/businessos/modules/registry.py`,
`platform/src/businessos/modules/sdk.py`, `platform/src/businessos/resources.py`,
`platform/src/businessos/runtime.py`, `platform/src/businessos/sdk/__init__.py`,
`tests/conformance/test_public_sdk.py`, and
`tests/unit/test_resource_ownership.py`. This document is the only additional
file in the documentation commit.

## Trust and composition

Resource claims are opt-in `ModuleManifest.resource_ownership` declarations. A
claiming module, or a module configured as a governed operation coordinator,
needs an `ApprovedModuleArtifact` supplied by the protected installation
composition through `create_application(approved_module_artifacts=...)`. The
grant identifies the exact loaded module instance and type, permitted module
ID, approved publisher/package allocation, and protected operator install
identity. An optional artifact digest may be checked against manifest metadata,
but the runtime does **not** perform signature or digest verification. The
operator's installation inventory must verify the artifact externally and
preserve the allocated module ID and publisher/package across process restarts,
disablement, retirement, and upgrades. A module manifest, entry point, tenant
API, or dynamic tenant configuration is not an approved grant source. The
runtime rejects missing, revoked, mismatched, or reused replacement evidence.
Reserved `foundation.*`, `business.*`, and `businessos.*` IDs require
first-party approval.
Every alias requires a separate exact alias/canonical/version approval in the
grant, including aliases using a legacy root.

`ModuleRegistry.replace` accepts only a disabled or installed module, requires
fresh approved install identity for the exact replacement instance, preserves
the allocated publisher/package, and checks additive ownership/alias
compatibility. A later persistent installation service may supply the same
protected input without changing the SDK. No database migration is included.

## SDK and lifecycle

The stable SDK exports `ResourceOwnership`, `ResourceLocator`,
`ResourceOwnerFacts`, typed facts/operation protocols, and
`RESOURCE_OWNER_RESOLVER`. Modules register narrow facts or operation providers
through `ModuleRegistration.resource_owner_facts` and
`resource_owner_operation`. Registration requires a declaration in that exact
manifest, owner and version, and occurs before generation publication.
`ModuleRegistration.provider` remains available for ordinary capabilities; it
cannot establish canonical resource ownership. The neutral registry stages
claims and providers, rejects collisions, publishes with the contribution
generation, and removes the exact generation after drain. Aliases are explicit
reviewed mappings to the granted owner and cannot create a second owner.

The resolver returns an immutable binding and an admitted handle for the exact
resource/version/provider kind. It checks trusted request tenant and the
returned owner facts' tenant, namespace, record, owner, version, and lifecycle.
Operation handles require an approved coordinator module generation already
admitted by the framework dispatcher; a caller-supplied coordinator name is
never accepted. Operation providers declare supported actions; validation in
the same transaction precedes application. These contracts do not implement
retention, holds, Policy V2, Audit V2, or domain mutations.

The dispatcher owns a transaction admission scope. A provider generation is
admitted once per transaction and held through the outer unit of work's commit
or rollback and cleanup. Disable stops new admissions and waits for those
leases before removing contributions. Cached handles check their exact
transaction and registration on every use.

## Compatibility and follow-up

Existing modules with no resource declarations and ordinary provider
registration retain their Phase 1 behavior. No owner-domain schema or Alembic
revision changes here. Phase 1 remains FINAL PASS / FROZEN; this is the
compatible additive ADR-018 extension. ADR-014 Policy facts adaptation and
ADR-017 Governance retention/hold/purge coordination remain separate work.
Their implementation certification must resolve locked normalized owner facts
and the combined lock order identified in ADR-018.

The exact implementation candidate SHA, changed-file inventory, local gate
results, exact-head CI, and independent audit are recorded in the pull request
and its implementation report after the candidate is committed.
