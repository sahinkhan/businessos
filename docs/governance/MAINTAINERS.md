# BusinessOS Maintainers and Review Ownership

Status: Active governance policy

## Roles and current assignment

Governance roles describe accountability, not permanent people. The repository currently has one verified GitHub owner, `@sahinkhan`, who temporarily holds the roles below. Future maintainers may be assigned by an accepted governance change without changing the responsibilities of each role.

| Area | Accountable role | Current GitHub owner |
| --- | --- | --- |
| Architecture and ADRs | Architecture Maintainer | `@sahinkhan` |
| Protected kernel/runtime | Platform/Kernel Maintainer | `@sahinkhan` |
| Module framework and SDK | SDK/Contract Maintainer | `@sahinkhan` |
| Identity and web sessions | Identity Maintainer | `@sahinkhan` |
| Organization foundation | Organization Maintainer | `@sahinkhan` |
| Policy and authorization | Policy Maintainer | `@sahinkhan` |
| Cross-cutting security | Security Maintainer | `@sahinkhan` |
| Database migrations and ownership safety | Migration Safety Reviewer | `@sahinkhan` |
| CI, packaging, and releases | Release Maintainer | `@sahinkhan` |
| Enterprise frontend foundation | Frontend Foundation Maintainer | `@sahinkhan` |
| Documentation and governance | Documentation/Governance Maintainer | `@sahinkhan` |
| Other bounded contexts | Owning Domain Maintainer | `@sahinkhan` until delegated |

## Required review ownership

| Change | Required role review |
| --- | --- |
| Protected kernel, ASGI runtime, dependency injection, context, unit of work, lifecycle, compatibility, events, or provider registry | Platform/Kernel Maintainer; Architecture Maintainer when a boundary changes |
| Module SDK, manifest, conformance, or published provider/application contract | SDK/Contract Maintainer and Architecture Maintainer, plus each affected owning domain |
| Identity, OIDC/SAML, browser sessions, credentials, MFA, or principal trust | Identity Maintainer and Security Maintainer |
| Policy, authorization, support access, delegation, or privileged bypass | Policy Maintainer and Security Maintainer |
| Tenant isolation or cross-tenant subsystem behavior | Security Maintainer and affected owning-domain maintainer |
| Organization hierarchy or scope semantics | Organization Maintainer; Security Maintainer when authorization scope changes |
| Public contract version or removal | SDK/Contract Maintainer, Architecture Maintainer, and contract-owning domain maintainer |
| Alembic revision, schema ownership, migration graph, backfill, or destructive cleanup | Owning Domain Maintainer and Migration Safety Reviewer |
| ADR status change to `ACCEPTED` | The matrix in [ADR-GOVERNANCE.md](ADR-GOVERNANCE.md) |
| Release or tag | The matrix and eligibility gates in [RELEASES.md](RELEASES.md) |
| Frontend shell, design system, route/navigation contract, auth presentation, or extension slot | Frontend Foundation Maintainer; SDK/Contract or Security Maintainer when those boundaries are affected |
| CI workflow, packaging, signing, or release metadata | Release Maintainer; Security Maintainer for supply-chain controls |
| Governance policy | Documentation/Governance Maintainer and the accountable role whose policy changes |

Review must come from the required accountable role even when the author also holds that role. While one person holds several roles, the pull request or decision record lists each role exercised so later audits can distinguish responsibility from identity.

## Multiple approvals

The union of applicable review rows is required. Changes need multiple role approvals when they cross ownership boundaries, affect public contracts, change security or tenancy semantics, alter migration/data ownership, accept an ADR, or create a release. A single person may satisfy several roles during the initial maintainer stage, but this temporary staffing model does not collapse the roles or remove their separate review obligations.

## Availability and escalation

If an accountable owner is unavailable, the change remains pending. The Architecture Maintainer coordinates reassignment for architecture, SDK, or domain ownership; the Security Maintainer coordinates security review; and the Release Maintainer coordinates CI/release ownership. A replacement must be a valid repository collaborator and the review record identifies the delegated role.

An urgent security response may proceed with the Security Maintainer and Release Maintainer when delay would increase harm. The exception record must state scope, reason, mitigations, omitted role, and required retrospective review. It cannot silently waive tenant isolation, auditability, migration safety, or immutable-tag rules.

## CODEOWNERS and enforcement

`.github/CODEOWNERS` maps critical paths to the current valid GitHub owner. It provides review routing and an auditable ownership baseline. CODEOWNERS does not itself prove that branch protection, required reviews, or role separation is enabled. Until those repository settings are independently verified, these review rules are documented process requirements enforced through pull-request and release evidence.
