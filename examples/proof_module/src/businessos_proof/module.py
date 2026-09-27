"""Proof that an external package can use only the published BusinessOS SDK."""

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC
from importlib.resources import files
from typing import ClassVar
from uuid import UUID, uuid4

from businessos_data_governance import (
    DestructiveCleanupRequestedV2,
    ExpiryAction,
    RecordDestructiveCleanupResultV2,
)
from businessos_data_governance.retention_v2 import DECISIONS_V2, lock_governance_scope
from businessos_identity import PrincipalIdentity
from businessos_identity.contracts import TenantExecutionBinding
from businessos_identity.principal_binding import (
    bind_authenticated_principal,
    clear_authenticated_principal,
)
from pydantic import Field
from sqlalchemy import Column, DateTime, MetaData, String, Table, Text, func, select, update
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.dialects.postgresql import insert

from businessos.sdk import (
    MESSAGE_DISPATCHER,
    OBJECT_STORAGE,
    OBJECT_STORAGE_DELETE,
    BusinessOSError,
    Command,
    DependencyKey,
    DependencyScope,
    DomainEvent,
    EventHandlingContext,
    FeatureFlag,
    HandlerTransaction,
    HandlingContext,
    MetadataDeclaration,
    ModuleManifest,
    ModuleRegistration,
    PermissionDeclaration,
    Query,
    Request,
    RequestContext,
    RequestDependencyScope,
    ResourceLocator,
    ResourceOwnerFacts,
    Response,
    TenantContext,
)


@dataclass(frozen=True, slots=True)
class ProofDependency:
    """Module-owned typed service registered only through the public SDK."""

    label: str


PROOF_DEPENDENCY = DependencyKey[ProofDependency]("example.phase1-proof.service")

