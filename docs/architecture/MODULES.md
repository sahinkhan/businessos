# BusinessOS Module and Extension Architecture

## Module Classes

BusinessOS supports four primary extension forms.

### Declarative Module

Metadata/contracts with no arbitrary in-process executable code. Suitable for custom entities, fields, forms, views, workflow, rules, reports and configuration.

### First-Party In-Process Python Module

Official BusinessOS module distributed as a versioned Python package and loaded through the BusinessOS module SDK. Used for high-trust platform foundations and official business modules. Importability alone does not activate a module; discovery, dependency validation and lifecycle remain framework-owned.

### Isolated Service Module

Separate OCI container/process. Default executable model for customer modules and marketplace modules that require custom code.

### UI Micro-Application

Sandboxed frontend contribution for specialized user experiences that cannot be represented through declarative UI/controlled extension slots.

## In-Process Runtime Plugins

Arbitrary in-process runtime plugins are not the marketplace architecture. Their interpreter/dependency coupling and process trust model conflict with long-term independent module compatibility and isolation goals.

Go remains an optional future implementation language only for isolated, performance-sensitive microservices justified by measurement and architecture review. Those services use published contracts and do not participate as in-process modules.

## Framework Ownership

The custom BusinessOS ASGI framework owns module discovery, dependency ordering, install/enable/disable/upgrade/retire lifecycle, route and middleware registration, dependency injection, command/query and event registration, metadata, permissions, Unit of Work boundaries, SDK compatibility and upgrade coordination.

Modules contribute declarations and handlers through the versioned BusinessOS Python SDK. They must not mutate global registries, construct parallel routers/containers or manage application-wide SQLAlchemy sessions outside those contracts.

## Module Ownership

Every module owns:

- domain invariants
- database schema/tables
- migrations
- application services
- public commands/events/APIs it publishes
- permissions
- UI contributions
- tests
- localization resources

A module must not directly modify another module's private tables or import private Python modules.

## Module Manifest

Every installable module must have a machine-readable manifest declaring at minimum:

- stable module ID
- name/publisher
- semantic version
- compatible platform range
- SDK compatibility
- execution type
- Python and BusinessOS SDK compatibility for in-process modules
- framework registration entry point for in-process modules
- dependencies and version ranges
- required capabilities/permissions
- database schema/migrations
- APIs/events/contracts
- UI contributions
- supported tenancy modes
- configuration scopes
- localization resources
- tenant export/delete support where applicable
- integrity/signature/SBOM information for distributable modules

## Dependency Rules

Dependencies form a directed acyclic graph.

Allowed conceptual direction:

```text
Industry -> Business -> Foundation -> Kernel
Localization/Connectors -> published contracts of relevant layers
```

Circular module dependencies are prohibited.

Optional integrations use events/provider contracts rather than hard cyclic dependencies.

## Customer Development

Customer code lives outside protected vendor core repositories and depends only on the published BusinessOS SDK and contracts.

Customer modules must remain installable/upgradable without patching BusinessOS kernel source.

## Marketplace Trust

Third-party executable modules default to isolated execution with:

- scoped service identity
- explicit capabilities
- no unrestricted database credentials
- network policy where supported
- signed artifacts
- SBOM/provenance
- vulnerability scanning
- resource quotas
- auditable install/upgrade lifecycle

## Module Lifecycle

Canonical states:

```text
available -> installing -> installed -> enabled
                         -> disabled
                         -> upgrading
                         -> failed
                         -> uninstalling -> removed
```

Install/upgrade operations must be resumable or recoverable. A partially migrated incompatible module must not be silently enabled.

## Compatibility

Public module dependencies use semantic compatibility ranges. Private implementation details are not compatibility contracts.

Contract changes that require consumers to change immediately are breaking changes and require a versioning/deprecation strategy.
