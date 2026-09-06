"""Proof that an external package can use only the published BusinessOS SDK."""

import json
from importlib.resources import files
from typing import ClassVar

from businessos.context import RequestContext, TenantContext
from businessos.dependencies import MESSAGE_DISPATCHER, OBJECT_STORAGE
from businessos.di import RequestDependencyScope
from businessos.errors import BusinessOSError
from businessos.features import FeatureFlag
from businessos.http import Request, Response
from businessos.messages import Command, DomainEvent, HandlingContext, Query
from businessos.metadata import MetadataDeclaration
from businessos.modules import ModuleManifest, ModuleRegistration
from businessos.permissions import PermissionDeclaration


class StoreProof(Command):
    value: str


class ReadProof(Query):
    pass


class ProofStored(DomainEvent):
    event_type: ClassVar[str] = "example.phase1_proof.stored"
    value: str


class ProofModule:
    def __init__(self) -> None:
        package = files("businessos_proof")
        manifest_data = json.loads(package.joinpath("manifest.json").read_text(encoding="utf-8"))
        manifest_data["migrations"] = [str(package.joinpath("migrations", "versions"))]
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
        context.emit(
            ProofStored(
                tenant_id=tenant.tenant_id,
                correlation_id=context.request.correlation_id,
                value=command.value,
            )
        )
        return {"stored": True}

    async def _read(self, _: ReadProof, context: HandlingContext) -> object:
        tenant = self._tenant(context.request)
        storage = await context.dependencies.resolve(OBJECT_STORAGE)
        value = await storage.get(tenant.tenant_id, "phase1-proof/value.txt")
        return {"value": value.decode("utf-8")}

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
