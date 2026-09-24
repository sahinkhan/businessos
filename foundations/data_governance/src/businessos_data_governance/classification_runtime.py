"""Data Governance owned V2 classification resolution and Policy adapter."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from businessos_policy.v2_contracts import PolicyClassificationFactsV2
from sqlalchemy import text

from businessos.sdk import (
    BusinessOSError,
    HandlerTransaction,
    RequestContext,
    ResourceLocator,
    ResourceOwnerFacts,
)

from .classification_v2 import (
    CANONICAL_NAMESPACE,
    CONTRACT_VERSION,
    ClassificationResolutionV2,
    SecurityControls,
    parse_ref,
)

OWNER = "foundation.data_governance"


def _deny(reason: str) -> BusinessOSError:
    return BusinessOSError("classification_unavailable", reason, status_code=403)


def _trusted_tenant(request: RequestContext) -> UUID:
    if request.tenant is None:
        raise _deny("Trusted tenant context is required")
    return request.tenant.tenant_id


def _controls(row: Any) -> SecurityControls:
    return SecurityControls(
        sensitivity_level=row.sensitivity_level,
        required_controls=frozenset(row.required_controls),
        restrictions=frozenset(row.restrictions),
        allowed_audience=(
            None if row.allowed_audience is None else frozenset(row.allowed_audience)
        ),
        mandatory_masking=row.mandatory_masking,
    )


def _utc(instant: datetime | None) -> datetime | None:
    return None if instant is None else instant.astimezone(UTC)


class DataGovernanceClassificationV2:
    """One same-UOW resolver for public, Policy, and ADR-018 projections."""

    version = "2"

    async def _resolve(
        self,
        tenant_id: UUID,
        reference: str,
        transaction: HandlerTransaction,
        *,
        at: datetime,
        lock: bool,
    ) -> ClassificationResolutionV2:
        kind, code = parse_ref(reference, tenant_id)
        offset = at.utcoffset()
        if at.tzinfo is None or offset is None or offset.total_seconds() != 0:
            raise _deny("Classification instant must be aware UTC")
        if kind == "core":
            return await self._canonical(tenant_id, reference, code, transaction, at, lock)
        return await self._tenant(tenant_id, reference, code, transaction, at, lock)

    async def _canonical(
        self,
        tenant_id: UUID,
        reference: str,
        code: str,
        transaction: HandlerTransaction,
        at: datetime,
        lock: bool,
    ) -> ClassificationResolutionV2:
        # PostgreSQL row locks require UPDATE privilege. Canonical tables are
        # read-only to businessos_app, so use a transaction-scoped shared
        # advisory lock for the governed canonical identity instead.
        if lock:
            await transaction.persistence.execute(
                text(
                    "SELECT pg_advisory_xact_lock_shared("
                    "hashtextextended('classification-core:' || :code, 0))"
                ),
                {"code": code},
            )
            await transaction.persistence.execute(
                text(
                    "SELECT pg_advisory_xact_lock_shared(hashtextextended("
                    "'classification-overlay:' || :tenant || ':' || :code, 0))"
                ),
                {"tenant": str(tenant_id), "code": code},
            )
            # A writer may have committed a newer overlay while we waited.
            # Capture the live instant only after both admission locks.
            at = datetime.now(UTC)
        canonical_suffix = ""
        overlay_suffix = " FOR SHARE" if lock else ""
        definitions = (
            await transaction.persistence.execute(
                text(
                    "SELECT id, qualified_ref, is_active FROM "
                    "platform_gov.classification_definitions WHERE code = :code "
                    "AND qualified_ref = :ref LIMIT 2" + canonical_suffix
                ),
                {"code": code, "ref": reference},
            )
        ).all()
        if len(definitions) != 1:
            raise _deny("Canonical classification is unknown or ambiguous")
        definition = definitions[0]
        versions = (
            await transaction.persistence.execute(
                text(
                    "SELECT version, valid_from, valid_until, sensitivity_level, "
                    "required_controls, restrictions, allowed_audience, mandatory_masking "
                    "FROM platform_gov.classification_versions "
                    "WHERE definition_id = :id AND valid_from <= :at "
                    "AND (valid_until IS NULL OR :at < valid_until) "
                    "ORDER BY valid_from DESC LIMIT 2" + canonical_suffix
                ),
                {"id": definition.id, "at": at},
            )
        ).all()
        if len(versions) != 1:
            raise _deny("Effective canonical version is unavailable or ambiguous")
        version = versions[0]
        canonical = _controls(version)
        # The overlay lookup is mandatory even when no overlay exists. A query
        # failure never becomes a canonical-only authorization decision.
        overlays = (
            await transaction.persistence.execute(
                text(
                    "SELECT version, valid_from, valid_until, sensitivity_level, "
                    "required_controls, restrictions, allowed_audience, mandatory_masking "
                    "FROM platform_gov.classification_overlays "
                    "WHERE tenant_id = :tenant AND canonical_definition_id = :id "
                    "AND valid_from <= :at AND (valid_until IS NULL OR :at < valid_until) "
                    "ORDER BY valid_from DESC LIMIT 2" + overlay_suffix
                ),
                {"tenant": tenant_id, "id": definition.id, "at": at},
            )
        ).all()
        if len(overlays) > 1:
            raise _deny("Effective tenant overlay is ambiguous")
        if not overlays:
            registered = await transaction.persistence.execute(
                text(
                    "SELECT 1 FROM platform_gov.classification_overlays "
                    "WHERE tenant_id = :tenant AND canonical_definition_id = :id "
                    "AND valid_from <= :at ORDER BY valid_from DESC LIMIT 1"
                ),
                {"tenant": tenant_id, "id": definition.id, "at": at},
            )
            if registered.first() is not None:
                raise _deny("Registered tenant overlay has no effective version")
        addition = _controls(overlays[0]) if overlays else None
        try:
            effective = canonical if addition is None else canonical.compose(addition)
        except ValueError as exc:
            raise _deny("Tenant overlay weakens canonical controls") from exc
        valid_from = _utc(version.valid_from)
        valid_until = _utc(version.valid_until)
        assert valid_from is not None
        if overlays:
            overlay_from = _utc(overlays[0].valid_from)
            assert overlay_from is not None
            valid_from = max(valid_from, overlay_from)
            if overlays[0].valid_until is not None:
                overlay_until = _utc(overlays[0].valid_until)
                assert overlay_until is not None
                valid_until = (
                    overlay_until if valid_until is None else min(valid_until, overlay_until)
                )
        return ClassificationResolutionV2(
            tenant_id=tenant_id,
            qualified_ref=reference,
            definition_id=definition.id,
            definition_version=str(version.version),
            namespace="core",
            canonical_base_ref=reference,
            active=definition.is_active,
            valid_from=valid_from,
            valid_until=valid_until,
            canonical_controls=canonical,
            tenant_additions=addition,
            effective_controls=effective,
            provenance="governed_canonical_and_tenant_overlay"
            if addition
            else "governed_canonical",
        )

    async def _tenant(
        self,
        tenant_id: UUID,
        reference: str,
        code: str,
        transaction: HandlerTransaction,
        at: datetime,
        lock: bool,
    ) -> ClassificationResolutionV2:
        definitions = (
            await transaction.persistence.execute(
                text(
                    "SELECT t.id, t.is_active, c.qualified_ref AS base_ref "
                    "FROM platform_gov.tenant_classifications t "
                    "LEFT JOIN platform_gov.classification_definitions c "
                    "ON c.id = t.canonical_base_id "
                    "WHERE t.tenant_id = :tenant AND t.code = :code "
                    "AND t.qualified_ref = :ref LIMIT 2"
                ),
                {"tenant": tenant_id, "code": code, "ref": reference},
            )
        ).all()
        if len(definitions) != 1:
            raise _deny("Tenant classification is unknown or ambiguous")
        definition = definitions[0]
        base = None
        if definition.base_ref is not None:
            base = await self._canonical(
                tenant_id,
                definition.base_ref,
                definition.base_ref[5:],
                transaction,
                at,
                lock,
            )
        if lock:
            locked = (
                await transaction.persistence.execute(
                    text(
                        "SELECT t.id, t.is_active, c.qualified_ref AS base_ref "
                        "FROM platform_gov.tenant_classifications t "
                        "LEFT JOIN platform_gov.classification_definitions c "
                        "ON c.id = t.canonical_base_id "
                        "WHERE t.tenant_id = :tenant AND t.id = :id LIMIT 2 FOR SHARE OF t"
                    ),
                    {"tenant": tenant_id, "id": definition.id},
                )
            ).all()
            if len(locked) != 1 or locked[0] != definition:
                raise _deny("Tenant classification changed during locked resolution")
            # The definition row serializes semantic-version writers.
            at = datetime.now(UTC)
            if definition.base_ref is not None:
                # A scheduled canonical version or overlay can turn over while
                # the tenant row lock is pending. The admission locks acquired
                # above are still held, so resolve the base again at this final
                # instant without changing the canonical-then-tenant lock order.
                base = await self._canonical(
                    tenant_id,
                    definition.base_ref,
                    definition.base_ref[5:],
                    transaction,
                    at,
                    False,
                )
        versions = (
            await transaction.persistence.execute(
                text(
                    "SELECT version, valid_from, valid_until, sensitivity_level, "
                    "required_controls, restrictions, allowed_audience, mandatory_masking "
                    "FROM platform_gov.tenant_classification_versions "
                    "WHERE tenant_id = :tenant AND definition_id = :id "
                    "AND valid_from <= :at AND (valid_until IS NULL OR :at < valid_until) "
                    "ORDER BY valid_from DESC LIMIT 2" + (" FOR SHARE" if lock else "")
                ),
                {"tenant": tenant_id, "id": definition.id, "at": at},
            )
        ).all()
        if len(versions) != 1:
            raise _deny("Effective tenant version is unavailable or ambiguous")
        version = versions[0]
        own = _controls(version)
        valid_from = version.valid_from.astimezone(UTC)
        valid_until = _utc(version.valid_until)
        # A tenant definition with an explicit base must resolve and compose
        # that base; it never replaces the canonical minimum.
        if base is not None:
            effective = base.effective_controls.compose(own)
            canonical = base.canonical_controls
            valid_from = max(valid_from, base.valid_from)
            if base.valid_until is not None:
                valid_until = (
                    base.valid_until if valid_until is None else min(valid_until, base.valid_until)
                )
        else:
            canonical = own
            effective = own
        return ClassificationResolutionV2(
            tenant_id=tenant_id,
            qualified_ref=reference,
            definition_id=definition.id,
            definition_version=str(version.version),
            namespace="tenant",
            canonical_base_ref=definition.base_ref,
            active=definition.is_active,
            valid_from=valid_from,
            valid_until=valid_until,
            canonical_controls=canonical,
            tenant_additions=own if definition.base_ref is not None else None,
            effective_controls=effective,
            provenance="tenant_definition",
        )

    async def resolve_current(
        self,
        reference: str,
        request: RequestContext,
        transaction: HandlerTransaction,
    ) -> ClassificationResolutionV2:
        return await self._resolve(
            _trusted_tenant(request), reference, transaction, at=datetime.now(UTC), lock=False
        )

    async def resolve_assignable(
        self,
        reference: str,
        request: RequestContext,
        transaction: HandlerTransaction,
    ) -> ClassificationResolutionV2:
        """Hold definition and overlay locks through the new-reference write."""
        result = await self._resolve(
            _trusted_tenant(request), reference, transaction, at=datetime.now(UTC), lock=True
        )
        if not result.active:
            raise _deny("Inactive classification cannot be newly assigned")
        return result

    async def resolve_historical(
        self,
        reference: str,
        at: datetime,
        request: RequestContext,
        transaction: HandlerTransaction,
    ) -> ClassificationResolutionV2:
        # This read contract is not installed as live Policy authority. The
        # handler exposing it must require the historical-read permission.
        return await self._resolve(
            _trusted_tenant(request), reference, transaction, at=at, lock=False
        )

    async def resolve_locked(
        self,
        tenant_id: UUID,
        classification_ref: str,
        transaction: HandlerTransaction,
    ) -> PolicyClassificationFactsV2:
        boundary = await transaction.persistence.execute(
            text("SELECT nullif(current_setting('app.tenant_id', true), '')::uuid")
        )
        if boundary.scalar_one_or_none() != tenant_id:
            raise _deny("Policy classification tenant differs from active transaction")
        result = await self._resolve(
            tenant_id, classification_ref, transaction, at=datetime.now(UTC), lock=True
        )
        return PolicyClassificationFactsV2(
            tenant_id=tenant_id,
            classification_ref=result.qualified_ref,
            owner_module_id=OWNER,
            definition_id=result.definition_id,
            definition_version=result.definition_version,
            active=True,  # Existing references remain live after deactivation.
            sensitive=result.effective_controls.sensitivity_level > 1,
            valid_from=result.valid_from,
            valid_until=result.valid_until,
        )

    async def read_facts(
        self,
        locator: ResourceLocator,
        request: RequestContext,
        transaction: HandlerTransaction,
    ) -> ResourceOwnerFacts:
        return await self._owner_facts(locator, request, transaction, lock=False)

    async def read_locked_facts(
        self,
        locator: ResourceLocator,
        action: str,
        request: RequestContext,
        transaction: HandlerTransaction,
    ) -> ResourceOwnerFacts:
        if action != "classification.read":
            raise _deny("Unsupported classification owner action")
        return await self._owner_facts(locator, request, transaction, lock=True)

    async def _owner_facts(
        self,
        locator: ResourceLocator,
        request: RequestContext,
        transaction: HandlerTransaction,
        *,
        lock: bool,
    ) -> ResourceOwnerFacts:
        tenant_id = _trusted_tenant(request)
        if (
            locator.namespace != CANONICAL_NAMESPACE
            or locator.contract_version != CONTRACT_VERSION
            or locator.tenant_id != tenant_id
        ):
            raise _deny("Classification locator does not match canonical owner")
        # The identity lookup is not a lock; _resolve takes the shared locks
        # in the same definition/version/overlay order as the Policy adapter.
        suffix = ""
        canonical = (
            await transaction.persistence.execute(
                text(
                    "SELECT qualified_ref FROM platform_gov.classification_definitions "
                    "WHERE id = :id LIMIT 2" + suffix
                ),
                {"id": locator.record_id},
            )
        ).all()
        tenant = (
            await transaction.persistence.execute(
                text(
                    "SELECT qualified_ref FROM platform_gov.tenant_classifications "
                    "WHERE tenant_id = :tenant AND id = :id LIMIT 2" + suffix
                ),
                {"tenant": tenant_id, "id": locator.record_id},
            )
        ).all()
        if len(canonical) + len(tenant) != 1:
            raise _deny("Classification record identity is unavailable or ambiguous")
        reference = (canonical or tenant)[0].qualified_ref
        result = await self._resolve(
            tenant_id, reference, transaction, at=datetime.now(UTC), lock=lock
        )
        if result.definition_id != locator.record_id:
            raise _deny("Classification record changed during owner projection")
        return ResourceOwnerFacts(
            tenant_id=tenant_id,
            namespace=CANONICAL_NAMESPACE,
            record_id=result.definition_id,
            owner_module_id=OWNER,
            contract_version=CONTRACT_VERSION,
            lifecycle="current",
            facts={
                "classification_ref": reference,
                "definition_version": result.definition_version,
                "active": True,
                "sensitive": result.effective_controls.sensitivity_level > 1,
            },
        )
