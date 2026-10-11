"""ADR-025 neutral values remain canonical, bounded and explicitly untrusted."""

import json
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import TypeAdapter, ValidationError

from businessos.sdk import (
    CANONICAL_FIELD_LOCATOR_CONTRACT_ID,
    OWNER_FIELD_WITNESS_CONTRACT_ID,
    CanonicalFieldLocator,
    DynamicFieldPin,
    FieldAuthorityProvenance,
    FieldContractFailure,
    FieldFailureReason,
    FieldIdentityKind,
    FieldOperationIntent,
    FieldProviderDescriptor,
    FieldSchemaPin,
    OwnerFieldLifecycle,
    OwnerFieldWitness,
    OwnerFieldWitnessResult,
    UTCInstant,
)

TENANT = UUID("018f045a-673b-7a01-8080-080808080808")
FIELD = UUID("018f045a-673b-7a02-8080-080808080808")
DEFINITION = UUID("018f045a-673b-7a03-8080-080808080808")
REVISION = UUID("018f045a-673b-7a04-8080-080808080808")
TYPE = UUID("018f045a-673b-7a05-8080-080808080808")
RECORD = UUID("018f045a-673b-7a06-8080-080808080808")
DIGEST = "a" * 64


def _locator(**changes: object) -> CanonicalFieldLocator:
    values: dict[str, object] = {
        "tenant_id": TENANT,
        "resource_namespace": "foundation.party.party",
        "resource_contract_version": "1",
        "resource_owner_module_id": "foundation.party",
        "field_id": FIELD,
        "field_contract_id": "foundation.party.fixed-fields.v1",
        "field_contract_version": "1.0",
        "identity_kind": FieldIdentityKind.FIXED,
    }
    return CanonicalFieldLocator.model_validate({**values, **changes})


def _provider(**changes: object) -> FieldProviderDescriptor:
    return FieldProviderDescriptor.model_validate(
        {
            "owner_module_id": "foundation.party",
            "contract_id": OWNER_FIELD_WITNESS_CONTRACT_ID,
            "contract_version": "1.0",
            "registration_id": "registration:party-field-owner",
            "resource_namespace": "foundation.party.party",
            "resource_contract_version": "1",
            **changes,
        }
    )


def _provenance(
    provider: FieldProviderDescriptor | None = None, /, **changes: object
) -> FieldAuthorityProvenance:
    return FieldAuthorityProvenance.model_validate(
        {
            "provider": provider or _provider(),
            "approved_install_id": "protected-install:party-v1",
            "artifact_identity": "package:businessos-party@0.2.0",
            "process_generation": 4,
            "durable_fence_id": "activation:party",
            "durable_generation": 9,
            **changes,
        }
    )


def _pin(**changes: object) -> DynamicFieldPin:
    return DynamicFieldPin.model_validate(
        {
            "definition_id": DEFINITION,
            "revision_id": REVISION,
            "revision_digest": DIGEST,
            "schema_pin": FieldSchemaPin(
                definition_id=DEFINITION, revision_id=REVISION, digest=DIGEST
            ),
            **changes,
        }
    )


def _witness(**changes: object) -> OwnerFieldWitness:
    return OwnerFieldWitness.model_validate(
        {
            "locator": _locator(),
            "field_exists": True,
            "lifecycle": OwnerFieldLifecycle.CURRENT,
            "operation": "field.read",
            "resource_record_id": RECORD,
            "field_meaning_fingerprint": DIGEST,
            "owner_provenance": _provenance(),
            **changes,
        }
    )


def test_exact_logical_key_excludes_descriptive_names_and_has_one_absence() -> None:
    locator = _locator()
    assert locator.logical_key() == (
        TENANT,
        "foundation.party.party",
        "1",
        "foundation.party",
        FIELD,
        "foundation.party.fixed-fields.v1",
        "1.0",
        None,
        None,
    )
    assert json.loads(locator.canonical_json())["dynamic_definition_id"] is None
    assert json.loads(locator.canonical_json())["dynamic_type_id"] is None
    assert CANONICAL_FIELD_LOCATOR_CONTRACT_ID == "platform.canonical-field-locator.v1"


