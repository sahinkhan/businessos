"""Identity and membership module registration and handlers."""

import json
import secrets
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from typing import ClassVar, Literal, cast
from uuid import UUID, uuid4

from businessos_tenant import DatabaseTenantAccessValidator, validate_effective_period
from pydantic import ConfigDict, Field
from sqlalchemy import insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from businessos.sdk import (
    INSTALLATION_ID,
    UNIT_OF_WORK_FACTORY,
    BusinessOSError,
    Command,
    DependencyResolver,
    DependencyScope,
    DomainEvent,
    HandlingContext,
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

from .authority import DatabaseMembershipAuthority
from .contracts import (
    MEMBERSHIP_AUTHORITY,
    WORKLOAD_EXECUTION_AUTHORITY,
    AuthenticationSessionRecord,
    AuthenticationStrength,
    IdentityContract,
    MembershipRecord,
    MembershipStatus,
)
from .models import (
    AUTHENTICATION_SESSIONS,
    DEVICES,
    EXTERNAL_IDENTITIES,
    MEMBERSHIPS,
    MFA_POLICIES,
    OIDC_PROVIDERS,
    SERVICE_ACCOUNTS,
    USERS,
)
from .oidc import OIDCContextResolver
from .principal_binding import AUTHENTICATED_PRINCIPAL, current_authenticated_principal
from .web_browser import BrowserOIDCSettings, BrowserSessionRuntime
from .web_sessions import (
    AUTH_TRANSACTION_COOKIE,
    SESSION_COOKIE,
    WEB_SESSION_SERVICE,
    WebSessionApplicationService,
    WebSessionContract,
    cookie_value,
    expire_cookie,
    session_cookie,
    transaction_cookie,
)
from .workload_authority import DatabaseWorkloadExecutionAuthority


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
    principal_type: Literal["user", "service_account"] = "user"
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
    active: bool = True


class SetMFAPolicy(Command):
    tenant_id: UUID
    minimum_strength: AuthenticationStrength
    required_methods: tuple[str, ...] = ()
    configuration: dict[str, object] = Field(default_factory=dict)


class GetMembership(Query):
    tenant_id: UUID
    principal_id: UUID
    principal_type: Literal["user", "service_account", "device"] = "user"


class StartAuthenticationSession(Command):
    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    expires_at: datetime


class RevokeAuthenticationSession(Command):
    tenant_id: UUID
    session_id: UUID


class GetAuthenticationSession(Query):
    tenant_id: UUID
    session_id: UUID


class ValidateAuthenticationSession(Query):
    tenant_id: UUID
    session_id: UUID


class MembershipGranted(DomainEvent):
    event_type: ClassVar[str] = "identity.membership.granted.v1"
    membership_id: UUID
    principal_id: UUID
    principal_type: str


class MembershipRevoked(DomainEvent):
    event_type: ClassVar[str] = "identity.membership.revoked.v1"
    principal_id: UUID
    principal_type: str


class AuthenticationSessionStarted(DomainEvent):
    event_type: ClassVar[str] = "identity.authentication_session.started.v1"
    session_id: UUID
    principal_id: UUID
    principal_type: str


class AuthenticationSessionRevoked(DomainEvent):
    event_type: ClassVar[str] = "identity.authentication_session.revoked.v1"
    session_id: UUID


class IdentityModule:
    def __init__(self, *, max_session_lifetime: timedelta = timedelta(hours=8)) -> None:
        if max_session_lifetime <= timedelta(0):
            raise ValueError("Maximum authentication session lifetime must be positive")
        self.max_session_lifetime = max_session_lifetime
        data = json.loads(
            files("businessos_identity").joinpath("manifest.json").read_text(encoding="utf-8")
        )
        self.manifest = ModuleManifest.model_validate(data)
        self._browser_runtime: BrowserSessionRuntime | None = None

    async def register(self, registration: ModuleRegistration) -> None:
        registration.dependency(MEMBERSHIP_AUTHORITY, lambda _: DatabaseMembershipAuthority())
        registration.dependency(
            WORKLOAD_EXECUTION_AUTHORITY,
            lambda _: DatabaseWorkloadExecutionAuthority(),
            scope=DependencyScope.SINGLETON,
        )
        registration.dependency(
            AUTHENTICATED_PRINCIPAL, lambda _: current_authenticated_principal()
        )
        for key, description in (
            ("foundation.identity.read", "Read tenant identity and membership"),
            ("foundation.identity.manage", "Manage tenant principals and federation"),
            ("foundation.identity.membership.manage", "Grant and revoke tenant membership"),
        ):
            registration.permission(PermissionDeclaration(key=key, description=description))
        registration.contract("foundation.identity.v1", IdentityContract())
        registration.contract("foundation.identity.web-session.v1", WebSessionContract())
        registration.dependency(
            WEB_SESSION_SERVICE,
            self._provide_web_session_service,
            scope=DependencyScope.SINGLETON,
        )
        registration.route("GET", "/api/v1/auth/session", self._http_session, name="web-session")
        registration.route(
            "POST", "/api/v1/auth/login/start", self._http_login_start, name="web-login-start"
        )
        registration.route("GET", "/api/v1/auth/callback", self._http_callback, name="web-callback")
        registration.route("POST", "/api/v1/auth/logout", self._http_logout, name="web-logout")
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
        registration.command(
            StartAuthenticationSession,
            self._start_session,
            permission="foundation.identity.read",
        )
        registration.command(
            RevokeAuthenticationSession,
            self._revoke_session,
            permission="foundation.identity.manage",
        )
        registration.query(
            GetMembership, self._get_membership, permission="foundation.identity.read"
        )
        registration.query(
            GetAuthenticationSession,
            self._get_session,
            permission="foundation.identity.read",
        )
        registration.query(
            ValidateAuthenticationSession,
            self._validate_session,
            permission="foundation.identity.read",
        )

    async def _provide_web_session_service(
        self, dependencies: DependencyResolver
    ) -> WebSessionApplicationService:
        settings = BrowserOIDCSettings.from_environment()
        if settings is None:
            raise BusinessOSError(
                "authentication_unavailable",
                "Browser authentication is not configured",
                status_code=503,
            )
        installation_id = await dependencies.resolve(INSTALLATION_ID)
        unit_of_work_factory = await dependencies.resolve(UNIT_OF_WORK_FACTORY)
        oidc = OIDCContextResolver(
            installation_id=installation_id,
            unit_of_work_factory=unit_of_work_factory,
            tenant_access=DatabaseTenantAccessValidator(installation_id, unit_of_work_factory),
        )
        runtime = BrowserSessionRuntime(settings, installation_id, unit_of_work_factory, oidc)
        self._browser_runtime = runtime
        return runtime.service

    @staticmethod
    async def _service(dependencies: RequestDependencyScope) -> WebSessionApplicationService:
        return await dependencies.resolve(WEB_SESSION_SERVICE)

    async def _http_session(
        self, request: Request, dependencies: RequestDependencyScope
    ) -> Response:
        service = await self._service(dependencies)
        handle = cookie_value(request.headers, SESSION_COOKIE)
        session = await service.get_session(handle) if handle else None
        if session is None or handle is None:
            response = Response.json(
                {"code": "unauthenticated", "message": "Authentication required"}, status_code=401
            )
            response.append_header("set-cookie", expire_cookie(SESSION_COOKIE))
            return response
        return Response.json(service.project(session, handle))

    async def _http_login_start(
        self, request: Request, dependencies: RequestDependencyScope
    ) -> Response:
        fetch_site = request.headers.get("sec-fetch-site")
        origin = request.headers.get("origin")
        host = request.headers.get("host")
        if fetch_site not in {None, "same-origin", "none"} or (
            origin is not None and (host is None or origin != f"{request.scheme}://{host}")
        ):
            raise BusinessOSError("invalid_origin", "Login request is not valid", status_code=403)
        payload = await request.json()
        if not isinstance(payload, dict):
            raise BusinessOSError("invalid_request", "Request must be an object", status_code=400)
        payload = cast(dict[str, object], payload)
        provider = payload.get("provider", "default")
        return_to = payload.get("return_to")
        if not isinstance(provider, str) or not isinstance(return_to, str | None):
            raise BusinessOSError("invalid_request", "Request is not valid", status_code=400)
        service = await self._service(dependencies)
        started = await service.start_login(
            provider, return_to, rate_limit_key=f"login:{request.client_host}"
        )
        response = Response.json(
            {"authorization_url": started.authorization_url, "expires_at": started.expires_at}
        )
        response.append_header(
            "set-cookie", transaction_cookie(started.browser_binding, started.expires_at)
        )
        return response

    async def _http_callback(
        self, request: Request, dependencies: RequestDependencyScope
    ) -> Response:
        service = await self._service(dependencies)
        state = request.query_params.get("state", ("",))[0]
        code = request.query_params.get("code", ("",))[0]
        binding = cookie_value(request.headers, AUTH_TRANSACTION_COOKIE) or ""
        if not state or not code or not binding:
            response = Response.json(
                {"code": "invalid_authentication_callback", "message": "Authentication failed"},
                status_code=401,
            )
            response.append_header("set-cookie", expire_cookie(AUTH_TRANSACTION_COOKIE))
            return response
        try:
            handle, session, return_to = await service.complete_oidc_login(
                state=state, code=code, browser_binding=binding
            )
        except BusinessOSError as error:
            response = Response.json(error.payload(), status_code=error.status_code)
            response.append_header("set-cookie", expire_cookie(AUTH_TRANSACTION_COOKIE))
            return response
        previous = cookie_value(request.headers, SESSION_COOKIE)
        if previous:
            await service.logout(previous)
        response = Response(status_code=303, headers={"location": return_to})
        response.append_header("set-cookie", expire_cookie(AUTH_TRANSACTION_COOKIE))
        response.append_header("set-cookie", session_cookie(handle, session.absolute_expires_at))
        return response

    async def _http_logout(
        self, request: Request, dependencies: RequestDependencyScope
    ) -> Response:
        service = await self._service(dependencies)
        handle = cookie_value(request.headers, SESSION_COOKIE)
        if handle:
            session = await service.get_session(handle, touch=False)
            if session is not None and not secrets.compare_digest(
                request.headers.get("x-csrf-token", ""), session.csrf_token
            ):
                raise BusinessOSError("invalid_csrf", "CSRF validation failed", status_code=403)
            await service.logout(handle)
        response = Response(status_code=204)
        response.append_header("set-cookie", expire_cookie(SESSION_COOKIE))
        return response

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        if self._browser_runtime is not None:
            await self._browser_runtime.close()
            self._browser_runtime = None
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
            select(USERS.c.id, USERS.c.is_break_glass).where(
                USERS.c.tenant_id == tenant.tenant_id, USERS.c.id == command.user_id
            )
        )
        user = exists.one_or_none()
        if user is None:
            raise BusinessOSError("not_found", "User not found", status_code=404)
        if user.is_break_glass:
            raise BusinessOSError(
                "invalid_break_glass",
                "Break-glass identities cannot use federation",
                status_code=422,
            )
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
        validate_effective_period(command.valid_from, command.valid_until)
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
        principal_table = {
            "user": USERS,
            "service_account": SERVICE_ACCOUNTS,
        }[command.principal_type]
        principal = await context.unit_of_work.persistence.execute(
            select(principal_table.c.id).where(
                principal_table.c.tenant_id == tenant.tenant_id,
                principal_table.c.id == command.principal_id,
                principal_table.c.active.is_(True),
            )
        )
        if principal.scalar_one_or_none() is None:
            raise BusinessOSError("not_found", "Active device principal not found", status_code=404)
        await context.unit_of_work.persistence.execute(
            insert(DEVICES).values(
                id=command.device_id,
                tenant_id=tenant.tenant_id,
                principal_id=command.principal_id,
                principal_type=command.principal_type,
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
                active=command.active,
            )
            .on_conflict_do_update(
                constraint="oidc_provider_identity",
                set_={
                    "jwks_uri": command.jwks_uri,
                    "algorithms": list(command.algorithms),
                    "active": command.active,
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

    async def _start_session(
        self, command: StartAuthenticationSession, context: HandlingContext
    ) -> object:
        tenant = _require_tenant(context.request, command.tenant_id)
        now = datetime.now(UTC)
        if (
            command.expires_at.tzinfo is None
            or command.expires_at.utcoffset() is None
            or command.expires_at <= now
            or command.expires_at > now + self.max_session_lifetime
            or (
                tenant.credential_expires_at is not None
                and (
                    tenant.credential_expires_at.tzinfo is None
                    or tenant.credential_expires_at.utcoffset() is None
                    or command.expires_at > tenant.credential_expires_at
                )
            )
        ):
            raise BusinessOSError(
                "invalid_session_expiry",
                "Session expiry exceeds the permitted credential or session lifetime",
                status_code=422,
            )
        membership = await context.unit_of_work.persistence.execute(
            select(MEMBERSHIPS.c.id, MEMBERSHIPS.c.principal_type).where(
                MEMBERSHIPS.c.tenant_id == tenant.tenant_id,
                MEMBERSHIPS.c.principal_id == tenant.principal_id,
                MEMBERSHIPS.c.status == MembershipStatus.ACTIVE,
                (MEMBERSHIPS.c.valid_from.is_(None) | (MEMBERSHIPS.c.valid_from <= now)),
                (MEMBERSHIPS.c.valid_until.is_(None) | (MEMBERSHIPS.c.valid_until > now)),
            )
        )
        memberships = tuple(membership)
        if len(memberships) != 1:
            raise BusinessOSError(
                "invalid_membership", "Active tenant membership is required", status_code=403
            )
        principal_type = memberships[0].principal_type
        principal_table = {
            "user": USERS,
            "service_account": SERVICE_ACCOUNTS,
            "device": DEVICES,
        }.get(principal_type)
        if principal_table is None:
            raise BusinessOSError(
                "invalid_principal", "Active principal is required", status_code=403
            )
        principal = await context.unit_of_work.persistence.execute(
            select(principal_table.c.id).where(
                principal_table.c.tenant_id == tenant.tenant_id,
                principal_table.c.id == tenant.principal_id,
                principal_table.c.active.is_(True),
            )
        )
        if principal.scalar_one_or_none() is None:
            raise BusinessOSError(
                "invalid_principal", "Active principal is required", status_code=403
            )
        await context.unit_of_work.persistence.execute(
            insert(AUTHENTICATION_SESSIONS).values(
                id=command.session_id,
                tenant_id=tenant.tenant_id,
                principal_id=tenant.principal_id,
                principal_type=principal_type,
                authentication_strength=tenant.authentication_strength,
                expires_at=command.expires_at,
            )
        )
        context.emit(
            AuthenticationSessionStarted(
                tenant_id=tenant.tenant_id,
                correlation_id=context.request.correlation_id,
                session_id=command.session_id,
                principal_id=tenant.principal_id,
                principal_type=principal_type,
            )
        )
        return {"session_id": command.session_id}

    async def _revoke_session(
        self, command: RevokeAuthenticationSession, context: HandlingContext
    ) -> object:
        tenant = _require_tenant(context.request, command.tenant_id)
        revoked_at = datetime.now(UTC)
        result = await context.unit_of_work.persistence.execute(
            update(AUTHENTICATION_SESSIONS)
            .where(
                AUTHENTICATION_SESSIONS.c.tenant_id == tenant.tenant_id,
                AUTHENTICATION_SESSIONS.c.id == command.session_id,
            )
            .values(revoked_at=revoked_at)
            .returning(AUTHENTICATION_SESSIONS.c.id)
        )
        if result.scalar_one_or_none() is None:
            raise BusinessOSError("not_found", "Authentication session not found", status_code=404)
        context.emit(
            AuthenticationSessionRevoked(
                tenant_id=tenant.tenant_id,
                correlation_id=context.request.correlation_id,
                session_id=command.session_id,
            )
        )
        return {"session_id": command.session_id, "revoked_at": revoked_at}

    async def _get_session(
        self, query: GetAuthenticationSession, context: HandlingContext
    ) -> object:
        _require_tenant(context.request, query.tenant_id)
        result = await context.unit_of_work.persistence.execute(
            select(AUTHENTICATION_SESSIONS).where(
                AUTHENTICATION_SESSIONS.c.tenant_id == query.tenant_id,
                AUTHENTICATION_SESSIONS.c.id == query.session_id,
            )
        )
        row = result.mappings().one_or_none()
        if row is None:
            raise BusinessOSError("not_found", "Authentication session not found", status_code=404)
        return AuthenticationSessionRecord(
            session_id=row["id"],
            tenant_id=row["tenant_id"],
            principal_id=row["principal_id"],
            principal_type=row["principal_type"],
            authentication_strength=row["authentication_strength"],
            started_at=row["started_at"],
            expires_at=row["expires_at"],
            revoked_at=row["revoked_at"],
        )

    async def _validate_session(
        self, query: ValidateAuthenticationSession, context: HandlingContext
    ) -> object:
        record = await self._get_session(
            GetAuthenticationSession(tenant_id=query.tenant_id, session_id=query.session_id),
            context,
        )
        if not isinstance(record, AuthenticationSessionRecord) or not record.is_active():
            raise BusinessOSError(
                "invalid_session", "Authentication session is not active", status_code=401
            )
        membership = await context.unit_of_work.persistence.execute(
            select(MEMBERSHIPS.c.id).where(
                MEMBERSHIPS.c.tenant_id == record.tenant_id,
                MEMBERSHIPS.c.principal_id == record.principal_id,
                MEMBERSHIPS.c.principal_type == record.principal_type,
                MEMBERSHIPS.c.status == MembershipStatus.ACTIVE,
                (
                    MEMBERSHIPS.c.valid_from.is_(None)
                    | (MEMBERSHIPS.c.valid_from <= datetime.now(UTC))
                ),
                (
                    MEMBERSHIPS.c.valid_until.is_(None)
                    | (MEMBERSHIPS.c.valid_until > datetime.now(UTC))
                ),
            )
        )
        if membership.scalar_one_or_none() is None:
            raise BusinessOSError(
                "invalid_session", "Authentication session is not active", status_code=401
            )
        principal_table = {
            "user": USERS,
            "service_account": SERVICE_ACCOUNTS,
            "device": DEVICES,
        }.get(record.principal_type)
        if principal_table is None:
            raise BusinessOSError(
                "invalid_session", "Authentication session is not active", status_code=401
            )
        principal = await context.unit_of_work.persistence.execute(
            select(principal_table.c.id).where(
                principal_table.c.tenant_id == record.tenant_id,
                principal_table.c.id == record.principal_id,
                principal_table.c.active.is_(True),
            )
        )
        if principal.scalar_one_or_none() is None:
            raise BusinessOSError(
                "invalid_session", "Authentication session is not active", status_code=401
            )
        return record


def _require_tenant(context: RequestContext, expected: UUID) -> TenantContext:
    tenant = context.tenant
    if tenant is None:
        raise BusinessOSError("unauthenticated", "Authentication required", status_code=401)
    if tenant.tenant_id != expected:
        raise BusinessOSError("forbidden", "Tenant scope mismatch", status_code=403)
    return tenant
