"""Permanent contract checks for inert, additive ADR-025 Policy interfaces."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from businessos_policy import (
    EFFECTIVE_CLASSIFICATION_CONTROLS_CONTRACT_ID,
    FIELD_CLASSIFICATION_COMPOSITION_CAPABILITY,
    FIELD_TAG_FACTS_CONTRACT_ID,
    FieldClassificationEnrollment,
    PolicyClassificationDefinitionIdentity,
    PolicyClassificationFactsV2,
    PolicyClassificationOverlayIdentity,
    PolicyEffectiveClassificationControlsFacts,
    PolicyEffectiveClassificationControlsResult,
    PolicyFieldTagFacts,
    PolicyFieldTagFactsResult,
)
from pydantic import ValidationError

from businessos.sdk import (
    OWNER_FIELD_WITNESS_CONTRACT_ID,
    CanonicalFieldLocator,
    DynamicFieldPin,
    FieldAuthorityProvenance,
    FieldContractFailure,
    FieldFailureReason,
    FieldIdentityKind,
    FieldProviderDescriptor,
    FieldSchemaPin,
)

TENANT = UUID("00000000-0000-4000-8000-000000000001")
OTHER_TENANT = UUID("00000000-0000-4000-8000-000000000002")
FIELD = UUID("00000000-0000-4000-8000-000000000003")
BINDING = UUID("00000000-0000-4000-8000-000000000004")
DEFINITION = UUID("00000000-0000-4000-8000-000000000005")
BASE_DEFINITION = UUID("00000000-0000-4000-8000-000000000006")
REVISION = UUID("00000000-0000-4000-8000-000000000007")
INSTANT = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
DIGEST = "1" * 64


def provider(contract_id: str) -> FieldProviderDescriptor:
    return FieldProviderDescriptor(
        owner_module_id="foundation.data_governance",
        contract_id=contract_id,
        contract_version="1.0",
        registration_id="governance-field-provider",
        resource_namespace=None,
        resource_contract_version=None,
    )


def provenance(contract_id: str) -> FieldAuthorityProvenance:
    return FieldAuthorityProvenance(
        provider=provider(contract_id),
        approved_install_id="approved-governance-install",
        artifact_identity="governance-wheel-0.4.0",
        artifact_sha256=DIGEST,
        process_generation=3,
        durable_fence_id="governance-activation-fence",
        durable_generation=7,
    )


def locator(kind: FieldIdentityKind = FieldIdentityKind.FIXED) -> CanonicalFieldLocator:
    return CanonicalFieldLocator(
        tenant_id=TENANT,
        resource_namespace="foundation.party.party",
        resource_contract_version="1",
        resource_owner_module_id="foundation.party",
        field_id=FIELD,
        field_contract_id="foundation.party.fields.v1",
        field_contract_version="1.0",
        identity_kind=kind,
        dynamic_definition_id=None if kind is FieldIdentityKind.FIXED else DEFINITION,
        dynamic_type_id=FIELD if kind is FieldIdentityKind.TYPED_DEFINITION else None,
    )


def pin(revision_id: UUID = REVISION) -> DynamicFieldPin:
    return DynamicFieldPin(
        definition_id=DEFINITION,
        revision_id=revision_id,
        revision_digest=DIGEST,
        schema_pin=FieldSchemaPin(definition_id=DEFINITION, revision_id=revision_id, digest=DIGEST),
    )


def tag_payload(kind: FieldIdentityKind = FieldIdentityKind.FIXED) -> dict[str, Any]:
    return {
        "tenant_id": TENANT,
        "locator": locator(kind),
        "binding_id": BINDING,
        "binding_version": 2,
        "binding_generation": 3,
        "field_meaning_fingerprint": DIGEST,
        "coverage_fingerprint": DIGEST,
        "classification_ref": "core:PUBLIC",
        "mandatory_tag_masking": True,
        "valid_from": INSTANT,
        "valid_until": INSTANT + timedelta(hours=1),
        "resolved_at": INSTANT,
        "lifecycle": "current",
        "dynamic_coverage": () if kind is FieldIdentityKind.FIXED else (pin(),),
        "provenance": provenance(FIELD_TAG_FACTS_CONTRACT_ID),
    }


def controls_payload() -> dict[str, Any]:
    return {
        "tenant_id": TENANT,
        "classification_ref": "core:PUBLIC",
        "definition_id": DEFINITION,
        "definition_version": "1",
        "canonical_base": None,
        "tenant_overlay": None,
        "valid_from": INSTANT,
        "valid_until": INSTANT + timedelta(hours=1),
        "resolved_at": INSTANT,
        "lifecycle": "current",
        "sensitivity_level": 1,
        "mandatory_masking": True,
        "required_controls": ("mfa", "encryption"),
        "restrictions": ("no_export",),
        "allowed_audience": None,
        "provenance": provenance(EFFECTIVE_CLASSIFICATION_CONTROLS_CONTRACT_ID),
    }


def enrollment_payload() -> dict[str, Any]:
    return {
        "capability": FIELD_CLASSIFICATION_COMPOSITION_CAPABILITY,
        "action": "field.read",
        "mode": "read",
        "resource_namespace": "foundation.party.party",
        "resource_contract_version": "1",
        "resource_owner_module_id": "foundation.party",
        "identity_kind": FieldIdentityKind.FIXED,
        "locator_contract_version": "1.0",
        "owner_witness_contract_version": "1.0",
        "tag_facts_contract_version": "1.0",
        "effective_controls_contract_version": "1.0",
        "owner_provider": FieldProviderDescriptor(
            owner_module_id="foundation.party",
            contract_id=OWNER_FIELD_WITNESS_CONTRACT_ID,
            contract_version="1.0",
            registration_id="party-owner-fields",
            resource_namespace="foundation.party.party",
            resource_contract_version="1",
        ),
        "definition_owner_provider": None,
        "tag_provider": provider(FIELD_TAG_FACTS_CONTRACT_ID),
        "effective_controls_provider": provider(EFFECTIVE_CLASSIFICATION_CONTROLS_CONTRACT_ID),
        "supported_control_vocabulary": ("mfa", "no_export", "encryption"),
    }


def test_tag_masking_is_explicit_even_for_public_reference() -> None:
    facts = PolicyFieldTagFacts.model_validate(tag_payload())
    assert facts.classification_ref == "core:PUBLIC"
    assert facts.mandatory_tag_masking is True
    payload = tag_payload()
    del payload["mandatory_tag_masking"]
    with pytest.raises(ValidationError):
        PolicyFieldTagFacts.model_validate(payload)


@pytest.mark.parametrize(
    "name,value",
    [
        ("tenant_id", OTHER_TENANT),
        ("classification_ref", "PUBLIC"),
        ("classification_ref", "core:public"),
        ("classification_ref", f"tenant:{OTHER_TENANT}:PUBLIC"),
        ("classification_ref", "core:PUBLIC\n"),
        ("binding_version", 0),
        ("binding_version", True),
        ("binding_generation", "3"),
        ("mandatory_tag_masking", 0),
        ("coverage_fingerprint", "A" * 64),
        ("lifecycle", "tombstone"),
        ("resolved_at", INSTANT + timedelta(hours=1)),
        ("valid_until", INSTANT),
        ("valid_from", INSTANT + timedelta(seconds=1)),
        ("resolved_at", datetime(2026, 10, 11, 12, 0)),
        ("version", "2.0"),
        ("unknown", "value"),
    ],
)
def test_tag_rejects_malformed_or_unavailable_facts(name: str, value: object) -> None:
    payload = tag_payload()
    payload[name] = value
    with pytest.raises(ValidationError):
        PolicyFieldTagFacts.model_validate(payload)


@pytest.mark.parametrize("kind", [FieldIdentityKind.DEFINITION, FieldIdentityKind.TYPED_DEFINITION])
def test_dynamic_coverage_pins_exact_definition_and_all_retained_revisions(
    kind: FieldIdentityKind,
) -> None:
    earlier = UUID("00000000-0000-4000-8000-000000000000")
    payload = tag_payload(kind)
    payload["dynamic_coverage"] = (pin(), pin(earlier))
    facts = PolicyFieldTagFacts.model_validate(payload)
    assert tuple(value.revision_id for value in facts.dynamic_coverage) == (earlier, REVISION)
    reverse = {**payload, "dynamic_coverage": tuple(reversed(payload["dynamic_coverage"]))}
    assert facts.canonical_bytes() == PolicyFieldTagFacts.model_validate(reverse).canonical_bytes()
    for coverage in ((), (pin(), pin())):
        with pytest.raises(ValidationError):
            PolicyFieldTagFacts.model_validate({**payload, "dynamic_coverage": coverage})
    mismatched_locator = locator(kind).model_dump()
    mismatched_locator["dynamic_definition_id"] = OTHER_TENANT
    with pytest.raises(ValidationError):
        PolicyFieldTagFacts.model_validate(
            {**payload, "locator": CanonicalFieldLocator.model_validate(mismatched_locator)}
        )


def test_fixed_field_rejects_dynamic_coverage() -> None:
    with pytest.raises(ValidationError):
        PolicyFieldTagFacts.model_validate({**tag_payload(), "dynamic_coverage": (pin(),)})


def test_effective_controls_preserve_masking_and_audience_semantics() -> None:
    payload = controls_payload()
    facts = PolicyEffectiveClassificationControlsFacts.model_validate(payload)
    assert facts.sensitivity_level == 1
    assert facts.mandatory_masking is True
    assert facts.allowed_audience is None
    assert facts.required_controls == ("encryption", "mfa")
    empty = PolicyEffectiveClassificationControlsFacts.model_validate(
        {**payload, "allowed_audience": ()}
    )
    assert empty.allowed_audience == ()
    assert empty.canonical_bytes() != facts.canonical_bytes()
    reversed_controls = {**payload, "required_controls": ("encryption", "mfa")}
    assert (
        PolicyEffectiveClassificationControlsFacts.model_validate(
            reversed_controls
        ).canonical_bytes()
        == facts.canonical_bytes()
    )


@pytest.mark.parametrize(
    "name,value",
    [
        ("sensitivity_level", 0),
        ("sensitivity_level", 6),
        ("sensitivity_level", True),
        ("mandatory_masking", "false"),
        ("definition_version", "01"),
        ("classification_ref", f"tenant:{OTHER_TENANT}:LOCAL"),
        ("required_controls", ("mfa", "mfa")),
        ("restrictions", ("",)),
        ("required_controls", ("x" * 101,)),
        ("allowed_audience", (10,)),
        ("allowed_audience", ("staff", "staff")),
        ("required_controls", tuple(f"control_{index}" for index in range(129))),
        ("lifecycle", "retired"),
        ("resolved_at", INSTANT + timedelta(hours=1)),
        ("version", "1.1"),
        ("allowed", True),
    ],
)
def test_full_controls_reject_unsupported_or_incomplete_shapes(name: str, value: object) -> None:
    payload = controls_payload()
    payload[name] = value
    with pytest.raises(ValidationError):
        PolicyEffectiveClassificationControlsFacts.model_validate(payload)


def test_base_and_overlay_provenance_are_independently_explicit() -> None:
    overlay = PolicyClassificationOverlayIdentity(
        tenant_id=TENANT,
        canonical_definition_id=DEFINITION,
        overlay_version="2",
        provenance="tenant-overlay-transition-2",
    )
    canonical = PolicyEffectiveClassificationControlsFacts.model_validate(
        {**controls_payload(), "tenant_overlay": overlay}
    )
    assert canonical.tenant_overlay is not None
    assert canonical.tenant_overlay.overlay_version == "2"
    base = PolicyClassificationDefinitionIdentity(
        classification_ref="core:PUBLIC", definition_id=BASE_DEFINITION, definition_version="3"
    )
    tenant_overlay = PolicyClassificationOverlayIdentity(
        tenant_id=TENANT,
        canonical_definition_id=BASE_DEFINITION,
        overlay_version="4",
        provenance="tenant-overlay-transition-4",
    )
    derived = {
        **controls_payload(),
        "classification_ref": f"tenant:{TENANT}:LOCAL",
        "canonical_base": base,
        "tenant_overlay": tenant_overlay,
    }
    facts = PolicyEffectiveClassificationControlsFacts.model_validate(derived)
    assert facts.canonical_base == base
    assert facts.tenant_overlay == tenant_overlay
    for change in (
        {"canonical_base": None},
        {"tenant_overlay": overlay},
        {"classification_ref": "core:PUBLIC"},
    ):
        with pytest.raises(ValidationError):
            PolicyEffectiveClassificationControlsFacts.model_validate({**derived, **change})
    other_overlay = tenant_overlay.model_dump()
    other_overlay["tenant_id"] = OTHER_TENANT
    with pytest.raises(ValidationError):
        PolicyEffectiveClassificationControlsFacts.model_validate(
            {
                **derived,
                "tenant_overlay": PolicyClassificationOverlayIdentity.model_validate(other_overlay),
            }
        )
    with pytest.raises(ValidationError):
        PolicyClassificationDefinitionIdentity.model_validate(
            {**base.model_dump(), "classification_ref": f"tenant:{TENANT}:LOCAL"}
        )


def test_full_controls_preserve_existing_opaque_vocabulary_exactly() -> None:
    tokens = (
        "encrypt:at-rest",
        "customer restricted",
        "PII",
        "staff / operations",
        "a.b-c_d",
        "  preserve  ",
        "إدارة",
    )
    expected = tuple(sorted(tokens, key=lambda value: value.encode("utf-8")))
    facts = PolicyEffectiveClassificationControlsFacts.model_validate(
        {
            **controls_payload(),
            "required_controls": tokens,
            "restrictions": tuple(reversed(tokens)),
            "allowed_audience": tokens,
        }
    )
    assert facts.required_controls == expected
    assert facts.restrictions == expected
    assert facts.allowed_audience == expected
    assert (
        PolicyEffectiveClassificationControlsFacts.model_validate_json(facts.canonical_json())
        == facts
    )
    enrollment = FieldClassificationEnrollment.model_validate(
        {**enrollment_payload(), "supported_control_vocabulary": tokens}
    )
    assert enrollment.supported_control_vocabulary == expected
    assert (
        FieldClassificationEnrollment.model_validate_json(enrollment.canonical_json()) == enrollment
    )


@pytest.mark.parametrize("bad_owner", ["foundation.party", "foundation.policy"])
def test_policy_facts_require_governance_provider_attribution(bad_owner: str) -> None:
    payload = tag_payload()
    descriptor = provider(FIELD_TAG_FACTS_CONTRACT_ID).model_dump()
    descriptor["owner_module_id"] = bad_owner
    source = provenance(FIELD_TAG_FACTS_CONTRACT_ID).model_dump()
    source["provider"] = FieldProviderDescriptor.model_validate(descriptor)
    payload["provenance"] = FieldAuthorityProvenance.model_validate(source)
    with pytest.raises(ValidationError):
        PolicyFieldTagFacts.model_validate(payload)
    with pytest.raises(ValidationError):
        PolicyEffectiveClassificationControlsFacts.model_validate(
            {**controls_payload(), "provenance": provenance(FIELD_TAG_FACTS_CONTRACT_ID)}
        )


def test_public_facts_are_inert_frozen_and_round_trip_deterministically() -> None:
    facts = PolicyFieldTagFacts.model_validate(tag_payload(FieldIdentityKind.DEFINITION))
    immutable_mask_member = "mandatory_tag_masking"
    immutable_generation_member = "durable_generation"
    with pytest.raises(ValidationError):
        setattr(facts, immutable_mask_member, False)
    with pytest.raises(ValidationError):
        setattr(facts.provenance, immutable_generation_member, 999)
    assert PolicyFieldTagFacts.model_validate_json(facts.canonical_json()) == facts
    assert not any(
        hasattr(facts, name) for name in ("allowed", "trusted", "authenticate", "permit")
    )
    encoded = facts.canonical_json()
    assert str(TENANT) in encoded
    assert not any(name in encoded for name in ("invocation_token", "connection", "database_url"))
    controls = PolicyEffectiveClassificationControlsFacts.model_validate(controls_payload())
    assert (
        PolicyEffectiveClassificationControlsFacts.model_validate_json(controls.canonical_json())
        == controls
    )


@pytest.mark.parametrize("reason", list(FieldFailureReason))
def test_each_bounded_failure_is_explicit_and_never_a_public_or_allowed_fact(
    reason: FieldFailureReason,
) -> None:
    failure = FieldContractFailure(reason=reason)
    tag = PolicyFieldTagFactsResult(facts=None, failure=failure)
    controls = PolicyEffectiveClassificationControlsResult(facts=None, failure=failure)
    assert tag.facts is None and controls.facts is None
    assert "allowed" not in PolicyFieldTagFactsResult.model_fields
    assert "PUBLIC" not in tag.canonical_json()


def test_results_require_exactly_one_facts_or_failure() -> None:
    tag = PolicyFieldTagFacts.model_validate(tag_payload())
    controls = PolicyEffectiveClassificationControlsFacts.model_validate(controls_payload())
    failure = FieldContractFailure(reason=next(iter(FieldFailureReason)))
    assert PolicyFieldTagFactsResult(facts=tag, failure=None).facts == tag
    assert (
        PolicyEffectiveClassificationControlsResult(facts=controls, failure=None).facts == controls
    )
    for result_type, facts in (
        (PolicyFieldTagFactsResult, tag),
        (PolicyEffectiveClassificationControlsResult, controls),
    ):
        for payload in ({"facts": None, "failure": None}, {"facts": facts, "failure": failure}):
            with pytest.raises(ValidationError):
                result_type.model_validate(payload)


def test_enrollment_is_explicit_exact_and_does_not_activate_a_runtime() -> None:
    enrollment = FieldClassificationEnrollment.model_validate(enrollment_payload())
    assert enrollment.capability == "field-classification-composition.v1"
    assert enrollment.supported_control_vocabulary == ("encryption", "mfa", "no_export")
    assert not any(hasattr(enrollment, name) for name in ("activate", "fallback", "allowed"))
    assert (
        FieldClassificationEnrollment.model_validate_json(enrollment.canonical_json()) == enrollment
    )
    write = FieldClassificationEnrollment.model_validate(
        {**enrollment_payload(), "action": "field.write", "mode": "commit"}
    )
    assert write.mode == "commit"


@pytest.mark.parametrize(
    "name,value",
    [
        ("capability", "field-policy.v2"),
        ("capability", "field-classification-composition.v2"),
        ("tag_facts_contract_version", "2.0"),
        ("owner_witness_contract_version", "2.0"),
        ("locator_contract_version", "2.0"),
        ("effective_controls_contract_version", "2.0"),
        ("mode", "presentation"),
        ("action", "field read"),
        ("resource_contract_version", "2"),
        ("resource_owner_module_id", "foundation.metadata"),
        ("identity_kind", FieldIdentityKind.DEFINITION),
        ("tag_provider", provider(EFFECTIVE_CLASSIFICATION_CONTROLS_CONTRACT_ID)),
        ("supported_control_vocabulary", ("mfa", "mfa")),
        ("fallback", "field-policy.v2"),
    ],
)
def test_enrollment_rejects_fallback_version_or_family_drift(name: str, value: object) -> None:
    with pytest.raises(ValidationError):
        FieldClassificationEnrollment.model_validate({**enrollment_payload(), name: value})


def test_dynamic_enrollment_preserves_independent_definition_owner() -> None:
    definition_provider = FieldProviderDescriptor(
        owner_module_id="foundation.metadata",
        contract_id=OWNER_FIELD_WITNESS_CONTRACT_ID,
        contract_version="1.0",
        registration_id="metadata-definition-witness",
        resource_namespace=None,
        resource_contract_version=None,
    )
    enrollment = FieldClassificationEnrollment.model_validate(
        {
            **enrollment_payload(),
            "identity_kind": FieldIdentityKind.DEFINITION,
            "definition_owner_provider": definition_provider,
        }
    )
    assert enrollment.owner_provider.owner_module_id == "foundation.party"
    assert enrollment.definition_owner_provider == definition_provider
    wrong_contract = definition_provider.model_dump()
    wrong_contract["contract_id"] = "foundation.metadata.definition"
    with pytest.raises(ValidationError):
        FieldClassificationEnrollment.model_validate(
            {
                **enrollment.model_dump(),
                "definition_owner_provider": FieldProviderDescriptor.model_validate(wrong_contract),
            }
        )


def test_old_policy_v2_projection_and_public_contract_ownership_are_preserved() -> None:
    assert PolicyClassificationFactsV2.__module__ == "businessos_policy.v2_contracts"
    assert PolicyFieldTagFacts.__module__ == "businessos_policy.field_classification_contracts"
    assert (
        PolicyEffectiveClassificationControlsFacts.__module__
        == "businessos_policy.field_classification_contracts"
    )
    old = PolicyClassificationFactsV2(
        TENANT, "legacy-ref", "foundation.governance", DEFINITION, "1", True
    )
    assert old.sensitive is True
    assert not hasattr(old, "mandatory_masking")