metadata = MetaData()
PROOF_RECORDS = Table(
    "proof_records",
    metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
    Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
    Column("command_id", PGUUID(as_uuid=True), nullable=False),
    Column("value", Text(), nullable=False),
    Column("description", Text()),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("retention_category", String(100), nullable=False, server_default="proof"),
    Column(
        "retention_anchor_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
    Column("lifecycle", String(20), nullable=False, server_default="current"),
    schema="mod_example_phase1_proof",
)


class StoreProof(Command):
    command_id: UUID = Field(default_factory=uuid4)
    value: str


class ReadProof(Query):
    pass


class ProofStored(DomainEvent):
    event_type: ClassVar[str] = "example.phase1_proof.stored"
    record_id: UUID
    command_id: UUID
    value: str


class ProofModule:
    supported_actions = frozenset({"archive", "anonymize", "purge"})
    declared_entity_types = frozenset({"proof_record"})
    resource_namespace = "example.phase1-proof.proof-record"
    resource_version = "1"

    @staticmethod
    def record_object_key(record_id: UUID) -> str:
        return f"phase1-proof/records/{record_id}.txt"

    def __init__(self) -> None:
        package = files("businessos_proof")
        manifest_data = json.loads(package.joinpath("manifest.json").read_text(encoding="utf-8"))
        self.manifest = ModuleManifest.model_validate(manifest_data)
        self.started = False
        self.events_consumed = 0
        self.dependencies_started = 0
        self.dependencies_stopped = 0

    async def register(self, registration: ModuleRegistration) -> None:
        registration.resource_owner_facts(self.resource_namespace, self.resource_version, self)
        registration.resource_owner_operation(self.resource_namespace, self.resource_version, self)
        registration.dependency(
            PROOF_DEPENDENCY,
            self._proof_dependency,
            scope=DependencyScope.REQUEST,
        )
        registration.permission(
            PermissionDeclaration(
                key="example.phase1-proof.read",
                description="Read the Phase 1 proof value",
            )
        )
        registration.permission(
            PermissionDeclaration(
                key="example.phase1-proof.write",
                description="Write the Phase 1 proof value",
            )
        )
        registration.permission(
            PermissionDeclaration(
                key="example.phase1-proof.cleanup",
                description="Clean up a committed proof retention operation",
            )
        )
        registration.metadata(
            MetadataDeclaration(
                key="example.phase1-proof.form",
                kind="form",
                version=2,
                value={"fields": ["value", "description"]},
            )
        )
        registration.feature(
            FeatureFlag(
                key="example.phase1-proof.enabled",
                description="Enable the external Phase 1 proof module",
                default=True,
            )
        )
        registration.command(
            StoreProof,
            self._store,
            permission="example.phase1-proof.write",
        )
        registration.query(
            ReadProof,
            self._read,
            permission="example.phase1-proof.read",
        )
        registration.event(
            ProofStored,
            "object-storage-projection",
            self._project,
            permission="example.phase1-proof.write",
        )
        registration.event(
            DestructiveCleanupRequestedV2,
            "external-retention-cleanup",
            self._cleanup_destructive,
            permission="example.phase1-proof.cleanup",
        )
        registration.route(
            "POST",
            "/proof/value",
            self._store_route,
            name="store",
            permission="example.phase1-proof.write",
        )
        registration.route(
            "GET",
            "/proof/value",
            self._read_route,
            name="read",
            permission="example.phase1-proof.read",
        )

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.started = False

    @asynccontextmanager
    async def _proof_dependency(self, _: object) -> AsyncGenerator[ProofDependency]:
        self.dependencies_started += 1
        try:
            yield ProofDependency(label="phase1-public-sdk")
        finally:
            self.dependencies_stopped += 1

    async def _store(self, command: StoreProof, context: HandlingContext) -> object:
        tenant = self._tenant(context.request)
        record_id = uuid4()
        statement = (
            insert(PROOF_RECORDS)
            .values(
                id=record_id,
                tenant_id=tenant.tenant_id,
                command_id=command.command_id,
                value=command.value,
            )
            .on_conflict_do_nothing(index_elements=["tenant_id", "command_id"])
            .returning(PROOF_RECORDS.c.id)
        )
        result = await context.unit_of_work.persistence.execute(statement)
        if result.scalar_one_or_none() is None:
            return {"stored": False}
        context.emit(
            ProofStored(
                tenant_id=tenant.tenant_id,
                correlation_id=context.request.correlation_id,
                record_id=record_id,
                command_id=command.command_id,
                value=command.value,
            )
        )
        return {"stored": True}

    async def _read(self, _: ReadProof, context: HandlingContext) -> object:
        tenant = self._tenant(context.request)
        result = await context.unit_of_work.persistence.execute(
            select(PROOF_RECORDS.c.value)
            .where(PROOF_RECORDS.c.tenant_id == tenant.tenant_id)
            .order_by(PROOF_RECORDS.c.created_at.desc(), PROOF_RECORDS.c.id.desc())
            .limit(1)
        )
        value = result.scalar_one_or_none()
        if value is None:
            raise BusinessOSError("not_found", "Proof value not found", status_code=404)
        return {"value": value}

    async def _project(
        self,
        event: ProofStored,
        context: EventHandlingContext,
    ) -> None:
        # The shared compatibility key is tenant-wide. Serialize every writer
        # in this post-commit worker UOW, including destructive reconciliation.
        await lock_governance_scope(context.unit_of_work, "proof-shared-object", event.tenant_id)
        changed = await context.unit_of_work.persistence.execute(
            PROOF_RECORDS.update()
            .where(
                PROOF_RECORDS.c.id == event.record_id,
                PROOF_RECORDS.c.tenant_id == event.tenant_id,
                PROOF_RECORDS.c.lifecycle == "current",
            )
            .values(description="object-storage-projection")
            .returning(PROOF_RECORDS.c.id)
        )
        if changed.scalar_one_or_none() is None:
            return
        storage = await context.dependencies.resolve(OBJECT_STORAGE)
        await storage.put(
            event.tenant_id,
            self.record_object_key(event.record_id),
            event.value.encode("utf-8"),
        )
        latest = (
            await context.unit_of_work.persistence.execute(
                select(PROOF_RECORDS.c.value)
                .where(
                    PROOF_RECORDS.c.tenant_id == event.tenant_id,
                    PROOF_RECORDS.c.lifecycle == "current",
                )
                .order_by(PROOF_RECORDS.c.created_at.desc(), PROOF_RECORDS.c.id.desc())
                .limit(1)
            )
        ).one_or_none()
        if latest is None:
            return
        await storage.put(
            event.tenant_id,
            "phase1-proof/value.txt",
            latest.value.encode("utf-8"),
        )
        self.events_consumed += 1

    async def _cleanup_destructive(
        self, event: DestructiveCleanupRequestedV2, context: EventHandlingContext
    ) -> None:
        # Every subscriber sees the event contract; only this canonical owner
        # may act on its own committed resource.
        if event.owner_module_id != self.manifest.module_id:
            return
        if (
            event.resource_namespace != self.resource_namespace
            or event.contract_version != self.resource_version
            or event.entity_type != "proof_record"
        ):
            raise BusinessOSError(
                "proof_cleanup_identity_invalid",
                "Cleanup resource identity mismatch",
                status_code=409,
            )
        tenant = context.request.tenant
        binding = context.workload_binding
        if (
            tenant is None
            or tenant.tenant_id != event.tenant_id
            or not isinstance(binding, TenantExecutionBinding)
            or binding.tenant_id != event.tenant_id
            or binding.workload.installation_id != tenant.installation_id
            or binding.workload.process_class != "event-worker"
            or binding.purpose != "event-delivery"
            or binding.subscriber != "example.phase1-proof.external-retention-cleanup"
            or binding.source_event_id != event.event_id
        ):
            raise PermissionError("Verified tenant workload required for proof cleanup")
        binding.assert_active(context.unit_of_work)
        # A committed outbox row proves delivery provenance, not that this
        # event was emitted by the protected destructive command. Bind the
        # external effect to the exact protected decision first.
        await lock_governance_scope(context.unit_of_work, "proof-shared-object", event.tenant_id)
        decision = (
            await context.unit_of_work.persistence.execute(
                select(DECISIONS_V2).where(
                    DECISIONS_V2.c.tenant_id == event.tenant_id,
                    DECISIONS_V2.c.id == event.decision_id,
                )
            )
        ).one_or_none()
        if decision is None or (
            decision.owner_module_id != event.owner_module_id
            or decision.resource_namespace != event.resource_namespace
            or decision.contract_version != event.contract_version
            or decision.entity_type != event.entity_type
            or decision.record_id != event.record_id
            or decision.action != event.action.value
        ):
            raise BusinessOSError(
                "proof_cleanup_decision_invalid",
                "Cleanup event does not match its protected decision",
                status_code=409,
            )
        if decision.external_cleanup_status == "completed":
            return
        if decision.external_cleanup_status not in {"pending", "failed"}:
            raise BusinessOSError(
                "proof_cleanup_status_invalid",
                "Cleanup decision status is invalid",
                status_code=409,
            )
        row = (
            await context.unit_of_work.persistence.execute(
                select(PROOF_RECORDS.c.lifecycle).where(
                    PROOF_RECORDS.c.tenant_id == event.tenant_id,
                    PROOF_RECORDS.c.id == event.record_id,
                )
            )
        ).one_or_none()
        expected_lifecycle = {
            ExpiryAction.ARCHIVE: "archived",
            ExpiryAction.ANONYMIZE: "anonymized",
            ExpiryAction.PURGE: "purged",
        }[event.action]
        if row is None or row.lifecycle != expected_lifecycle:
            raise BusinessOSError(
                "proof_cleanup_state_invalid", "Owner cleanup state is unavailable", status_code=409
            )
        if event.action in {ExpiryAction.ANONYMIZE, ExpiryAction.PURGE}:
            storage_delete = await context.dependencies.resolve(OBJECT_STORAGE_DELETE)
            await storage_delete.delete(event.tenant_id, self.record_object_key(event.record_id))
            surviving = (
                await context.unit_of_work.persistence.execute(
                    select(PROOF_RECORDS.c.value)
                    .where(
                        PROOF_RECORDS.c.tenant_id == event.tenant_id,
                        PROOF_RECORDS.c.lifecycle == "current",
                    )
                    .order_by(PROOF_RECORDS.c.created_at.desc(), PROOF_RECORDS.c.id.desc())
                    .limit(1)
                )
            ).one_or_none()
            if surviving is None:
                await storage_delete.delete(event.tenant_id, "phase1-proof/value.txt")
            else:
                storage = await context.dependencies.resolve(OBJECT_STORAGE)
                await storage.put(
                    event.tenant_id, "phase1-proof/value.txt", surviving.value.encode("utf-8")
                )
        dispatcher = await context.dependencies.resolve(MESSAGE_DISPATCHER)
        bind_authenticated_principal(
            context.request,
            PrincipalIdentity(
                tenant_id=event.tenant_id,
                principal_id=tenant.principal_id,
                principal_type="service_account",
                authentication_strength="verified-workload",
            ),
        )
        try:
            completion = RecordDestructiveCleanupResultV2(
                tenant_id=event.tenant_id, decision_id=event.decision_id, completed=True
            )
            completion.bind_delivery(binding, context.unit_of_work)
            await dispatcher.command(
                completion,
                context.request,
                context.dependencies,
            )
        finally:
            clear_authenticated_principal()

    async def read_facts(
        self, locator: ResourceLocator, request: RequestContext, transaction: HandlerTransaction
    ) -> ResourceOwnerFacts:
        return await self._owner_facts(locator, request, transaction, locked=False)

    async def read_locked_facts(
        self,
        locator: ResourceLocator,
        action: str,
        request: RequestContext,
        transaction: HandlerTransaction,
    ) -> ResourceOwnerFacts:
        if action not in (*self.supported_actions, "hold"):
            raise BusinessOSError(
                "proof_action_unsupported", "Unsupported owner action", status_code=409
            )
        return await self._owner_facts(locator, request, transaction, locked=True)

    async def validate_operation(
        self,
        locator: ResourceLocator,
        action: str,
        request: RequestContext,
        transaction: HandlerTransaction,
    ) -> ResourceOwnerFacts:
        if action not in self.supported_actions:
            raise BusinessOSError(
                "proof_action_unsupported", "Unsupported owner action", status_code=409
            )
        return await self._owner_facts(locator, request, transaction, locked=True)

    async def apply_operation(
        self,
        locator: ResourceLocator,
        action: str,
        request: RequestContext,
        transaction: HandlerTransaction,
    ) -> None:
        self._assert_locator(locator, request)
        if action not in self.supported_actions:
            raise BusinessOSError(
                "proof_action_unsupported", "Unsupported owner action", status_code=409
            )
        values: dict[str, object] = {
            "lifecycle": {"archive": "archived", "anonymize": "anonymized", "purge": "purged"}[
                action
            ]
        }
        if action in {"anonymize", "purge"}:
            values.update(value="", description=None)
        result = await transaction.persistence.execute(
            update(PROOF_RECORDS)
            .where(
                PROOF_RECORDS.c.id == locator.record_id,
                PROOF_RECORDS.c.tenant_id == locator.tenant_id,
                PROOF_RECORDS.c.lifecycle == "current",
            )
            .values(**values)
            .returning(PROOF_RECORDS.c.id)
        )
        if result.scalar_one_or_none() is None:
            raise BusinessOSError(
                "proof_record_removed", "Proof record is no longer current", status_code=409
            )

    async def _owner_facts(
        self,
        locator: ResourceLocator,
        request: RequestContext,
        transaction: HandlerTransaction,
        *,
        locked: bool,
    ) -> ResourceOwnerFacts:
        self._assert_locator(locator, request)
        statement = select(PROOF_RECORDS).where(
            PROOF_RECORDS.c.id == locator.record_id,
            PROOF_RECORDS.c.tenant_id == locator.tenant_id,
        )
        if locked:
            statement = statement.with_for_update()
        row = (await transaction.persistence.execute(statement)).first()
        if row is None:
            raise BusinessOSError("proof_record_missing", "Proof record not found", status_code=404)
        return ResourceOwnerFacts(
            tenant_id=locator.tenant_id,
            namespace=self.resource_namespace,
            record_id=locator.record_id,
            owner_module_id="example.phase1-proof",
            contract_version=self.resource_version,
            lifecycle=row.lifecycle,
            facts={
                "entity_type": "proof_record",
                "retention_category": row.retention_category,
                "retention_anchor_at": row.retention_anchor_at.astimezone(UTC),
                "supported_actions": self.supported_actions,
            },
        )

    def _assert_locator(self, locator: ResourceLocator, request: RequestContext) -> None:
        if (
            locator.namespace != self.resource_namespace
            or locator.contract_version != self.resource_version
            or request.tenant is None
            or locator.tenant_id != request.tenant.tenant_id
        ):
            raise BusinessOSError(
                "proof_owner_mismatch", "Proof resource identity mismatch", status_code=403
            )

    async def _store_route(
        self, request: Request, dependencies: RequestDependencyScope
    ) -> Response:
        command = StoreProof.model_validate(await request.json())
        proof_dependency = await dependencies.resolve(PROOF_DEPENDENCY)
        if proof_dependency.label != "phase1-public-sdk":
            raise RuntimeError("Proof dependency registration is invalid")
        dispatcher = await dependencies.resolve(MESSAGE_DISPATCHER)
        result = await dispatcher.command(command, request.context, dependencies)
        return Response.json(result, status_code=202)

    async def _read_route(self, request: Request, dependencies: RequestDependencyScope) -> Response:
        proof_dependency = await dependencies.resolve(PROOF_DEPENDENCY)
        if proof_dependency.label != "phase1-public-sdk":
            raise RuntimeError("Proof dependency registration is invalid")
        dispatcher = await dependencies.resolve(MESSAGE_DISPATCHER)
        result = await dispatcher.query(ReadProof(), request.context, dependencies)
        return Response.json(result)

    @staticmethod
    def _tenant(context: RequestContext) -> TenantContext:
        if context.tenant is None:
            raise BusinessOSError("unauthenticated", "Authentication required", status_code=401)
        return context.tenant
