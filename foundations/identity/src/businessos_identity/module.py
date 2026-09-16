"""Identity and membership module registration and handlers."""

import json
from datetime import datetime
from importlib.resources import files
from typing import ClassVar, Literal
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from businessos.sdk import (
    BusinessOSError,
    Command,
    DomainEvent,
    HandlingContext,
    ModuleManifest,
    ModuleRegistration,
    PermissionDeclaration,
    Query,
    RequestContext,
    TenantContext,
)

from .contracts import IdentityContract, MembershipRecord, MembershipStatus
from .models import (
    DEVICES,
    EXTERNAL_IDENTITIES,
    MEMBERSHIPS,
    MFA_POLICIES,
    OIDC_PROVIDERS,
    SERVICE_ACCOUNTS,
    USERS,
)


class CreateUser(Command):
    user_id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=320)
    display_name: str = Field(min_length=1, max_length=200)
    break_glass: bool = False
    credential_secret_reference: str | None = Field(default=None, max_length=1000)


class MapExternalIdentity(Command):
    tenant_id: UUID
    user_id: UUID
    issuer: str = Field(min_length=1, max_length=500)
    subject: str = Field(min_length=1, max_length=500)


class GrantMembership(Command):
    membership_id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    principal_id: UUID
    principal_type: Literal["user", "service_account", "device"]
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    scopes: tuple[dict[str, str], ...] = ()


class RevokeMembership(Command):
    tenant_id: UUID
    principal_id: UUID
    principal_type: Literal["user", "service_account", "device"]


class RegisterServiceAccount(Command):
    service_account_id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    name: str = Field(min_length=1, max_length=200)
    credential_secret_reference: str = Field(min_length=1, max_length=1000)


class RegisterDevice(Command):
    device_id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    principal_id: UUID
    name: str = Field(min_length=1, max_length=200)
    device_type: str = Field(min_length=1, max_length=100)
    credential_secret_reference: str = Field(min_length=1, max_length=1000)


