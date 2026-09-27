"""ADR-017 rejects caller-controlled facts and V1 destructive authority."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, cast
from uuid import uuid4

import pytest
from businessos_data_governance.contracts import DataGovernanceHooks
from businessos_data_governance.models import ExpiryAction
from businessos_data_governance.retention_v2 import (
    DestructiveCleanupRequestedV2,
    HoldScope,
    PlaceRetentionHoldV2,
    RetentionSubjectKey,
    SetRetentionPolicyV2,
    normalize_owner_facts,
)
from businessos_identity.contracts import TenantExecutionBinding, WorkloadIdentityFacts
from businessos_proof.module import ProofModule
from pydantic import ValidationError

from businessos.context import RequestContext, TenantContext
from businessos.errors import BusinessOSError
from businessos.messages import EventHandlingContext
from businessos.resources import ResourceOwnerFacts


def _key() -> RetentionSubjectKey:
    return RetentionSubjectKey(
        tenant_id=uuid4(),
        owner_module_id="example.phase1-proof",
        resource_namespace="example.phase1-proof.proof-record",
        contract_version="1",
        entity_type="proof_record",
        record_id=uuid4(),
    )


def _facts(key: RetentionSubjectKey, **changes: object) -> ResourceOwnerFacts:
    values: dict[str, object] = {
        "entity_type": key.entity_type,
        "retention_category": "proof",
        "retention_anchor_at": datetime(2025, 1, 1, tzinfo=UTC),
        "supported_actions": frozenset({"archive", "anonymize", "purge"}),
    }
    values.update(changes)
    return ResourceOwnerFacts(
        tenant_id=key.tenant_id,
        namespace=key.resource_namespace,
        record_id=key.record_id,
        owner_module_id=key.owner_module_id,
        contract_version=key.contract_version,
        lifecycle="current",
        facts=values,
    )


def test_locked_facts_require_identity_category_utc_and_supported_action() -> None:
    key = _key()
    assert normalize_owner_facts(key, _facts(key)).retention_category == "proof"
    for changed in (
        {"retention_category": ""},
        {"retention_anchor_at": datetime(2025, 1, 1)},
        {"retention_anchor_at": datetime(2025, 1, 1, tzinfo=timezone(timedelta(hours=6)))},
        {"entity_type": "other"},
        {"supported_actions": frozenset({"destroy_everything"})},
    ):
        with pytest.raises(Exception, match="Locked owner facts"):
            normalize_owner_facts(key, _facts(key, **changed))
    for changed_identity in (
        {"tenant_id": uuid4()},
        {"record_id": uuid4()},
        {"namespace": "another.resource"},
        {"owner_module_id": "another.owner"},
        {"contract_version": "2"},
    ):
        with pytest.raises(Exception, match="Locked owner facts"):
            normalize_owner_facts(key, replace(_facts(key), **changed_identity))
    with pytest.raises(Exception, match="no longer current"):
        normalize_owner_facts(key, replace(_facts(key), lifecycle="purged"))


def test_policy_intervals_are_half_open_and_utc() -> None:
    key = _key()
    start = datetime(2025, 1, 1, tzinfo=UTC)
    fields = dict(
        tenant_id=key.tenant_id,
        owner_module_id=key.owner_module_id,
        resource_namespace=key.resource_namespace,
        contract_version=key.contract_version,
        entity_type=key.entity_type,
        retention_category="proof",
        retention_period_days=1,
        action_on_expiry=ExpiryAction.PURGE,
        valid_from=start,
    )
    assert SetRetentionPolicyV2(**fields, valid_until=start + timedelta(days=1)).valid_until
    for invalid in (start, start - timedelta(seconds=1), start.replace(tzinfo=None)):
        with pytest.raises(ValidationError):
            SetRetentionPolicyV2(**fields, valid_until=invalid)


def test_all_hold_cannot_be_narrowed_by_category() -> None:
    with pytest.raises(ValidationError, match="ALL hold must be category-free"):
        PlaceRetentionHoldV2(
            subject=_key(), scope=HoldScope.ALL, retention_category="proof", reason="invalid"
        )
    with pytest.raises(ValidationError, match="CATEGORY hold requires"):
        PlaceRetentionHoldV2(subject=_key(), scope=HoldScope.CATEGORY, reason="invalid")


@pytest.mark.asyncio
async def test_v1_destructive_hook_fails_closed() -> None:
    with pytest.raises(PermissionError, match=r"destructive-lifecycle\.v2"):
        await DataGovernanceHooks().anonymize_subject(uuid4(), uuid4())


@pytest.mark.asyncio
async def test_cleanup_contract_rejects_keys_wrong_resource_and_wrong_tenant() -> None:
    key = _key()
    event = DestructiveCleanupRequestedV2(
        tenant_id=key.tenant_id,
        correlation_id="cleanup-test",
        decision_id=uuid4(),
        owner_module_id=key.owner_module_id,
        resource_namespace=key.resource_namespace,
        contract_version=key.contract_version,
        entity_type=key.entity_type,
        record_id=key.record_id,
        action=ExpiryAction.PURGE,
    )
    with pytest.raises(ValidationError):
        DestructiveCleanupRequestedV2.model_validate(
            {**event.model_dump(mode="json"), "object_key": "../another-tenant/private"}
        )
    with pytest.raises(ValidationError):
        DestructiveCleanupRequestedV2.model_validate(
            {**event.model_dump(mode="json"), "action": "arbitrary"}
        )
    request = RequestContext(tenant=TenantContext(uuid4(), key.tenant_id, uuid4()))
    context = EventHandlingContext(request, cast(Any, object()), cast(Any, object()))
    proof = ProofModule()
    await proof._cleanup_destructive(
        event.model_copy(update={"owner_module_id": "another.owner"}), context
    )
    with pytest.raises(BusinessOSError, match="Cleanup resource identity mismatch"):
        await proof._cleanup_destructive(
            event.model_copy(update={"resource_namespace": "another.resource"}), context
        )
    wrong_request = RequestContext(tenant=TenantContext(uuid4(), uuid4(), uuid4()))
    wrong_context = EventHandlingContext(wrong_request, cast(Any, object()), cast(Any, object()))
    with pytest.raises(PermissionError, match="Verified tenant workload"):
        await proof._cleanup_destructive(event, wrong_context)


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ("subscriber", "source_event_id"))
async def test_cleanup_rejects_mismatched_delivery_before_external_effects(
    monkeypatch: pytest.MonkeyPatch, mismatch: str
) -> None:
    key = _key()
    event = DestructiveCleanupRequestedV2(
        tenant_id=key.tenant_id,
        correlation_id="cleanup-source-test",
        decision_id=uuid4(),
        owner_module_id=key.owner_module_id,
        resource_namespace=key.resource_namespace,
        contract_version=key.contract_version,
        entity_type=key.entity_type,
        record_id=key.record_id,
        action=ExpiryAction.PURGE,
    )
    tenant = TenantContext(uuid4(), key.tenant_id, uuid4())
    binding = object.__new__(TenantExecutionBinding)
    object.__setattr__(binding, "tenant_id", key.tenant_id)
    object.__setattr__(
        binding,
        "workload",
        WorkloadIdentityFacts(
            installation_id=tenant.installation_id,
            workload_id=uuid4(),
            principal_type="service_account",
            purpose="event-delivery",
            process_class="event-worker",
            credential_reference="test",
            credential_generation=1,
            verification_method="test",
            verification_reference=uuid4(),
        ),
    )
    object.__setattr__(binding, "purpose", "event-delivery")
    object.__setattr__(binding, "subscriber", "example.phase1-proof.external-retention-cleanup")
    object.__setattr__(binding, "source_event_id", event.event_id)
    object.__setattr__(binding, mismatch, uuid4() if mismatch == "source_event_id" else "other")
    monkeypatch.setattr(TenantExecutionBinding, "assert_active", lambda self, transaction: None)
    # Persistence and storage are deliberately absent: reaching either would fail.
    context = EventHandlingContext(
        RequestContext(tenant=tenant), cast(Any, object()), cast(Any, object()), binding
    )
    with pytest.raises(PermissionError, match="Verified tenant workload"):
        await ProofModule()._cleanup_destructive(event, context)
