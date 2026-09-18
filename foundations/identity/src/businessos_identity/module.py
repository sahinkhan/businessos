"""Identity and membership module registration and handlers."""

import json
import secrets
from collections.abc import Awaitable, Callable
from datetime import datetime
from importlib.resources import files
from typing import ClassVar, Literal, cast
from uuid import UUID, uuid4

from businessos_tenant import DatabaseTenantAccessValidator
from pydantic import Field
from sqlalchemy import insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from businessos.sdk import (
    PROVIDER_REGISTRY,
    TRUSTED_CONTEXT_RESOLVER,
    UNIT_OF_WORK_FACTORY,
    BusinessOSError,
    Command,
    DependencyScope,
    DomainEvent,
    HandlingContext,
    ModuleManifest,
    ModuleRegistration,
    PermissionDeclaration,
    ProviderRegistry,
    Query,
    Request,
    RequestContext,
    RequestDependencyScope,
    RequestIdentity,
    Response,
    TenantContext,
    UnitOfWorkFactory,
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
from .web_sessions import (
    AUTH_TRANSACTION_COOKIE,
    AUTH_TRANSACTION_PROVIDER,
    OIDC_BROWSER_PROVIDER,
    PRINCIPAL_SESSION_VALIDATOR,
    SESSION_COOKIE,
    SESSION_PROVIDER,
    WEB_SESSION_CONFIGURATION,
    WEB_SESSION_SERVICE,
    AuthorizationTransactionStore,
    DatabasePrincipalSessionValidator,
    OIDCBrowserProvider,
    PrincipalSessionValidator,
    WebSessionApplicationService,
    WebSessionConfiguration,
    WebSessionContract,
    WebSessionStore,
    cookie_value,
    expire_cookie,
    session_cookie,
    transaction_cookie,
)


class WebSessionContextResolver:
    def __init__(self, service: WebSessionApplicationService) -> None:
        self._service = service

    async def resolve(self, identity: RequestIdentity) -> RequestContext:
        handle = cookie_value(dict(identity.headers), SESSION_COOKIE)
        if handle is None:
            return RequestContext(
                correlation_id=identity.correlation_id,
                trace_id=identity.trace_id,
            )
        session = await self._service.get_session(handle)
        if session is None:
            return RequestContext(
                correlation_id=identity.correlation_id,
                trace_id=identity.trace_id,
            )
        return self._service.request_context(session, identity)


def _web_session_service(
    registry: ProviderRegistry, unit_of_work_factory: UnitOfWorkFactory
) -> WebSessionApplicationService:
    try:
        configuration = cast(WebSessionConfiguration, registry.get(WEB_SESSION_CONFIGURATION))
        sessions = cast(WebSessionStore, registry.get(SESSION_PROVIDER))
        transactions = cast(AuthorizationTransactionStore, registry.get(AUTH_TRANSACTION_PROVIDER))
        oidc = cast(OIDCBrowserProvider, registry.get(OIDC_BROWSER_PROVIDER))
    except Exception:
        raise BusinessOSError(
            "authentication_unavailable",
            "Authentication service is unavailable",
            status_code=503,
        ) from None
    return WebSessionApplicationService(
        configuration=configuration,
        sessions=sessions,
        transactions=transactions,
        oidc=oidc,
        principal_validator=(
            cast(PrincipalSessionValidator, registry.get(PRINCIPAL_SESSION_VALIDATOR))
            if registry.contains(PRINCIPAL_SESSION_VALIDATOR)
            else DatabasePrincipalSessionValidator(
                installation_id=configuration.installation_id,
                unit_of_work_factory=unit_of_work_factory,
                tenant_access=DatabaseTenantAccessValidator(
                    configuration.installation_id, unit_of_work_factory
                ),
            )
        ),
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
        self._web_sessions: WebSessionApplicationService | None = None

    async def register(self, registration: ModuleRegistration) -> None:
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
        registration.dependency(
            TRUSTED_CONTEXT_RESOLVER,
            self._provide_context_resolver,
            scope=DependencyScope.SINGLETON,
        )
        registration.middleware("web-session-csrf", self._csrf_middleware)
        registration.route("GET", "/api/v1/auth/session", self._http_session, name="auth-session")
        registration.route(
            "POST", "/api/v1/auth/login/start", self._http_login_start, name="auth-login-start"
        )
        registration.route(
            "GET", "/api/v1/auth/callback", self._http_callback, name="auth-callback"
        )
        registration.route("POST", "/api/v1/auth/logout", self._http_logout, name="auth-logout")
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

    async def _provide_web_session_service(
        self, dependencies: object
    ) -> WebSessionApplicationService:
        registry = await cast(RequestDependencyScope, dependencies).resolve(PROVIDER_REGISTRY)
        unit_of_work_factory = await cast(RequestDependencyScope, dependencies).resolve(
            UNIT_OF_WORK_FACTORY
        )
        service = _web_session_service(registry, unit_of_work_factory)
        self._web_sessions = service
        return service

    @staticmethod
    async def _provide_context_resolver(dependencies: object) -> WebSessionContextResolver:
        service = await cast(RequestDependencyScope, dependencies).resolve(WEB_SESSION_SERVICE)
        return WebSessionContextResolver(service)

    async def _csrf_middleware(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return await call_next(request)
        handle = cookie_value(request.headers, SESSION_COOKIE)
        if handle is None:
            return await call_next(request)
        service = self._web_sessions
        if service is None:
            raise BusinessOSError(
                "authentication_unavailable",
                "Authentication service is unavailable",
                status_code=503,
            )
        session = await service.get_session(handle, touch=False)
        supplied = request.headers.get("x-csrf-token", "")
        if (
            session is None
            or not supplied
            or not secrets.compare_digest(supplied, session.csrf_token)
        ):
            raise BusinessOSError("invalid_csrf", "CSRF validation failed", status_code=403)
        fetch_site = request.headers.get("sec-fetch-site")
        if fetch_site not in {None, "same-origin", "none"}:
            raise BusinessOSError("invalid_csrf", "CSRF validation failed", status_code=403)
        origin = request.headers.get("origin")
        host = request.headers.get("host")
        if origin is not None and (host is None or origin != f"{request.scheme}://{host}"):
            raise BusinessOSError("invalid_csrf", "CSRF validation failed", status_code=403)
        return await call_next(request)

    @staticmethod
    async def _resolve_service(
        request: Request, dependencies: RequestDependencyScope
    ) -> WebSessionApplicationService:
        service = await dependencies.resolve(WEB_SESSION_SERVICE)
        return service

    async def _http_session(
        self, request: Request, dependencies: RequestDependencyScope
    ) -> Response:
        service = await self._resolve_service(request, dependencies)
        handle = cookie_value(request.headers, SESSION_COOKIE)
        session = await service.get_session(handle) if handle else None
        if session is None:
            response = Response.json(
                {"code": "unauthenticated", "message": "Authentication required"},
                status_code=401,
            )
            response.append_header("set-cookie", expire_cookie(SESSION_COOKIE))
            return response
        return Response.json(service.project(session))

    async def _http_login_start(
        self, request: Request, dependencies: RequestDependencyScope
    ) -> Response:
        service = await self._resolve_service(request, dependencies)
        payload = await request.json()
        if not isinstance(payload, dict):
            raise BusinessOSError("invalid_request", "Request must be an object", status_code=400)
        payload = cast(dict[str, object], payload)
        provider = payload.get("provider", "default")
        return_to = payload.get("return_to")
        if not isinstance(provider, str) or not isinstance(return_to, str | None):
            raise BusinessOSError("invalid_request", "Request is not valid", status_code=400)
        started = await service.start_login(
            provider, return_to, rate_limit_key=f"login:{request.client_host}"
        )
        response = Response.json(
            {
                "authorization_url": started.authorization_url,
                "expires_at": started.expires_at,
            }
        )
        response.append_header(
            "set-cookie", transaction_cookie(started.browser_binding, started.expires_at)
        )
        return response

    async def _http_callback(
        self, request: Request, dependencies: RequestDependencyScope
    ) -> Response:
        service = await self._resolve_service(request, dependencies)
        state = request.query_params.get("state", ("",))[0]
        code = request.query_params.get("code", ("",))[0]
        binding = cookie_value(request.headers, AUTH_TRANSACTION_COOKIE) or ""
        if not state or not code or not binding:
            if state:
                try:
                    await service.transactions.consume(state, binding)
                except BusinessOSError:
                    pass
            elif binding:
                await service.transactions.clear_browser_binding(binding)
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
        except BusinessOSError as exc:
            response = Response.json(exc.payload(), status_code=exc.status_code)
            response.append_header("set-cookie", expire_cookie(AUTH_TRANSACTION_COOKIE))
            return response
        except Exception:
            await service.transactions.clear_browser_binding(binding)
            response = Response.json(
                {"code": "invalid_authentication_callback", "message": "Authentication failed"},
                status_code=401,
            )
            response.append_header("set-cookie", expire_cookie(AUTH_TRANSACTION_COOKIE))
            return response
        response = Response(status_code=303, headers={"location": return_to})
        response.append_header("set-cookie", expire_cookie(AUTH_TRANSACTION_COOKIE))
        response.append_header("set-cookie", session_cookie(handle, session.absolute_expires_at))
        return response

    async def _http_logout(
        self, request: Request, dependencies: RequestDependencyScope
    ) -> Response:
        service = await self._resolve_service(request, dependencies)
        handle = cookie_value(request.headers, SESSION_COOKIE)
        if handle:
            session = await service.get_session(handle, touch=False)
            supplied = request.headers.get("x-csrf-token", "")
            if session is not None and not secrets.compare_digest(supplied, session.csrf_token):
                raise BusinessOSError("invalid_csrf", "CSRF validation failed", status_code=403)
            await service.logout(handle)
        response = Response(status_code=204)
        response.append_header("set-cookie", expire_cookie(SESSION_COOKIE))
        return response

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