class ConfigureOIDCProvider(Command):
    tenant_id: UUID
    issuer: str = Field(pattern=r"^https://", max_length=500)
    audience: str = Field(min_length=1, max_length=500)
    jwks_uri: str = Field(pattern=r"^https://", max_length=1000)
    algorithms: tuple[
        Literal["RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "EdDSA"], ...
    ] = ("RS256",)


class SetMFAPolicy(Command):
    tenant_id: UUID
    minimum_strength: str = Field(min_length=1, max_length=100)
    required_methods: tuple[str, ...] = ()
    configuration: dict[str, object] = Field(default_factory=dict)


class GetMembership(Query):
    tenant_id: UUID
    principal_id: UUID
    principal_type: Literal["user", "service_account", "device"] = "user"


class MembershipGranted(DomainEvent):
    event_type: ClassVar[str] = "identity.membership.granted.v1"
    membership_id: UUID
    principal_id: UUID
    principal_type: str


class MembershipRevoked(DomainEvent):
    event_type: ClassVar[str] = "identity.membership.revoked.v1"
    principal_id: UUID
    principal_type: str


class IdentityModule:
    def __init__(self) -> None:
        data = json.loads(
            files("businessos_identity").joinpath("manifest.json").read_text(encoding="utf-8")
        )
        self.manifest = ModuleManifest.model_validate(data)

    async def register(self, registration: ModuleRegistration) -> None:
        for key, description in (
            ("foundation.identity.read", "Read tenant identity and membership"),
            ("foundation.identity.manage", "Manage tenant principals and federation"),
            ("foundation.identity.membership.manage", "Grant and revoke tenant membership"),
        ):
            registration.permission(PermissionDeclaration(key=key, description=description))
        registration.contract("foundation.identity.v1", IdentityContract())
        registration.command(CreateUser, self._create_user, permission="foundation.identity.manage")
        registration.command(
            MapExternalIdentity, self._map_external, permission="foundation.identity.manage"
        )
        registration.command(
            GrantMembership,
            self._grant_membership,
            permission="foundation.identity.membership.manage",
        )
        registration.command(
            RevokeMembership,
            self._revoke_membership,
            permission="foundation.identity.membership.manage",
        )
        registration.command(
            RegisterServiceAccount,
            self._service_account,
            permission="foundation.identity.manage",
        )
        registration.command(RegisterDevice, self._device, permission="foundation.identity.manage")
        registration.command(
            ConfigureOIDCProvider, self._oidc_provider, permission="foundation.identity.manage"
        )
        registration.command(
            SetMFAPolicy, self._mfa_policy, permission="foundation.identity.manage"
        )
        registration.query(
            GetMembership, self._get_membership, permission="foundation.identity.read"
        )

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def _create_user(self, command: CreateUser, context: HandlingContext) -> object:
        tenant = _require_tenant(context.request, command.tenant_id)
        if command.break_glass and not command.credential_secret_reference:
            raise BusinessOSError(
                "invalid_break_glass",
                "Break-glass identity requires a secret reference",
                status_code=422,
            )
        await context.unit_of_work.persistence.execute(
            insert(USERS).values(
                id=command.user_id,
                tenant_id=tenant.tenant_id,
                email=str(command.email).casefold(),
                display_name=command.display_name,
                is_break_glass=command.break_glass,
                credential_secret_reference=command.credential_secret_reference,
            )
        )
        return {"user_id": command.user_id}

    async def _map_external(self, command: MapExternalIdentity, context: HandlingContext) -> object:
        tenant = _require_tenant(context.request, command.tenant_id)
        exists = await context.unit_of_work.persistence.execute(
            select(USERS.c.id).where(
                USERS.c.tenant_id == tenant.tenant_id, USERS.c.id == command.user_id
            )
        )
        if exists.scalar_one_or_none() is None:
            raise BusinessOSError("not_found", "User not found", status_code=404)
        await context.unit_of_work.persistence.execute(
            insert(EXTERNAL_IDENTITIES).values(
                id=uuid4(),
                tenant_id=tenant.tenant_id,
                user_id=command.user_id,
                issuer=command.issuer,
                subject=command.subject,
            )
        )
        return {"user_id": command.user_id, "issuer": command.issuer}

    async def _grant_membership(self, command: GrantMembership, context: HandlingContext) -> object:
        tenant = _require_tenant(context.request, command.tenant_id)
        if command.valid_from and command.valid_until and command.valid_until < command.valid_from:
            raise BusinessOSError(
                "invalid_effective_dates", "Membership dates are invalid", status_code=422
            )
        principal_table = {
            "user": USERS,
            "service_account": SERVICE_ACCOUNTS,
            "device": DEVICES,
        }[command.principal_type]
        principal = await context.unit_of_work.persistence.execute(
            select(principal_table.c.id).where(
                principal_table.c.tenant_id == tenant.tenant_id,
                principal_table.c.id == command.principal_id,
                principal_table.c.active.is_(True),
            )
        )
        if principal.scalar_one_or_none() is None:
            raise BusinessOSError("not_found", "Active principal not found", status_code=404)
        statement = (
            pg_insert(MEMBERSHIPS)
            .values(
                id=command.membership_id,
                tenant_id=tenant.tenant_id,
                principal_id=command.principal_id,
                principal_type=command.principal_type,
                status=MembershipStatus.ACTIVE,
                valid_from=command.valid_from,
                valid_until=command.valid_until,
                scopes=list(command.scopes),
                granted_by=tenant.principal_id,
            )
            .on_conflict_do_update(
                constraint="membership_principal",
                set_={
                    "status": MembershipStatus.ACTIVE,
                    "valid_from": command.valid_from,
                    "valid_until": command.valid_until,
                    "scopes": list(command.scopes),
                    "granted_by": tenant.principal_id,
                },
            )
            .returning(MEMBERSHIPS.c.id)
        )
        membership_id = (await context.unit_of_work.persistence.execute(statement)).scalar_one()
        context.emit(
            MembershipGranted(
                tenant_id=tenant.tenant_id,
                correlation_id=context.request.correlation_id,
                membership_id=membership_id,
                principal_id=command.principal_id,
                principal_type=command.principal_type,
            )
        )
        return {"membership_id": membership_id, "status": MembershipStatus.ACTIVE}

    async def _revoke_membership(
        self, command: RevokeMembership, context: HandlingContext
    ) -> object:
        tenant = _require_tenant(context.request, command.tenant_id)
        result = await context.unit_of_work.persistence.execute(
            update(MEMBERSHIPS)
            .where(
                MEMBERSHIPS.c.tenant_id == tenant.tenant_id,
                MEMBERSHIPS.c.principal_id == command.principal_id,
                MEMBERSHIPS.c.principal_type == command.principal_type,
            )
            .values(status=MembershipStatus.REVOKED)
            .returning(MEMBERSHIPS.c.id)
        )
        if result.scalar_one_or_none() is None:
            raise BusinessOSError("not_found", "Membership not found", status_code=404)
        context.emit(
            MembershipRevoked(
                tenant_id=tenant.tenant_id,
                correlation_id=context.request.correlation_id,
                principal_id=command.principal_id,
                principal_type=command.principal_type,
            )
        )
        return {"status": MembershipStatus.REVOKED}

    async def _service_account(
        self, command: RegisterServiceAccount, context: HandlingContext
    ) -> object:
        tenant = _require_tenant(context.request, command.tenant_id)
        await context.unit_of_work.persistence.execute(
            insert(SERVICE_ACCOUNTS).values(
                id=command.service_account_id,
                tenant_id=tenant.tenant_id,
                name=command.name,
                credential_secret_reference=command.credential_secret_reference,
            )
        )
        return {"service_account_id": command.service_account_id}

    async def _device(self, command: RegisterDevice, context: HandlingContext) -> object:
        tenant = _require_tenant(context.request, command.tenant_id)
        await context.unit_of_work.persistence.execute(
            insert(DEVICES).values(
                id=command.device_id,
                tenant_id=tenant.tenant_id,
                principal_id=command.principal_id,
                name=command.name,
                device_type=command.device_type,
                credential_secret_reference=command.credential_secret_reference,
            )
        )
        return {"device_id": command.device_id}

    async def _oidc_provider(
        self, command: ConfigureOIDCProvider, context: HandlingContext
    ) -> object:
        tenant = _require_tenant(context.request, command.tenant_id)
        statement = (
            pg_insert(OIDC_PROVIDERS)
            .values(
                id=uuid4(),
                tenant_id=tenant.tenant_id,
                issuer=command.issuer,
                audience=command.audience,
                jwks_uri=command.jwks_uri,
                algorithms=list(command.algorithms),
            )
            .on_conflict_do_update(
                constraint="oidc_provider_identity",
                set_={
                    "jwks_uri": command.jwks_uri,
                    "algorithms": list(command.algorithms),
                    "active": True,
                },
            )
        )
        await context.unit_of_work.persistence.execute(statement)
        return {"issuer": command.issuer, "audience": command.audience}

    async def _mfa_policy(self, command: SetMFAPolicy, context: HandlingContext) -> object:
        tenant = _require_tenant(context.request, command.tenant_id)
        statement = (
            pg_insert(MFA_POLICIES)
            .values(
                id=uuid4(),
                tenant_id=tenant.tenant_id,
                minimum_strength=command.minimum_strength,
                required_methods=list(command.required_methods),
                configuration=command.configuration,
            )
            .on_conflict_do_update(
                constraint="mfa_policy_tenant",
                set_={
                    "minimum_strength": command.minimum_strength,
                    "required_methods": list(command.required_methods),
                    "configuration": command.configuration,
                },
            )
        )
        await context.unit_of_work.persistence.execute(statement)
        return {"minimum_strength": command.minimum_strength}

    async def _get_membership(self, query: GetMembership, context: HandlingContext) -> object:
        _require_tenant(context.request, query.tenant_id)
        result = await context.unit_of_work.persistence.execute(
            select(MEMBERSHIPS).where(
                MEMBERSHIPS.c.tenant_id == query.tenant_id,
                MEMBERSHIPS.c.principal_id == query.principal_id,
                MEMBERSHIPS.c.principal_type == query.principal_type,
            )
        )
        row = result.mappings().one_or_none()
        if row is None:
            raise BusinessOSError("not_found", "Membership not found", status_code=404)
        return MembershipRecord(
            membership_id=row["id"],
            tenant_id=row["tenant_id"],
            principal_id=row["principal_id"],
            principal_type=row["principal_type"],
            status=row["status"],
            valid_from=row["valid_from"],
            valid_until=row["valid_until"],
            scopes=tuple(row["scopes"]),
        )


def _require_tenant(context: RequestContext, expected: UUID) -> TenantContext:
    tenant = context.tenant
    if tenant is None:
        raise BusinessOSError("unauthenticated", "Authentication required", status_code=401)
    if tenant.tenant_id != expected:
        raise BusinessOSError("forbidden", "Tenant scope mismatch", status_code=403)
    return tenant
