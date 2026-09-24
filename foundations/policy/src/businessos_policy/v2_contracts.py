"""Public, immutable Policy V2 decision and owner-fact contracts."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol, cast
from uuid import UUID

from businessos_identity import PrincipalReference

from businessos.sdk import (
    DependencyKey,
    HandlerTransaction,
    RequestContext,
    ResourceLocator,
    ResourceOwnerFacts,
)

from .models import FieldAccessType


class DecisionMode(StrEnum):
    PRESENTATION = "presentation"
    READ = "read"
    MUTATION = "mutation"
    APPROVAL = "approval"


class DecisionReason(StrEnum):
    ALLOWED = "allowed"
    PRINCIPAL_MISMATCH = "principal_mismatch"
    INACTIVE_MEMBERSHIP = "inactive_membership"
    ACTION_UNMAPPED = "action_unmapped"
    OWNER_UNAVAILABLE = "resource_owner_unavailable"
    FACT_MISMATCH = "resource_fact_mismatch"
    NO_ACTIVE_ROLE = "no_active_role"
    SCOPE_MISMATCH = "scope_mismatch"
    RECORD_DENIED = "record_denied"
    CLASSIFICATION_UNAVAILABLE = "classification_unavailable"
    FIELD_NOT_ALLOWED = "field_not_allowed"
    APPROVAL_LIMIT_MISSING = "approval_limit_missing"
    APPROVAL_LIMIT_EXCEEDED = "approval_limit_exceeded"
    CURRENCY_MISMATCH = "currency_mismatch"
    OPERATION_MISMATCH = "operation_mismatch"
    SUPPORT_GRANT_MISSING = "support_grant_missing"


def _freeze_attributes(values: Mapping[str, object]) -> Mapping[str, object]:
    def freeze(value: object) -> object:
        if value is None or type(value) in (str, int, bool, UUID, Decimal):
            return value
        if type(value) is tuple:
            return tuple(freeze(item) for item in cast(tuple[object, ...], value))
        if type(value) is dict or type(value) is MappingProxyType:
            return _freeze_attributes(cast(Mapping[str, object], value))
        raise ValueError("Unsupported Policy V2 fact shape")

    if type(values) not in (dict, MappingProxyType) or not all(type(key) is str for key in values):
        raise ValueError("Policy V2 fact names must be canonical strings")
    return MappingProxyType({key: freeze(value) for key, value in values.items()})


@dataclass(frozen=True, slots=True)
class AuthorizationResourceFactsV2:
    tenant_id: UUID
    namespace: str
    contract_version: str
    record_id: UUID
    owner_module_id: str
    lifecycle: str
    company_id: UUID | None = None
    legal_entity_id: UUID | None = None
    operating_site_id: UUID | None = None
    business_unit_id: UUID | None = None
    record_owner_id: UUID | None = None
    record_owner_type: str | None = None
    classification_ref: str | None = None
    field_classifications: Mapping[str, str] = MappingProxyType({})
    attributes: Mapping[str, object] = MappingProxyType({})
    normalized_operation: AuthorizationOperationFactsV2 | None = None

    def __post_init__(self) -> None:
        for value in (
            self.tenant_id,
            self.record_id,
            self.company_id,
            self.legal_entity_id,
            self.operating_site_id,
            self.business_unit_id,
            self.record_owner_id,
        ):
            if value is not None and type(value) is not UUID:
                raise ValueError("Policy V2 resource IDs must be exact UUIDs")
        if any(
            type(value) is not str
            for value in (
                self.namespace,
                self.contract_version,
                self.owner_module_id,
                self.lifecycle,
            )
        ) or (self.classification_ref is not None and type(self.classification_ref) is not str):
            raise ValueError("Policy V2 resource strings must be exact")
        if self.record_owner_type is not None and self.record_owner_type not in (
            "user",
            "service_account",
            "device",
        ):
            raise ValueError("Owner principal type is invalid")
        if self.record_owner_type is not None and type(self.record_owner_type) is not str:
            raise ValueError("Owner principal type must be exact")
        if type(self.field_classifications) not in (dict, MappingProxyType) or any(
            type(name) is not str or type(reference) is not str
            for name, reference in self.field_classifications.items()
        ):
            raise ValueError("Field classification metadata is invalid")
        object.__setattr__(
            self, "field_classifications", MappingProxyType(dict(self.field_classifications))
        )
        object.__setattr__(self, "attributes", _freeze_attributes(self.attributes))
        if (
            self.normalized_operation is not None
            and type(self.normalized_operation) is not AuthorizationOperationFactsV2
        ):
            raise ValueError("Trusted owner operation facts are invalid")

    @classmethod
    def from_owner(
        cls, owner: ResourceOwnerFacts, locator: ResourceLocator, owner_module_id: str
    ) -> AuthorizationResourceFactsV2:
        if (
            type(owner) is not ResourceOwnerFacts
            or owner.tenant_id != locator.tenant_id
            or owner.namespace != locator.namespace
            or owner.contract_version != locator.contract_version
            or owner.record_id != locator.record_id
            or owner.owner_module_id != owner_module_id
            or owner.lifecycle != "current"
        ):
            raise ValueError("Owner facts do not match the canonical resource")
        raw = owner.facts
        known = (
            "company_id",
            "legal_entity_id",
            "operating_site_id",
            "business_unit_id",
            "record_owner_id",
        )

        def optional_uuid(name: str) -> UUID | None:
            value = raw.get(name)
            if value is not None and type(value) is not UUID:
                raise ValueError("Owner scope facts must be exact UUIDs")
            return value

        ids = {name: optional_uuid(name) for name in known}
        classification = raw.get("classification_ref")
        if classification is not None and type(classification) is not str:
            raise ValueError("Owner classification reference is invalid")
        owner_type = raw.get("record_owner_type")
        if owner_type is not None and type(owner_type) is not str:
            raise ValueError("Record owner principal type is invalid")
        field_classifications = raw.get("field_classifications", {})
        if type(field_classifications) not in (dict, MappingProxyType):
            raise ValueError("Field classification metadata is invalid")
        attributes = raw.get("attributes", {})
        if type(attributes) not in (dict, MappingProxyType):
            raise ValueError("Owner ABAC facts are invalid")
        owner_operation = raw.get("normalized_operation")
        if owner_operation is not None and type(owner_operation) not in (dict, MappingProxyType):
            raise ValueError("Owner normalized operation is invalid")
        normalized = None
        if owner_operation is not None:
            values = cast(Mapping[str, object], owner_operation)
            if not values.keys() <= {
                "action",
                "amount",
                "currency",
                "quantity",
                "target_state",
                "attributes",
            }:
                raise ValueError("Owner normalized operation contains unknown values")
            normalized = AuthorizationOperationFactsV2(
                action=cast(str, values.get("action")),
                amount=cast(Decimal | None, values.get("amount")),
                currency=cast(str | None, values.get("currency")),
                quantity=cast(Decimal | None, values.get("quantity")),
                target_state=cast(str | None, values.get("target_state")),
                attributes=cast(Mapping[str, object], values.get("attributes", {})),
            )
        return cls(
            tenant_id=owner.tenant_id,
            namespace=owner.namespace,
            contract_version=owner.contract_version,
            record_id=owner.record_id,
            owner_module_id=owner.owner_module_id,
            lifecycle=owner.lifecycle,
            company_id=ids["company_id"],
            legal_entity_id=ids["legal_entity_id"],
            operating_site_id=ids["operating_site_id"],
            business_unit_id=ids["business_unit_id"],
            record_owner_id=ids["record_owner_id"],
            record_owner_type=owner_type,
            classification_ref=classification,
            field_classifications=cast(Mapping[str, str], field_classifications),
            attributes=cast(Mapping[str, object], attributes),
            normalized_operation=normalized,
        )


@dataclass(frozen=True, slots=True)
class AuthorizationOperationFactsV2:
    """Owner-normalized proposed operation; never a transport payload."""

    action: str
    amount: Decimal | None = None
    currency: str | None = None
    quantity: Decimal | None = None
    target_state: str | None = None
    attributes: Mapping[str, object] = MappingProxyType({})

    def __post_init__(self) -> None:
        if type(self.action) is not str or not re.fullmatch(r"[a-z][a-z0-9_.-]*", self.action):
            raise ValueError("Operation action must be canonical")
        if self.amount is not None and (
            type(self.amount) is not Decimal or not self.amount.is_finite()
        ):
            raise ValueError("Operation amount must be finite Decimal")
        if self.quantity is not None and (
            type(self.quantity) is not Decimal or not self.quantity.is_finite()
        ):
            raise ValueError("Operation quantity must be finite Decimal")
        if (self.amount is None) != (self.currency is None):
            raise ValueError("Amount and currency must be supplied together")
        if self.currency is not None and (
            type(self.currency) is not str or not re.fullmatch(r"[A-Z]{3}", self.currency)
        ):
            raise ValueError("Operation currency must be canonical ISO code")
        if self.target_state is not None and type(self.target_state) is not str:
            raise ValueError("Operation target state must be a string")
        object.__setattr__(self, "attributes", _freeze_attributes(self.attributes))


@dataclass(frozen=True, slots=True)
class PolicyDecisionEvidenceV2:
    tenant_id: UUID
    principal: PrincipalReference
    decision_at: datetime
    mode: DecisionMode
    action: str
    locator: ResourceLocator | None
    allowed: bool
    reason: DecisionReason
    policy_ids: tuple[UUID, ...] = ()

    def __post_init__(self) -> None:
        if (
            type(self.tenant_id) is not UUID
            or type(self.principal) is not PrincipalReference
            or type(self.principal.principal_id) is not UUID
            or type(self.principal.principal_type) is not str
            or self.principal.principal_type not in ("user", "service_account", "device")
            or type(self.decision_at) is not datetime
            or type(self.mode) is not DecisionMode
            or type(self.action) is not str
            or type(self.allowed) is not bool
            or type(self.reason) is not DecisionReason
            or (self.locator is not None and self.locator.tenant_id != self.tenant_id)
            or type(self.policy_ids) is not tuple
            or any(type(value) is not UUID for value in self.policy_ids)
            or self.allowed != (self.reason is DecisionReason.ALLOWED)
        ):
            raise ValueError("Policy decision evidence is inconsistent")
        offset = self.decision_at.utcoffset()
        if self.decision_at.tzinfo is None or offset is None:
            raise ValueError("Policy decision instant must be aware UTC")
        if offset.total_seconds() != 0:
            raise ValueError("Policy decision instant must be UTC")


@dataclass(frozen=True, slots=True)
class PolicyClassificationFactsV2:
    tenant_id: UUID
    classification_ref: str
    owner_module_id: str
    definition_id: UUID
    definition_version: str
    active: bool
    ambiguous: bool = False
    sensitive: bool = True

    def __post_init__(self) -> None:
        if (
            type(self.tenant_id) is not UUID
            or type(self.definition_id) is not UUID
            or type(self.classification_ref) is not str
            or not self.classification_ref
            or type(self.owner_module_id) is not str
            or not self.owner_module_id
            or type(self.definition_version) is not str
            or not self.definition_version
            or any(
                type(value) is not bool for value in (self.active, self.ambiguous, self.sensitive)
            )
        ):
            raise ValueError("Classification facts require exact owner provenance")


class PolicyClassificationFactsProvider(Protocol):
    async def resolve(
        self,
        tenant_id: UUID,
        classification_ref: str,
        decision_at: datetime,
        transaction: HandlerTransaction,
    ) -> PolicyClassificationFactsV2: ...


POLICY_CLASSIFICATION_FACTS_V2 = DependencyKey[PolicyClassificationFactsProvider](
    "businessos.policy.classification_facts.v2"
)


class CommitPermitV2(Protocol):
    async def apply(
        self,
        operation: AuthorizationOperationFactsV2,
        owner_apply: Callable[
            [AuthorizationOperationFactsV2], Awaitable[AuthorizationOperationFactsV2]
        ],
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class PolicyReadDecisionV2:
    evidence: PolicyDecisionEvidenceV2
    field_access: FieldAccessType | None = None


@dataclass(frozen=True, slots=True)
class PolicyCommitDecisionV2:
    evidence: PolicyDecisionEvidenceV2
    permit: CommitPermitV2 | None


class PolicyAuthorizationV2(Protocol):
    """Policy-owned same-UOW port; methods never finish the transaction."""

    async def authorize_read(
        self,
        request: RequestContext,
        transaction: HandlerTransaction,
        action: str,
        locator: ResourceLocator,
        *,
        mode: DecisionMode = DecisionMode.READ,
    ) -> PolicyReadDecisionV2: ...

    async def authorize_mutation(
        self,
        request: RequestContext,
        transaction: HandlerTransaction,
        operation: AuthorizationOperationFactsV2,
        locator: ResourceLocator,
    ) -> PolicyCommitDecisionV2: ...

    async def evaluate_field(
        self,
        request: RequestContext,
        transaction: HandlerTransaction,
        locator: ResourceLocator,
        field_name: str,
        requested_access: FieldAccessType = FieldAccessType.READ,
    ) -> PolicyReadDecisionV2: ...

    async def evaluate_approval(
        self,
        request: RequestContext,
        transaction: HandlerTransaction,
        operation: AuthorizationOperationFactsV2,
        locator: ResourceLocator,
    ) -> PolicyCommitDecisionV2: ...

    async def authorize_support_access(
        self,
        request: RequestContext,
        transaction: HandlerTransaction,
    ) -> PolicyReadDecisionV2: ...


POLICY_AUTHORIZATION_V2 = DependencyKey[PolicyAuthorizationV2]("businessos.policy.authorization.v2")
