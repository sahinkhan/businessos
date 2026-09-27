"""Private, bounded preventative SoD projection over trusted Policy authority."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Table, select

from businessos.sdk import BusinessOSError, TransactionalPersistence

from .delegation_authority import MAX_SOURCE_TRAVERSALS, active_at, has_effective_role_source
from .models import (
    DELEGATIONS,
    ROLE_PERMISSIONS,
    ROLES,
    SOD_RULES,
    SUBJECT_ROLE_ASSIGNMENTS,
    DelegationGrantRecord,
    RolePermissionRecord,
    RoleRecord,
    SegregationOfDutiesRuleRecord,
    SoDSeverity,
    SubjectRoleAssignmentRecord,
)

_MAX_ROWS = 256
_MAX_ROLE_DEPTH = 16
_MAX_EVALUATIONS = 4096
_TYPES = frozenset({"user", "service_account", "device"})
type _Subject = tuple[str, UUID]


def _unbounded(reason: str) -> BusinessOSError:
    return BusinessOSError("authority_unbounded", reason, status_code=403)


async def _load_rows(
    persistence: TransactionalPersistence, table: Table, tenant_id: UUID
) -> list[dict[str, object]]:
    result = await persistence.execute(
        select(table).where(table.c.tenant_id == tenant_id).limit(_MAX_ROWS + 1)
    )
    rows = [dict(row) for row in result.mappings()]
    if len(rows) > _MAX_ROWS:
        raise _unbounded("Policy authority scan exceeds the reviewed row bound")
    return rows


async def _load_preventative_rules(
    persistence: TransactionalPersistence, tenant_id: UUID
) -> list[dict[str, object]]:
    result = await persistence.execute(
        select(SOD_RULES)
        .where(
            SOD_RULES.c.tenant_id == tenant_id,
            SOD_RULES.c.severity == SoDSeverity.PREVENTATIVE.value,
        )
        .limit(_MAX_ROWS + 1)
    )
    rows = [dict(row) for row in result.mappings()]
    if len(rows) > _MAX_ROWS:
        raise _unbounded("Preventative SoD rule scan exceeds the reviewed row bound")
    return rows


@dataclass(frozen=True)
class SoDAuthority:
    """One tenant snapshot, used only under its Policy transaction advisory lock."""

    tenant_id: UUID
    roles: tuple[RoleRecord, ...]
    permissions: tuple[RolePermissionRecord, ...]
    assignments: tuple[SubjectRoleAssignmentRecord, ...]
    delegations: tuple[DelegationGrantRecord, ...]
    rules: tuple[SegregationOfDutiesRuleRecord, ...]

    @classmethod
    async def load(cls, persistence: TransactionalPersistence, tenant_id: UUID) -> SoDAuthority:
        graph = cls(
            tenant_id=tenant_id,
            roles=tuple(
                RoleRecord.model_validate(row)
                for row in await _load_rows(persistence, ROLES, tenant_id)
            ),
            permissions=tuple(
                RolePermissionRecord.model_validate(row)
                for row in await _load_rows(persistence, ROLE_PERMISSIONS, tenant_id)
            ),
            assignments=tuple(
                SubjectRoleAssignmentRecord.model_validate(row)
                for row in await _load_rows(persistence, SUBJECT_ROLE_ASSIGNMENTS, tenant_id)
            ),
            delegations=tuple(
                DelegationGrantRecord.model_validate(row)
                for row in await _load_rows(persistence, DELEGATIONS, tenant_id)
            ),
            rules=tuple(
                SegregationOfDutiesRuleRecord.model_validate(row)
                for row in await _load_preventative_rules(persistence, tenant_id)
            ),
        )
        graph._validate_shape()
        return graph

    def with_permission(self, record: RolePermissionRecord) -> SoDAuthority:
        return replace(self, permissions=(*self.permissions, record))

    def with_assignment(self, record: SubjectRoleAssignmentRecord) -> SoDAuthority:
        return replace(self, assignments=(*self.assignments, record))

    def with_delegation(self, record: DelegationGrantRecord) -> SoDAuthority:
        return replace(self, delegations=(*self.delegations, record))

    def with_rule(self, record: SegregationOfDutiesRuleRecord) -> SoDAuthority:
        return replace(self, rules=(*self.rules, record))

    def _validate_shape(self) -> None:
        for assignment in self.assignments:
            if (assignment.valid_from is not None and assignment.valid_from.tzinfo is None) or (
                assignment.valid_to is not None and assignment.valid_to.tzinfo is None
            ):
                raise _unbounded("Policy authority has a naive validity instant")
        for grant in self.delegations:
            if grant.valid_from.tzinfo is None or grant.valid_to.tzinfo is None:
                raise _unbounded("Policy authority has a naive validity instant")
        roles = {role.id: role for role in self.roles}
        for role in self.roles:
            seen: set[UUID] = set()
            current: UUID | None = role.id
            while current is not None:
                if current in seen or len(seen) >= _MAX_ROLE_DEPTH:
                    raise _unbounded("Policy role hierarchy is cyclic or too deep")
                seen.add(current)
                parent = roles.get(current)
                if parent is None:
                    raise _unbounded("Policy role hierarchy has a missing parent")
                current = parent.parent_role_id
        # A typed, non-revoked delegation cycle is malformed even when no
        # current root assignment can make it effective. Reject rather than
        # undercount it; memoized traversal keeps the graph check bounded.
        by_role: dict[UUID, dict[_Subject, set[_Subject]]] = {}
        for grant in self.delegations:
            if (
                grant.is_revoked
                or grant.delegator_type not in _TYPES
                or grant.delegatee_type not in _TYPES
            ):
                continue
            edges = by_role.setdefault(grant.role_id, {})
            edges.setdefault((grant.delegator_type, grant.delegator_id), set()).add(
                (grant.delegatee_type, grant.delegatee_id)
            )
        for edges in by_role.values():
            depths: dict[_Subject, int] = {}

            def visit(
                node: _Subject,
                path: frozenset[_Subject],
                graph_edges: dict[_Subject, set[_Subject]],
                memo: dict[_Subject, int],
            ) -> int:
                if node in path:
                    raise _unbounded("Policy delegation graph is cyclic or too deep")
                if node in memo:
                    return memo[node]
                depth = 1
                for child in graph_edges.get(node, ()):
                    depth = max(depth, 1 + visit(child, path | {node}, graph_edges, memo))
                if depth > _MAX_ROLE_DEPTH:
                    raise _unbounded("Policy delegation graph is cyclic or too deep")
                memo[node] = depth
                return depth

            for node in edges:
                visit(node, frozenset(), edges, depths)

    def _subjects(self) -> set[_Subject]:
        subjects = {
            (assignment.subject_type, assignment.subject_id)
            for assignment in self.assignments
            if assignment.subject_type in _TYPES
        }
        subjects.update(
            (grant.delegatee_type, grant.delegatee_id)
            for grant in self.delegations
            if grant.delegatee_type in _TYPES
        )
        return subjects

    def _instants(self, now: datetime) -> set[datetime]:
        # Authority changes only at a half-open validity boundary. Checking
        # now and every future start catches latent conflicts without adding
        # any new SoD rule syntax or caller-selected decision time.
        starts = {now}
        for row in self.assignments:
            if row.valid_from is not None and row.valid_from > now:
                starts.add(row.valid_from.astimezone(UTC))
        for grant in self.delegations:
            if grant.valid_from > now:
                starts.add(grant.valid_from.astimezone(UTC))
        return starts

    def permissions_for(
        self, subject: _Subject, instant: datetime, traversal_budget: list[int] | None = None
    ) -> set[str]:
        if traversal_budget is None:
            traversal_budget = [MAX_SOURCE_TRAVERSALS]
        role_ids = {
            row.role_id
            for row in self.assignments
            if row.subject_type == subject[0]
            and row.subject_id == subject[1]
            and active_at(row.valid_from, row.valid_to, instant)
        }
        for grant in self.delegations:
            if (
                grant.delegatee_type == subject[0]
                and grant.delegatee_id == subject[1]
                and grant.delegator_type in _TYPES
                and not grant.is_revoked
                and active_at(grant.valid_from, grant.valid_to, instant)
                and has_effective_role_source(
                    tenant_id=self.tenant_id,
                    subject_id=grant.delegator_id,
                    subject_type=grant.delegator_type,
                    role_id=grant.role_id,
                    scope_type=grant.scope_type,
                    scope_id=grant.scope_id,
                    valid_from=grant.valid_from,
                    valid_until=grant.valid_to,
                    evaluated_at=instant,
                    assignments=list(self.assignments),
                    delegations=list(self.delegations),
                    traversal_budget=traversal_budget,
                )
            ):
                role_ids.add(grant.role_id)
        roles = {role.id: role for role in self.roles}
        for role_id in tuple(role_ids):
            current: UUID | None = role_id
            while current is not None:
                role_ids.add(current)
                role = roles.get(current)
                if role is None:
                    raise _unbounded("Policy authority references a missing role")
                current = role.parent_role_id
        return {row.permission_code for row in self.permissions if row.role_id in role_ids}

    def reject_new_conflicts(self, projected: SoDAuthority, *, new_rule: bool = False) -> None:
        projected._validate_shape()
        rules = (
            projected.rules[-1:]
            if new_rule
            else tuple(
                rule for rule in projected.rules if rule.severity is SoDSeverity.PREVENTATIVE
            )
        )
        if not rules:
            return
        now = datetime.now(UTC)
        subjects = self._subjects() | projected._subjects()
        instants = self._instants(now) | projected._instants(now)
        if len(subjects) * len(instants) > _MAX_EVALUATIONS:
            raise _unbounded("Policy affected-subject evaluation exceeds the reviewed bound")
        conflicts: list[str] = []
        affected: list[str] = []
        traversal_budget = [MAX_SOURCE_TRAVERSALS]
        for subject in sorted(subjects):
            for instant in sorted(instants):
                before = self.permissions_for(subject, instant, traversal_budget)
                after = projected.permissions_for(subject, instant, traversal_budget)
                if not new_rule and not after.difference(before):
                    continue
                for rule in rules:
                    if (
                        rule.severity is SoDSeverity.PREVENTATIVE
                        and {rule.permission_a, rule.permission_b} <= after
                    ):
                        if rule.code not in conflicts:
                            conflicts.append(rule.code)
                        label = f"{subject[0]}:{subject[1]}"
                        if label not in affected:
                            affected.append(label)
                        break
        if conflicts:
            raise BusinessOSError(
                "segregation_of_duties_conflict",
                "Projected Policy authority violates a preventative segregation-of-duties rule",
                status_code=409,
                details={
                    "conflicts": conflicts[:8],
                    "subjects": affected[:8],
                    "subject_count": len(affected),
                },
            )
