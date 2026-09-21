# BusinessOS ADR Governance

Status: Active governance policy

## Purpose

Architecture Decision Records preserve decisions that affect BusinessOS architecture, public compatibility, trust boundaries, data ownership, or long-term platform direction. [DEVELOPMENT.md](../architecture/DEVELOPMENT.md) defines when to propose an ADR; this document defines lifecycle, approval authority, and acceptance evidence.

## Lifecycle statuses

- **DRAFT** — being explored; incomplete and not ready for approval.
- **PROPOSED** — complete enough for formal review; implementation depending on the decision remains blocked unless the proposal explicitly authorizes a reversible experiment.
- **ACCEPTED** — approved by the required accountable roles with traceable evidence. It is authoritative within its scope.
- **REJECTED** — reviewed and declined. It remains a historical record of the proposal and rationale.
- **WITHDRAWN** — removed from consideration by its proposer before acceptance or rejection.
- **SUPERSEDED** — previously accepted, then replaced by a later accepted ADR. It remains historical and links to its replacement.

Allowed transitions are:

```text
DRAFT -> PROPOSED
DRAFT -> WITHDRAWN
PROPOSED -> ACCEPTED
PROPOSED -> REJECTED
PROPOSED -> WITHDRAWN
ACCEPTED -> SUPERSEDED
```

A rejected or withdrawn idea returns through a new or explicitly revised DRAFT. `ACCEPTED` is never changed directly to `REJECTED` or `WITHDRAWN`.

## Required ADR record

Every new ADR includes:

- identifier and title;
- status;
- decision date when accepted, rejected, withdrawn, or superseded;
- context, decision, consequences, and considered alternatives;
- affected subsystems, owners, SDKs, and public contracts;
- compatibility and downstream impact;
- migration/data-ownership impact;
- tenancy and security impact where relevant;
- approving role names;
- approval pull request or commit;
- `Supersedes` and `Superseded by` links where applicable; and
- implementation or follow-up gates when the decision requires them.

Do not record fictional evidence. A missing historical field is documented as unavailable rather than invented.

## Approval authority

| ADR scope | Required approving roles |
| --- | --- |
| Normal architecture decision | Architecture Maintainer and owning-domain maintainer |
| Protected kernel/runtime | Architecture Maintainer and Platform/Kernel Maintainer |
| Security, identity, browser session, tenant trust, or authorization | Architecture Maintainer, Security Maintainer, and the Identity or Policy Maintainer as applicable |
| Public SDK or contract | Architecture Maintainer, SDK/Contract Maintainer, and affected owning-domain maintainer |
| Migration, schema ownership, or data lifecycle | Architecture Maintainer, Migration Safety Reviewer, and affected owning-domain maintainer |
| Cross-cutting release/compatibility policy | Architecture Maintainer, SDK/Contract Maintainer, and Release Maintainer |

One human may initially hold more than one role, but the acceptance evidence lists every role exercised. When a decision crosses several rows, the union of required roles approves it.

Normal approval is an independent accountable review by another eligible human maintainer. During the temporary single-maintainer pre-`1.0.0` stage, the documented [Solo Maintainer Exception](MAINTAINERS.md#temporary-solo-maintainer-exception) may instead provide owner governance attestation when its eligibility, exact-head CI, independent technical audit, and zero Critical/High finding gates are met. Owner attestation is not independent human review.

## Acceptance procedure

An ADR becomes formally `ACCEPTED` only when:

1. it is in `PROPOSED` status and contains the required impact analysis;
2. the required roles approve the exact ADR revision through independent accountable review or the documented Solo Maintainer Exception;
3. unresolved blocking review findings are closed;
4. the accepting pull request or commit records the decision date and approving roles; and
5. the accepted ADR is present on `main` with traceable approval evidence.

Green CI proves repository integrity but is not decision authority. GitHub mergeability alone does not accept an ADR. The merge or commit that changes status to `ACCEPTED` is the recorded acceptance checkpoint.

For solo acceptance, the owner personally records the exact ADR revision and commit SHA, GitHub identity, every accountable role exercised, applicable CI and independent technical audit evidence, and an explicit statement that independent human review was unavailable and was not performed. Authorship or merge action alone is not approval evidence. The normal ADR lifecycle, required impact analysis, status transitions, and supersession rules remain unchanged. Once another eligible human maintainer is formally assigned and available, independent accountable review is required.

## Accepted decisions and supersession

Do not silently rewrite an accepted decision into a materially different decision. Corrections that do not change meaning may use an ordinary reviewed documentation change. A material change uses a new ADR with a new identifier, includes a `Supersedes` link, and changes the earlier ADR to `SUPERSEDED` with a reciprocal `Superseded by` link in the same reviewed change.

Implementations must follow the latest accepted decision applicable to their scope. A proposed successor does not supersede an accepted ADR until the successor is accepted.

## Historical ADR transition

ADRs accepted before this policy took effect retain their historical accepted status. Existing evidence is recorded where available; missing modern metadata does not invalidate them. Future edits, status transitions, and new ADRs follow this policy.

Existing supersession history is preserved. In particular, ADR-008 remains the accepted Python/ASGI baseline and continues to supersede ADR-001. Accepted ADRs on later branches, including ADR-009 where present, are not invalidated merely because their original acceptance predates this policy.

## Enforcement boundary

This policy is a documented governance requirement. CODEOWNERS can request the mapped repository owner, but this document does not claim GitHub branch protection currently enforces role separation or approval counts. The acceptance record must state the actual reviewers and evidence used.