@pytest.mark.parametrize(
    "changes",
    [
        {"resource_namespace": "foundation.partyx.party"},
        {"resource_namespace": "foundation.Party.party"},
        {"resource_namespace": "foundation.party..party"},
        {"resource_namespace": "foundation.party.party\n"},
        {"resource_namespace": "foundation.party.p\u0430rty"},
        {"resource_owner_module_id": "foundation.organization"},
        {"resource_owner_module_id": "foundation.party "},
        {"field_contract_id": "Field label"},
        {"field_contract_id": "foundation.party."},
        {"field_contract_id": "a" * 201},
    ],
)
def test_identifiers_reject_lookalikes_and_wrong_owner(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _locator(**changes)


def test_exact_module_identity_preserves_embedded_underscores() -> None:
    locator = _locator(
        resource_namespace="partner.example_owner.custom_record",
        resource_owner_module_id="partner.example_owner",
    )
    assert locator.resource_owner_module_id == "partner.example_owner"


@pytest.mark.parametrize("version", ["", "01", "1.00", "1.", "v1", ">=1", "1rc1", " 1", "1\n"])
def test_malformed_exact_versions_are_rejected(version: str) -> None:
    with pytest.raises(ValidationError):
        _locator(resource_contract_version=version)
    with pytest.raises(ValidationError):
        _locator(field_contract_version=version)


def test_resource_versions_are_exact_not_semver_normalized() -> None:
    first = _locator(resource_contract_version="1")
    second = _locator(resource_contract_version="1.0")
    assert first.logical_key() != second.logical_key()
    assert first.canonical_bytes() != second.canonical_bytes()


@pytest.mark.parametrize("version", ["2.0", 1, True, None])
def test_unknown_envelope_versions_cannot_be_downgraded(version: object) -> None:
    with pytest.raises(ValidationError):
        _locator(version=version)


@pytest.mark.parametrize("value", [str(FIELD), FIELD.hex, 1, True, None])
def test_python_identity_requires_exact_uuid(value: object) -> None:
    with pytest.raises(ValidationError):
        _locator(field_id=value)


@pytest.mark.parametrize(
    "value", [str(FIELD).upper(), FIELD.hex, "{" + str(FIELD) + "}", "urn:uuid:" + str(FIELD)]
)
def test_json_uuid_rejects_noncanonical_spellings(value: str) -> None:
    raw = _locator().model_dump(mode="json")
    raw["field_id"] = value
    with pytest.raises(ValidationError):
        CanonicalFieldLocator.model_validate_json(json.dumps(raw))


@pytest.mark.parametrize(
    ("kind", "definition", "type_id"),
    [
        (FieldIdentityKind.FIXED, None, None),
        (FieldIdentityKind.DEFINITION, DEFINITION, None),
        (FieldIdentityKind.TYPED_DEFINITION, DEFINITION, TYPE),
    ],
)
def test_all_supported_dynamic_identity_combinations(
    kind: FieldIdentityKind, definition: UUID | None, type_id: UUID | None
) -> None:
    locator = _locator(
        identity_kind=kind, dynamic_definition_id=definition, dynamic_type_id=type_id
    )
    assert CanonicalFieldLocator.model_validate_json(locator.canonical_json()) == locator


@pytest.mark.parametrize(
    ("kind", "definition", "type_id"),
    [
        (FieldIdentityKind.FIXED, DEFINITION, None),
        (FieldIdentityKind.FIXED, None, TYPE),
        (FieldIdentityKind.DEFINITION, None, None),
        (FieldIdentityKind.DEFINITION, DEFINITION, TYPE),
        (FieldIdentityKind.TYPED_DEFINITION, DEFINITION, None),
        (FieldIdentityKind.TYPED_DEFINITION, None, TYPE),
    ],
)
def test_ambiguous_partial_dynamic_combinations_fail(
    kind: FieldIdentityKind, definition: UUID | None, type_id: UUID | None
) -> None:
    with pytest.raises(ValidationError):
        _locator(identity_kind=kind, dynamic_definition_id=definition, dynamic_type_id=type_id)


@pytest.mark.parametrize(
    "property_name",
    [
        "label",
        "column_name",
        "translation_key",
        "entity_type",
        "field_name",
        "trusted",
        "invocation_token",
    ],
)
def test_unknown_authority_or_descriptive_properties_are_rejected(property_name: str) -> None:
    with pytest.raises(ValidationError):
        _locator(**{property_name: "attacker supplied"})


def test_uuid_collision_does_not_collapse_other_contract_identity_members() -> None:
    first = _locator()
    versions = _locator(field_contract_version="2")
    contracts = _locator(field_contract_id="foundation.party.other-fields.v1")
    namespaces = _locator(resource_namespace="foundation.party.person")
    assert len({item.logical_key() for item in (first, versions, contracts, namespaces)}) == 4


def test_dynamic_pin_requires_complete_matching_schema_identity() -> None:
    pin = _pin()
    assert DynamicFieldPin.model_validate_json(pin.canonical_json()) == pin
    for field, value in (
        ("definition_id", uuid4()),
        ("revision_id", uuid4()),
        ("digest", "b" * 64),
    ):
        raw = pin.schema_pin.model_dump()
        raw[field] = value
        with pytest.raises(ValidationError, match="exact immutable definition revision"):
            _pin(schema_pin=FieldSchemaPin.model_validate(raw))
    with pytest.raises(ValidationError):
        _pin(schema_pin=None)


def test_static_witness_matches_only_exact_tenant_field_operation_and_record() -> None:
    witness = _witness()
    witness.require_matches(_locator(), "field.read", RECORD)
    for locator in (_locator(tenant_id=uuid4()), _locator(field_id=uuid4())):
        with pytest.raises(ValueError, match="identity mismatch"):
            witness.require_matches(locator, "field.read", RECORD)
    with pytest.raises(ValueError, match="operation mismatch"):
        witness.require_matches(_locator(), "field.write", RECORD)
    with pytest.raises(ValueError, match="record identity mismatch"):
        witness.require_matches(_locator(), "field.read", uuid4())
    with pytest.raises(ValueError, match="record identity mismatch"):
        witness.require_matches(_locator(), "field.read", None)


@pytest.mark.parametrize(
    "provider_changes",
    [
        {
            "owner_module_id": "foundation.organization",
            "resource_namespace": "foundation.organization.company",
        },
        {"resource_namespace": "foundation.party.person"},
        {"resource_contract_version": "1.0"},
        {"contract_id": "platform.other-witness.v1"},
        {"contract_version": "2.0"},
    ],
)
def test_owner_witness_rejects_provider_or_resource_identity_mismatch(
    provider_changes: dict[str, object],
) -> None:
    with pytest.raises(ValidationError, match="exact owner/resource/contract identity"):
        _witness(owner_provenance=_provenance(_provider(**provider_changes)))


def test_dynamic_definition_provenance_is_separately_attributed() -> None:
    locator = _locator(
        identity_kind=FieldIdentityKind.DEFINITION,
        dynamic_definition_id=DEFINITION,
        field_contract_id="foundation.party.custom-fields.v1",
    )
    definition_provider = _provider(
        owner_module_id="foundation.metadata",
        resource_namespace=None,
        resource_contract_version=None,
    )
    witness = _witness(
        locator=locator,
        dynamic_pin=_pin(),
        definition_owner_module_id="foundation.metadata",
        definition_owner_provenance=_provenance(definition_provider),
    )
    assert witness.owner_provenance.provider.owner_module_id == "foundation.party"
    assert witness.definition_owner_provenance is not None
    assert witness.definition_owner_provenance.provider.owner_module_id == "foundation.metadata"
    with pytest.raises(ValidationError, match="actual owner/witness contract"):
        _witness(
            locator=locator,
            dynamic_pin=_pin(),
            definition_owner_module_id="foundation.party",
            definition_owner_provenance=_provenance(definition_provider),
        )
    with pytest.raises(ValidationError, match="complete"):
        _witness(locator=locator)


@pytest.mark.parametrize(
    "changes",
    [
        {"contract_id": "foundation.metadata.definition.v1"},
        {"contract_version": "2.0"},
    ],
)
def test_definition_provenance_requires_exact_neutral_witness_provider(
    changes: dict[str, object],
) -> None:
    locator = _locator(
        identity_kind=FieldIdentityKind.DEFINITION,
        dynamic_definition_id=DEFINITION,
        field_contract_id="foundation.party.custom-fields.v1",
    )
    provider = _provider(
        owner_module_id="foundation.metadata",
        resource_namespace=None,
        resource_contract_version=None,
        **changes,
    )
    with pytest.raises(ValidationError, match="actual owner/witness contract"):
        _witness(
            locator=locator,
            dynamic_pin=_pin(),
            definition_owner_module_id="foundation.metadata",
            definition_owner_provenance=_provenance(provider),
        )


def test_fixed_field_cannot_claim_dynamic_pin_or_definition_owner() -> None:
    with pytest.raises(ValidationError, match="complete"):
        _witness(dynamic_pin=_pin())
    with pytest.raises(ValidationError, match="complete"):
        _witness(definition_owner_module_id="foundation.metadata")


def test_field_existence_and_lifecycle_do_not_imply_access() -> None:
    unavailable = _witness(field_exists=False, lifecycle=OwnerFieldLifecycle.UNAVAILABLE)
    retired = _witness(lifecycle=OwnerFieldLifecycle.RETIRED)
    assert not unavailable.field_exists
    assert retired.lifecycle is OwnerFieldLifecycle.RETIRED
    assert "allowed" not in unavailable.model_dump()
    with pytest.raises(ValidationError, match="existence"):
        _witness(field_exists=False)


def test_provenance_generations_and_install_identity_cannot_be_substituted() -> None:
    provenance = _provenance()
    assert provenance.process_generation == 4
    assert provenance.durable_generation == 9
    assert provenance.artifact_sha256 is None
    for name, value in (
        ("process_generation", True),
        ("durable_generation", "9"),
        ("durable_generation", 0),
        ("approved_install_id", ""),
        ("artifact_identity", "secret\n"),
        ("artifact_sha256", "A" * 64),
    ):
        with pytest.raises(ValidationError):
            _provenance(**{name: value})


def test_provider_descriptors_allow_another_owners_public_contract_but_not_resource_claim() -> None:
    provider = _provider(contract_id="foundation.policy.field-tag-facts.v1")
    assert provider.contract_id == "foundation.policy.field-tag-facts.v1"
    with pytest.raises(ValidationError, match="exact owner"):
        _provider(resource_namespace="foundation.metadata.custom_entity")
    with pytest.raises(ValidationError, match="together"):
        _provider(resource_namespace=None)


def test_nested_boundary_values_are_immutable_and_unknown_properties_fail() -> None:
    witness = _witness()
    for model, attribute, value in (
        (witness, "operation", "field.write"),
        (witness.locator, "tenant_id", uuid4()),
        (witness.owner_provenance, "durable_generation", 10),
        (witness.owner_provenance.provider, "owner_module_id", "foundation.metadata"),
    ):
        with pytest.raises(ValidationError):
            setattr(model, attribute, value)
    raw = witness.model_dump()
    provider = witness.owner_provenance.provider.model_dump()
    provider["privileged_generation"] = object()
    provenance = witness.owner_provenance.model_dump()
    provenance["provider"] = provider
    raw["owner_provenance"] = provenance
    with pytest.raises(ValidationError):
        OwnerFieldWitness.model_validate(raw)


def test_nested_construct_or_copy_cannot_skip_representation_validation() -> None:
    copied = _locator().model_copy(update={"field_id": "forged"})
    constructed = CanonicalFieldLocator.model_construct(
        **{**_locator().model_dump(), "dynamic_type_id": TYPE}
    )
    for invalid in (copied, constructed):
        with pytest.raises(ValidationError):
            _witness(locator=invalid)
        with pytest.raises(ValidationError):
            FieldOperationIntent(tenant_id=TENANT, operation="field.read", fields=(invalid,))


def test_canonical_serialization_is_deterministic_and_never_recovers_capability() -> None:
    witness = _witness()
    raw = witness.model_dump(mode="json")
    reversed_json = json.dumps(dict(reversed(tuple(raw.items()))))
    restored = OwnerFieldWitness.model_validate_json(reversed_json)
    assert restored == witness
    assert restored.canonical_bytes() == witness.canonical_bytes()
    assert restored.canonical_bytes() == restored.canonical_json().encode("utf-8")
    assert b": " not in restored.canonical_bytes()
    assert b", " not in restored.canonical_bytes()
    assert not hasattr(restored, "trusted")
    assert not hasattr(restored, "authenticated")
    assert not hasattr(restored, "invoke")
    assert not hasattr(restored, "transaction")
    assert not hasattr(restored, "invocation_token")


def test_result_requires_one_facts_or_failure_payload_without_public_fallback() -> None:
    facts = OwnerFieldWitnessResult(status="facts", witness=_witness())
    failure = FieldContractFailure(reason=FieldFailureReason.TAG_BINDING_UNAVAILABLE)
    denied = OwnerFieldWitnessResult(status="failure", failure=failure)
    assert facts.witness is not None
    assert denied.witness is None
    assert "allowed" not in denied.model_dump()
    for changes in (
        {"status": "facts"},
        {"status": "failure"},
        {"status": "facts", "witness": _witness(), "failure": failure},
        {"status": "public", "witness": _witness()},
    ):
        with pytest.raises(ValidationError):
            OwnerFieldWitnessResult.model_validate(changes)


def test_failure_reasons_are_total_bounded_and_version_diagnostic_is_inert() -> None:
    assert len(FieldFailureReason) == 13
    for reason in FieldFailureReason:
        failure = FieldContractFailure(reason=reason)
        assert FieldContractFailure.model_validate_json(failure.canonical_json()) == failure
    unsupported = FieldContractFailure(
        reason=FieldFailureReason.UNSUPPORTED_CONTRACT_VERSION,
        contract_id=CANONICAL_FIELD_LOCATOR_CONTRACT_ID,
        requested_contract_version="2.0",
    )
    assert unsupported.requested_contract_version == "2.0"
    with pytest.raises(ValidationError):
        FieldContractFailure.model_validate({"reason": "public"})
    with pytest.raises(ValidationError):
        FieldContractFailure(
            reason=FieldFailureReason.TENANT_MISMATCH,
            contract_id=CANONICAL_FIELD_LOCATOR_CONTRACT_ID,
            requested_contract_version="2.0",
        )


def test_operation_intent_accepts_exactly_128_distinct_fields_and_is_immutable() -> None:
    fields = tuple(_locator(field_id=UUID(int=index + 1)) for index in range(128))
    intent = FieldOperationIntent(tenant_id=TENANT, operation="field.read", fields=fields)
    assert len(intent.fields) == 128
    assert FieldOperationIntent.model_validate_json(intent.canonical_json()) == intent
    immutable_member = "fields"
    with pytest.raises(ValidationError):
        setattr(intent, immutable_member, ())
    with pytest.raises(ValidationError):
        FieldOperationIntent(
            tenant_id=TENANT,
            operation="field.read",
            fields=(*fields, _locator(field_id=UUID(int=129))),
        )
    with pytest.raises(ValidationError):
        FieldOperationIntent(tenant_id=TENANT, operation="field.read", fields=())


@pytest.mark.parametrize(
    "second",
    [
        _locator(),
        _locator(tenant_id=UUID(int=12)),
        _locator(field_contract_version="2"),
        _locator(field_id=UUID(int=13), resource_namespace="foundation.party.person"),
        _locator(field_id=UUID(int=14), resource_contract_version="1.0"),
        _locator(
            field_id=UUID(int=15),
            identity_kind=FieldIdentityKind.DEFINITION,
            dynamic_definition_id=DEFINITION,
        ),
    ],
)
def test_operation_envelope_rejects_duplicate_conflicts_and_mixed_families(
    second: CanonicalFieldLocator,
) -> None:
    with pytest.raises(ValidationError):
        FieldOperationIntent(tenant_id=TENANT, operation="field.read", fields=(_locator(), second))


def test_utc_intervals_require_aware_utc_instead_of_local_or_naive_instants() -> None:
    adapter: TypeAdapter[datetime] = TypeAdapter(UTCInstant)
    now = datetime(2026, 10, 11, tzinfo=UTC)
    assert adapter.validate_python(now, strict=True) == now
    for invalid in (
        now.replace(tzinfo=None),
        now.replace(tzinfo=timezone(timedelta(hours=6))),
    ):
        with pytest.raises(ValidationError):
            adapter.validate_python(invalid, strict=True)
