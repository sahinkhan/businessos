"""Versioned Audit integrity does not reinterpret historical encodings."""

from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from businessos_audit import AuditEvidenceV2, compute_audit_checksum, compute_audit_checksum_v3
from pydantic import ValidationError


def test_historical_encodings_are_stable_and_distinct_from_v3() -> None:
    tenant, occurred = uuid4(), datetime(2026, 9, 25, tzinfo=UTC)

    def checksum(version: str) -> str:
        return compute_audit_checksum(
            tenant_id=tenant,
            occurred_at=occurred,
            actor_id="legacy-claim",
            action="created",
            resource_type="resource",
            resource_id="42",
            status="success",
            integrity_version=version,
        )

    assert checksum("1") == checksum("1")
    assert checksum("2") != checksum("1")


@pytest.mark.parametrize(
    "path,value",
    [
        (("actor_id",), "other"),
        (("provenance_v3", "actual_actor", "id"), "other"),
        (("provenance_v3", "origin_actor", "id"), "other"),
        (("provenance_v3", "support"), {"target": "untrusted"}),
        (("source_event_id",), uuid4()),
        (("evidence_v3", "status"), "denied"),
        (("evidence_v3", "details", "result"), "other"),
        (("previous_checksum",), "f" * 64),
    ],
)
def test_v3_checksum_covers_trusted_envelope(path: tuple[str, ...], value: object) -> None:
    event_id = uuid4()
    envelope: dict[str, object] = {
        "id": uuid4(),
        "tenant_id": uuid4(),
        "occurred_at": datetime(2026, 9, 25, tzinfo=UTC),
        "actor_id": str(uuid4()),
        "actor_type": "service_account",
        "action": "policy.commit",
        "resource_type": "example.resource@2",
        "resource_id": str(uuid4()),
        "status": "allowed",
        "correlation_id": "test-correlation",
        "trace_id": "test-trace",
        "previous_checksum": "a" * 64,
        "provenance_v3": {
            "actual_actor": {"id": str(uuid4()), "type": "service_account"},
            "origin_actor": {"id": str(uuid4()), "type": "user"},
            "support": None,
        },
        "evidence_v3": {"status": "allowed", "details": {"result": "accepted"}},
        "source_event_id": event_id,
        "projection_kind": "policy-decision-v2",
    }
    baseline = compute_audit_checksum_v3(envelope)
    tampered = deepcopy(envelope)
    current: dict[str, object] = tampered
    for key in path[:-1]:
        nested = current[key]
        assert isinstance(nested, dict)
        current = nested
    current[path[-1]] = value
    assert compute_audit_checksum_v3(tampered) != baseline


def test_v2_evidence_cannot_supply_actor_tenant_or_event_time() -> None:
    for field, value in (
        ("actor_id", str(uuid4())),
        ("actor_type", "user"),
        ("tenant_id", str(uuid4())),
        ("occurred_at", datetime.now(UTC).isoformat()),
    ):
        with pytest.raises(ValidationError):
            AuditEvidenceV2.model_validate(
                {
                    "action": "created",
                    "resource_type": "example",
                    field: value,
                }
            )


def test_v2_evidence_rejects_raw_credentials_and_non_json_values() -> None:
    for details in (
        {"secret": "raw-value"},
        {"nested": {"access_token": "raw-value"}},
        {"bytes": b"raw-secret"},
        {"non_finite": float("nan")},
    ):
        with pytest.raises(ValidationError):
            AuditEvidenceV2(action="created", resource_type="example", details=details)
