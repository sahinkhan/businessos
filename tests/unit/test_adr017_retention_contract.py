"""ADR-017 trusted facts and compatibility boundary checks."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from businessos_data_governance.contracts import DataGovernanceHooks
from businessos_data_governance.models import ExpiryAction
from businessos_data_governance.retention_v2 import (
    HoldScope,
    PlaceRetentionHoldV2,
    RetentionSubjectKey,
    SetRetentionPolicyV2,
    normalize_owner_facts,
)
from pydantic import ValidationError

from businessos.resources import ResourceOwnerFacts


def _key() -> RetentionSubjectKey:
    return RetentionSubjectKey(
        tenant_id=uuid4(),
        owner_module_id="foundation.party",
        resource_namespace="foundation.party.party",
        contract_version="1",
        entity_type="party",
        record_id=uuid4(),
    )


def _facts(key: RetentionSubjectKey, **changes: object) -> ResourceOwnerFacts:
    values = {
        "entity_type": key.entity_type,
        "retention_category": "customer",
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


def test_owner_facts_require_exact_identity_category_and_aware_utc_anchor() -> None:
    key = _key()
    normalized = normalize_owner_facts(key, _facts(key))
    assert normalized.key == key
    assert normalized.retention_category == "customer"
    for changed in (
        {"retention_category": ""},
        {"retention_anchor_at": datetime(2025, 1, 1)},
        {"retention_anchor_at": datetime(2025, 1, 1, tzinfo=timezone(timedelta(hours=6)))},
        {"entity_type": "other"},
        {"supported_actions": frozenset({"destroy_everything"})},
    ):
        with pytest.raises(Exception, match="Locked owner facts"):
            normalize_owner_facts(key, _facts(key, **changed))
    with pytest.raises(Exception, match="Locked owner facts"):
        normalize_owner_facts(key, replace(_facts(key), tenant_id=uuid4()))


def test_policy_interval_is_half_open_utc() -> None:
    key = _key()
    start = datetime(2025, 1, 1, tzinfo=UTC)
    fields = dict(
        tenant_id=key.tenant_id,
        owner_module_id=key.owner_module_id,
        resource_namespace=key.resource_namespace,
        contract_version=key.contract_version,
        entity_type=key.entity_type,
        retention_category="customer",
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
            subject=_key(),
            scope=HoldScope.ALL,
            retention_category="customer",
            reason="would falsely claim all-category protection",
        )
    with pytest.raises(ValidationError, match="CATEGORY hold requires"):
        PlaceRetentionHoldV2(
            subject=_key(), scope=HoldScope.CATEGORY, reason="category not specified"
        )


@pytest.mark.asyncio
async def test_v1_destructive_hook_fails_closed() -> None:
    with pytest.raises(PermissionError, match=r"destructive-lifecycle\.v2"):
        await DataGovernanceHooks().anonymize_subject(uuid4(), uuid4())
