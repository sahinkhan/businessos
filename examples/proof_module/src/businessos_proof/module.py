"""Proof that an external package can use only the published BusinessOS SDK."""

import json
from importlib.resources import files
from typing import ClassVar
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import Column, DateTime, MetaData, Table, Text, func, select
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.dialects.postgresql import insert

from businessos.sdk import (
    MESSAGE_DISPATCHER,
    OBJECT_STORAGE,
    BusinessOSError,
    Command,
    DomainEvent,
    FeatureFlag,
    HandlingContext,
    MetadataDeclaration,
    ModuleManifest,
    ModuleRegistration,
    PermissionDeclaration,
    Query,
    Request,
    RequestContext,
    RequestDependencyScope,
    Response,
    TenantContext,
)

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
    def __init__(self) -> None:
        package = files("businessos_proof")
        manifest_data = json.loads(package.joinpath("manifest.json").read_text(encoding="utf-8"))
        self.manifest = ModuleManifest.model_validate(manifest_data)
        self.started = False
        self.events_consumed = 0

    async def register(self, registration: ModuleRegistration) -> None:
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
        registration.command(StoreProof, self._store)
        registration.query(ReadProof, self._read)
        registration.event(ProofStored, "object-storage-projection", self._project)
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
        _: RequestContext,
        dependencies: RequestDependencyScope,
    ) -> None:
        storage = await dependencies.resolve(OBJECT_STORAGE)
        await storage.put(
            event.tenant_id,
            "phase1-proof/value.txt",
            event.value.encode("utf-8"),
        )
        self.events_consumed += 1

    async def _store_route(
        self, request: Request, dependencies: RequestDependencyScope
    ) -> Response:
        command = StoreProof.model_validate(await request.json())
        dispatcher = await dependencies.resolve(MESSAGE_DISPATCHER)
        result = await dispatcher.command(command, request.context, dependencies)
        return Response.json(result, status_code=202)

    async def _read_route(self, request: Request, dependencies: RequestDependencyScope) -> Response:
        dispatcher = await dependencies.resolve(MESSAGE_DISPATCHER)
        result = await dispatcher.query(ReadProof(), request.context, dependencies)
        return Response.json(result)

    @staticmethod
    def _tenant(context: RequestContext) -> TenantContext:
        if context.tenant is None:
            raise BusinessOSError("unauthenticated", "Authentication required", status_code=401)
        return context.tenant
