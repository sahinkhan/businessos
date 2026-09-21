# Phase 1 module manifest declarations

`ModuleManifest` accepts additive declarations for published API, event, and other
public contracts. Each declaration has a stable `contract_id` and a version.
The manifest also carries UI contribution identifiers, configuration scopes,
localization resource paths, and explicit tenant export/delete support flags.
An omitted support flag means *not declared*, rather than a claim that the
operation is unsupported.

Distributable modules may declare an artifact SHA-256 digest and references to
their signature and SBOM. These are metadata for compatibility and distribution
preflight; the Phase 1 module loader does not verify signatures or perform
marketplace trust checks. That enforcement belongs to the later marketplace
implementation. Existing module manifests remain valid because the new fields
are optional and default to empty or unspecified values.

The declarations are validated and survive JSON serialization so upgrade tools
can compare published surfaces without importing private module code. Declaring
an export or delete capability does not itself register a lifecycle hook; the
owning module must separately implement and test that behavior.

Upgrade preflight compares a proposed manifest with the installed manifest. A
target may add contracts or increase their versions, but it cannot remove or
downgrade an API, event, or other public contract. It also cannot withdraw
declared UI contributions, configuration scopes, localization resources, or
tenant export/delete support. The check applies even when the module version
increases. Artifact digest, signature, and SBOM references describe the new
artifact and may change on upgrade; Phase 1 does not verify those references.
