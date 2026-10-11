"""Inert ADR-025 Policy-owned field-tag and effective-control contracts.

These values describe future admitted provider results. Constructing, decoding or
comparing them does not authenticate a provider, issue a witness, authorize an
operation or retain an admission. Gate 1 installs no provider or evaluator.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal, Protocol, Self

from pydantic import BeforeValidator, Field, field_validator, model_validator

from businessos.sdk import (
    OWNER_FIELD_WITNESS_CONTRACT_ID,
    CanonicalFieldLocator,
    CanonicalIdentity,
    CanonicalNamespace,
    CanonicalProvenanceIdentity,
    CanonicalSHA256,
    CanonicalUUID,
    CanonicalVersion,
    DynamicFieldPin,
    FieldAuthorityProvenance,
    FieldContractFailure,
    FieldContractModel,
    FieldIdentityKind,
    FieldProviderDescriptor,
    HandlerTransaction,
    RequestContext,
    UTCInstant,
)

FIELD_TAG_FACTS_CONTRACT_ID = "foundation.policy.field-tag-facts.v1"
EFFECTIVE_CLASSIFICATION_CONTROLS_CONTRACT_ID = (
    "foundation.policy.effective-classification-controls.v1"
)
FIELD_CLASSIFICATION_COMPOSITION_CAPABILITY = "field-classification-composition.v1"
FIELD_CLASSIFICATION_CONTRACT_VERSION: Literal["1.0"] = "1.0"
_GOVERNANCE_OWNER = "foundation.data_governance"
_CLASSIFICATION_CODE = re.compile(r"[A-Z][A-Z0-9_]{1,49}\Z", re.ASCII)


def _control_token(value: object) -> str:
    """Retain the existing classification control vocabulary without normalization."""
    if type(value) is not str or not value or len(value) > 100:
        raise ValueError("classification control must be an exact nonempty bounded string")
    return value


type PolicyControlToken = Annotated[str, BeforeValidator(_control_token)]


def _qualified_reference(reference: str, tenant_id: CanonicalUUID) -> None:
    """Validate representation only; no classification lookup or authority issuance."""
    if type(reference) is not str or len(reference) > 100:
        raise ValueError("qualified classification reference is invalid")
    prefix = "core:" if reference.startswith("core:") else f"tenant:{tenant_id}:"
    if not reference.startswith(prefix) or not _CLASSIFICATION_CODE.fullmatch(
        reference[len(prefix) :]
    ):
        raise ValueError("qualified classification reference is invalid or cross-tenant")


def _current_interval(
    valid_from: UTCInstant, valid_until: UTCInstant | None, resolved_at: UTCInstant
) -> None:
    if valid_from > resolved_at or (
        valid_until is not None and (valid_until <= valid_from or resolved_at >= valid_until)
    ):
        raise ValueError("live facts require a current nonempty half-open interval")


def _governance_provider(provider: FieldProviderDescriptor, contract_id: str) -> None:
    if (
        provider.owner_module_id != _GOVERNANCE_OWNER
        or provider.contract_id != contract_id
        or provider.contract_version != FIELD_CLASSIFICATION_CONTRACT_VERSION
    ):
        raise ValueError("provider does not describe the exact Policy-owned Governance port")


class PolicyFieldTagFacts(FieldContractModel):
    """Current assignment representation, separately attributed from owner facts."""

    version: Literal["1.0"] = FIELD_CLASSIFICATION_CONTRACT_VERSION
    tenant_id: CanonicalUUID
    locator: CanonicalFieldLocator
    binding_id: CanonicalUUID
    binding_version: int = Field(ge=1, le=2**63 - 1)
    binding_generation: int = Field(ge=1, le=2**63 - 1)
    field_meaning_fingerprint: CanonicalSHA256
    coverage_fingerprint: CanonicalSHA256
    classification_ref: str = Field(min_length=1, max_length=100)
    mandatory_tag_masking: bool
    valid_from: UTCInstant
    valid_until: UTCInstant | None
    resolved_at: UTCInstant
    lifecycle: Literal["current"]
    dynamic_coverage: tuple[DynamicFieldPin, ...] = Field(max_length=128)
    provenance: FieldAuthorityProvenance

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.tenant_id != self.locator.tenant_id:
            raise ValueError("tag and canonical field tenant must match")
        _qualified_reference(self.classification_ref, self.tenant_id)
        _current_interval(self.valid_from, self.valid_until, self.resolved_at)
        _governance_provider(self.provenance.provider, FIELD_TAG_FACTS_CONTRACT_ID)
        if self.locator.identity_kind is FieldIdentityKind.FIXED:
            if self.dynamic_coverage:
                raise ValueError("fixed fields cannot carry dynamic coverage")
        elif not self.dynamic_coverage or any(
            pin.definition_id != self.locator.dynamic_definition_id for pin in self.dynamic_coverage
        ):
            raise ValueError("dynamic field coverage must match the exact definition")
        revision_ids = tuple(pin.revision_id for pin in self.dynamic_coverage)
        if len(set(revision_ids)) != len(revision_ids):
            raise ValueError("dynamic coverage cannot repeat or conflict on a revision")
        object.__setattr__(
            self,
            "dynamic_coverage",
            tuple(sorted(self.dynamic_coverage, key=lambda pin: pin.revision_id.bytes)),
        )
        return self


class PolicyFieldTagFactsResult(FieldContractModel):
    """Facts or explicit refusal; absence never represents PUBLIC or permission."""

    version: Literal["1.0"] = FIELD_CLASSIFICATION_CONTRACT_VERSION
    facts: PolicyFieldTagFacts | None
    failure: FieldContractFailure | None

    @model_validator(mode="after")
    def exclusive(self) -> Self:
        if (self.facts is None) == (self.failure is None):
            raise ValueError("exactly one of tag facts or failure is required")
        return self


class PolicyFieldTagFactsProvider(Protocol):
    """Future fixed same-UOW port; selection and authentication are outside these values.

    The locator is inert data. Before invoking a future implementation, the
    runtime must separately authenticate the neutral owner witness and active
    dispatcher admission. The provider must retain its own admission and locks
    and resolve the current binding. Neither a locator nor a serialized descriptor
    supplies that authentication. No caller-selected historical instant exists.
    """

    version: Literal["1.0"]
    descriptor: FieldProviderDescriptor

    async def resolve_locked(
        self,
        locator: CanonicalFieldLocator,
        request: RequestContext,
        transaction: HandlerTransaction,
    ) -> PolicyFieldTagFactsResult: ...


class PolicyClassificationDefinitionIdentity(FieldContractModel):
    """Exact reference and version for an effective canonical base."""

    classification_ref: str = Field(min_length=1, max_length=100)
    definition_id: CanonicalUUID
    definition_version: CanonicalVersion

    @field_validator("classification_ref")
    @classmethod
    def canonical_base_reference(cls, value: str) -> str:
        if not value.startswith("core:") or not _CLASSIFICATION_CODE.fullmatch(value[5:]):
            raise ValueError("canonical base requires a qualified core reference")
        return value


class PolicyClassificationOverlayIdentity(FieldContractModel):
    """Explicit tenant overlay identity/version; not an authenticated receipt."""

    tenant_id: CanonicalUUID
    canonical_definition_id: CanonicalUUID
    overlay_version: CanonicalVersion
    provenance: CanonicalProvenanceIdentity


class PolicyEffectiveClassificationControlsFacts(FieldContractModel):
    """Complete effective controls without changing the reduced frozen V2 facts."""

    version: Literal["1.0"] = FIELD_CLASSIFICATION_CONTRACT_VERSION
    tenant_id: CanonicalUUID
    classification_ref: str = Field(min_length=1, max_length=100)
    definition_id: CanonicalUUID
    definition_version: CanonicalVersion
    canonical_base: PolicyClassificationDefinitionIdentity | None
    tenant_overlay: PolicyClassificationOverlayIdentity | None
    valid_from: UTCInstant
    valid_until: UTCInstant | None
    resolved_at: UTCInstant
    lifecycle: Literal["current"]
    sensitivity_level: int = Field(ge=1, le=5)
    mandatory_masking: bool
    required_controls: tuple[PolicyControlToken, ...] = Field(max_length=128)
    restrictions: tuple[PolicyControlToken, ...] = Field(max_length=128)
    allowed_audience: tuple[PolicyControlToken, ...] | None = Field(max_length=128)
    provenance: FieldAuthorityProvenance

    @field_validator("required_controls", "restrictions", "allowed_audience")
    @classmethod
    def canonical_collection(cls, values: tuple[str, ...] | None) -> tuple[str, ...] | None:
        if values is None:
            return None
        if len(set(values)) != len(values):
            raise ValueError("control collections cannot contain duplicate identities")
        return tuple(sorted(values, key=lambda value: value.encode("utf-8")))

    @model_validator(mode="after")
    def consistent(self) -> Self:
        _qualified_reference(self.classification_ref, self.tenant_id)
        _current_interval(self.valid_from, self.valid_until, self.resolved_at)
        _governance_provider(
            self.provenance.provider, EFFECTIVE_CLASSIFICATION_CONTROLS_CONTRACT_ID
        )
        if self.canonical_base is not None:
            _qualified_reference(self.canonical_base.classification_ref, self.tenant_id)
            if (
                self.classification_ref.startswith("core:")
                or not self.canonical_base.classification_ref.startswith("core:")
                or self.canonical_base.definition_id == self.definition_id
            ):
                raise ValueError("canonical base is valid only for a distinct tenant definition")
        if self.tenant_overlay is not None:
            canonical_id = (
                self.canonical_base.definition_id
                if self.canonical_base is not None
                else self.definition_id
            )
            if (
                self.tenant_overlay.tenant_id != self.tenant_id
                or self.tenant_overlay.canonical_definition_id != canonical_id
                or (self.classification_ref.startswith("tenant:") and self.canonical_base is None)
            ):
                raise ValueError("overlay must match the exact tenant and canonical definition")
        return self


class PolicyEffectiveClassificationControlsResult(FieldContractModel):
    version: Literal["1.0"] = FIELD_CLASSIFICATION_CONTRACT_VERSION
    facts: PolicyEffectiveClassificationControlsFacts | None
    failure: FieldContractFailure | None

    @model_validator(mode="after")
    def exclusive(self) -> Self:
        if (self.facts is None) == (self.failure is None):
            raise ValueError("exactly one of effective control facts or failure is required")
        return self


class PolicyEffectiveClassificationControlsProvider(Protocol):
    """Future full-control port; frozen V2 behavior and Governance semantics are unchanged.

    The reference is inert intent. A later runtime gate must authenticate provider
    and active operation admission separately; none is issued by these contracts.
    """

    version: Literal["1.0"]
    descriptor: FieldProviderDescriptor

    async def resolve_locked(
        self,
        classification_ref: str,
        request: RequestContext,
        transaction: HandlerTransaction,
    ) -> PolicyEffectiveClassificationControlsResult: ...


class FieldClassificationEnrollment(FieldContractModel):
    """Descriptive opt-in requirement; parsing does not enroll any runtime operation.

    Every required port is independently pinned. An enrolled operation may never
    fall back to field-policy.v2 or discard an unsupported effective control.
    Gate 1 creates no enrollment registry, private profile or dispatch behavior.
    """

    version: Literal["1.0"] = FIELD_CLASSIFICATION_CONTRACT_VERSION
    capability: Literal["field-classification-composition.v1"]
    action: CanonicalIdentity
    mode: Literal["read", "commit"]
    resource_namespace: CanonicalNamespace
    resource_contract_version: CanonicalVersion
    resource_owner_module_id: CanonicalIdentity
    identity_kind: FieldIdentityKind
    locator_contract_version: Literal["1.0"]
    owner_witness_contract_version: Literal["1.0"]
    tag_facts_contract_version: Literal["1.0"]
    effective_controls_contract_version: Literal["1.0"]
    owner_provider: FieldProviderDescriptor
    definition_owner_provider: FieldProviderDescriptor | None
    tag_provider: FieldProviderDescriptor
    effective_controls_provider: FieldProviderDescriptor
    supported_control_vocabulary: tuple[PolicyControlToken, ...] = Field(max_length=128)

    @field_validator("supported_control_vocabulary")
    @classmethod
    def canonical_vocabulary(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("supported control vocabulary must be unique")
        return tuple(sorted(values, key=lambda value: value.encode("utf-8")))

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if (
            not self.resource_namespace.startswith(self.resource_owner_module_id + ".")
            or self.owner_provider.owner_module_id != self.resource_owner_module_id
            or self.owner_provider.resource_namespace != self.resource_namespace
            or self.owner_provider.resource_contract_version != self.resource_contract_version
            or self.owner_provider.contract_id != OWNER_FIELD_WITNESS_CONTRACT_ID
            or self.owner_provider.contract_version != self.owner_witness_contract_version
        ):
            raise ValueError("owner provider must pin the exact resource family and contract")
        if (self.identity_kind is FieldIdentityKind.FIXED) != (
            self.definition_owner_provider is None
        ):
            raise ValueError("dynamic enrollment requires a separate definition owner descriptor")
        if self.definition_owner_provider is not None and (
            self.definition_owner_provider.contract_id != OWNER_FIELD_WITNESS_CONTRACT_ID
            or self.definition_owner_provider.contract_version
            != self.owner_witness_contract_version
        ):
            raise ValueError("definition owner must support the exact witness contract version")
        _governance_provider(self.tag_provider, FIELD_TAG_FACTS_CONTRACT_ID)
        _governance_provider(
            self.effective_controls_provider, EFFECTIVE_CLASSIFICATION_CONTROLS_CONTRACT_ID
        )
        return self
