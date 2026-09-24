"""Public qualified classification identities and monotonic security controls."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from businessos.sdk import HandlerTransaction, RequestContext

CANONICAL_NAMESPACE = "foundation.data_governance.data-classification"
POLICY_ALIAS = "foundation.governance.data-classification"
CONTRACT_VERSION = "2"
_CODE = re.compile(r"[A-Z][A-Z0-9_]{1,49}\Z", re.ASCII)


def normalize_code(code: str) -> str:
    if type(code) is not str or not _CODE.fullmatch(code):
        raise ValueError("Classification code must be canonical uppercase ASCII")
    return code


def canonical_ref(code: str) -> str:
    return f"core:{normalize_code(code)}"


def tenant_ref(tenant_id: UUID, code: str) -> str:
    if type(tenant_id) is not UUID:
        raise ValueError("Trusted tenant ID must be a UUID")
    return f"tenant:{tenant_id}:{normalize_code(code)}"


def parse_ref(reference: str, tenant_id: UUID) -> tuple[str, str]:
    if type(reference) is not str or type(tenant_id) is not UUID:
        raise ValueError("Qualified classification identity is required")
    if reference.startswith("core:"):
        code = normalize_code(reference[5:])
        if reference != canonical_ref(code):
            raise ValueError("Noncanonical classification identity")
        return "core", code
    prefix = f"tenant:{tenant_id}:"
    if reference.startswith(prefix):
        code = normalize_code(reference[len(prefix) :])
        if reference != tenant_ref(tenant_id, code):
            raise ValueError("Noncanonical classification identity")
        return "tenant", code
    raise ValueError("Unknown or cross-tenant classification identity")


@dataclass(frozen=True, slots=True)
class SecurityControls:
    sensitivity_level: int
    required_controls: frozenset[str] = frozenset()
    restrictions: frozenset[str] = frozenset()
    allowed_audience: frozenset[str] | None = None
    mandatory_masking: bool = False

    def __post_init__(self) -> None:
        if type(self.sensitivity_level) is not int or not 1 <= self.sensitivity_level <= 5:
            raise ValueError("Sensitivity level must be an integer from 1 to 5")
        if type(self.mandatory_masking) is not bool:
            raise ValueError("Masking must be Boolean")
        for values in (self.required_controls, self.restrictions, self.allowed_audience):
            if values is None:
                continue
            if type(values) is not frozenset or any(
                type(value) is not str or not value or len(value) > 100 for value in values
            ):
                raise ValueError("Security control values must be bounded immutable strings")

    def compose(self, addition: SecurityControls) -> SecurityControls:
        if addition.sensitivity_level < self.sensitivity_level:
            raise ValueError("Tenant controls cannot lower canonical sensitivity")
        if (
            self.allowed_audience is not None
            and addition.allowed_audience is not None
            and not addition.allowed_audience <= self.allowed_audience
        ):
            raise ValueError("Tenant controls cannot expand canonical audience")
        if self.allowed_audience is None:
            audience = addition.allowed_audience
        elif addition.allowed_audience is None:
            audience = self.allowed_audience
        else:
            audience = self.allowed_audience & addition.allowed_audience
        return SecurityControls(
            sensitivity_level=max(self.sensitivity_level, addition.sensitivity_level),
            required_controls=self.required_controls | addition.required_controls,
            restrictions=self.restrictions | addition.restrictions,
            allowed_audience=audience,
            mandatory_masking=self.mandatory_masking or addition.mandatory_masking,
        )


@dataclass(frozen=True, slots=True)
class ClassificationResolutionV2:
    tenant_id: UUID
    qualified_ref: str
    definition_id: UUID
    definition_version: str
    namespace: str
    canonical_base_ref: str | None
    active: bool
    valid_from: datetime
    valid_until: datetime | None
    canonical_controls: SecurityControls
    tenant_additions: SecurityControls | None
    effective_controls: SecurityControls
    provenance: str

    def __post_init__(self) -> None:
        parse_ref(self.qualified_ref, self.tenant_id)
        if type(self.definition_id) is not UUID or not self.definition_version:
            raise ValueError("Versioned definition identity is required")
        for instant in (self.valid_from, self.valid_until):
            offset = instant.utcoffset() if type(instant) is datetime else None
            if instant is not None and (
                type(instant) is not datetime
                or instant.tzinfo is None
                or offset is None
                or offset.total_seconds() != 0
            ):
                raise ValueError("Effective intervals require aware UTC")
        if self.valid_until is not None and self.valid_until <= self.valid_from:
            raise ValueError("Effective interval must be nonempty")


class ClassificationResolverV2(Protocol):
    """Public read contract; every resolution uses the caller's transaction."""

    async def resolve_current(
        self,
        reference: str,
        request: RequestContext,
        transaction: HandlerTransaction,
    ) -> ClassificationResolutionV2: ...

    async def resolve_historical(
        self,
        reference: str,
        at: datetime,
        request: RequestContext,
        transaction: HandlerTransaction,
    ) -> ClassificationResolutionV2: ...
