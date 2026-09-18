import sys
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from businessos_identity import (
    AUTH_TRANSACTION_PROVIDER,
    OIDC_BROWSER_PROVIDER,
    PRINCIPAL_SESSION_VALIDATOR,
    SESSION_PROVIDER,
    WEB_SESSION_CONFIGURATION,
    AuthenticatedPrincipal,
    AuthenticationStrength,
    CreateUser,
    GrantMembership,
    IdentityModule,
    InMemoryAuthorizationTransactionStore,
    InMemoryWebSessionStore,
    PrincipalIdentity,
    WebSessionConfiguration,
)
from businessos_organization import (
    AssignPrincipal,
    CreateCompany,
    CreateEnterpriseGroup,
    CreateLegalEntity,
    OrganizationScopeType,
)
from businessos_policy import (
    AssignPermissionToRoleCommand,
    AssignRoleToSubjectCommand,
    CreateRoleCommand,
    RegisterPermissionCommand,
)
from businessos_tenant import (
    DeploymentMode,
    ProvisionTenant,
    TenantModule,
    TenantStatus,
    TransitionTenant,
)

from businessos.bootstrap import create_application
from businessos.config import Settings
from businessos.context import RequestContext, TenantContext
from businessos.modules import discover_modules
from businessos.security import Authorizer
from tests.conftest import PostgreSQLTestDatabase


class StubOIDCProvider:
    def __init__(self, identity: PrincipalIdentity | None = None) -> None:
        self.state = ""
        self.nonce = ""
        self.challenge_method = ""
        self.identity = identity

    async def readiness(self) -> None:
        return None

    async def authorization_url(self, **values: str) -> tuple[str, str]:
        self.state = values["state"]
        self.nonce = values["nonce"]
        self.challenge_method = values["code_challenge_method"]
        return (
            f"https://idp.example.test/authorize?state={self.state}",
            "https://idp.example.test",
        )

    async def exchange_code(self, **values: str) -> AuthenticatedPrincipal:
        if values["expected_nonce"] != self.nonce or values["expected_issuer"] != (
            "https://idp.example.test"
        ):
            raise AssertionError("OIDC callback did not preserve nonce and issuer")
        return AuthenticatedPrincipal(
            identity=self.identity
            or PrincipalIdentity(
                tenant_id=uuid4(),
                principal_id=uuid4(),
                principal_type="user",
                authentication_strength=AuthenticationStrength.MFA,
            ),
            display_name="Phase 4.5 Operator",
            email="operator@example.test",
        )


class AcceptPrincipal:
    async def readiness(self) -> None:
        return None

    async def validate(self, principal: PrincipalIdentity) -> None:
        return None


class AllowAllPolicy:
    async def is_allowed(
        self, principal_id: object, tenant: TenantContext, permission: str
    ) -> bool:
        return True


async def dispatch(application: Any, message: object, context: RequestContext) -> object:
    assert application.runtime is not None
    async with application.container.request_scope() as dependencies:
        return await application.runtime.messages.command(message, context, dependencies)


@pytest.mark.skipif(sys.version_info < (3, 13), reason="BusinessOS runtime requires Python 3.13")
@pytest.mark.asyncio
async def test_real_asgi_login_session_csrf_and_logout_contract() -> None:
    sessions = InMemoryWebSessionStore()
    transactions = InMemoryAuthorizationTransactionStore()
    oidc = StubOIDCProvider()
    configuration = WebSessionConfiguration(
        installation_id=uuid4(),
        callback_url="https://businessos.example.test/api/v1/auth/callback",
    )
    application = create_application(
        Settings(database_readiness_enabled=False),
        modules=(TenantModule(), IdentityModule()),
        infrastructure_providers={
            SESSION_PROVIDER: sessions,
            AUTH_TRANSACTION_PROVIDER: transactions,
            OIDC_BROWSER_PROVIDER: oidc,
            PRINCIPAL_SESSION_VALIDATOR: AcceptPrincipal(),
            WEB_SESSION_CONFIGURATION: configuration,
        },
    )
    await application.startup()
    try:
        transport = httpx.ASGITransport(app=cast(Any, application))
        async with httpx.AsyncClient(
            transport=transport, base_url="https://businessos.example.test"
        ) as client:
            missing = await client.get("/api/v1/auth/session")
            assert missing.status_code == 401

            started = await client.post(
                "/api/v1/auth/login/start", json={"return_to": "/dashboard"}
            )
            assert started.status_code == 200
            assert oidc.challenge_method == "S256"
            assert client.cookies.get("__Host-businessos_auth_txn")

            callback = await client.get(
                "/api/v1/auth/callback",
                params={"state": oidc.state, "code": "authorization-code"},
                follow_redirects=False,
            )
            assert callback.status_code == 303
            assert callback.headers["location"] == "/dashboard"
            assert client.cookies.get("__Host-businessos_session")
            assert client.cookies.get("__Host-businessos_auth_txn") is None

            current = await client.get("/api/v1/auth/session")
            assert current.status_code == 200
            projection = current.json()
            assert projection["status"] == "authenticated"
            assert "access_token" not in projection
            assert "refresh_token" not in projection

            for method in ("POST", "PUT", "PATCH", "DELETE"):
                rejected_unsafe = await client.request(method, "/api/v1/missing")
                assert rejected_unsafe.status_code == 403
            assert (await client.get("/api/v1/missing")).status_code == 404

            rejected = await client.post("/api/v1/auth/logout")
            assert rejected.status_code == 403
            logged_out = await client.post(
                "/api/v1/auth/logout",
                headers={
                    "x-csrf-token": projection["csrf_token"],
                    "origin": "https://businessos.example.test",
                    "sec-fetch-site": "same-origin",
                },
            )
            assert logged_out.status_code == 204
            assert (await client.get("/api/v1/auth/session")).status_code == 401
    finally:
        await application.shutdown()


@pytest.mark.skipif(sys.version_info < (3, 13), reason="BusinessOS runtime requires Python 3.13")
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_authenticated_organization_and_policy_http_facades(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    tenant_id = uuid4()
    principal_id = uuid4()
    installation_id = uuid4()
    sessions = InMemoryWebSessionStore()
    transactions = InMemoryAuthorizationTransactionStore()
    oidc = StubOIDCProvider(
        PrincipalIdentity(
            tenant_id=tenant_id,
            principal_id=principal_id,
            principal_type="user",
            authentication_strength=AuthenticationStrength.MFA,
        )
    )
    configuration = WebSessionConfiguration(
        installation_id=installation_id,
        callback_url="https://businessos.example.test/api/v1/auth/callback",
    )
    modules = tuple(
        module
        for module in discover_modules()
        if module.manifest.module_id.startswith("foundation.")
    )
    application = create_application(
        Settings(environment="test", database_url=postgres_database.runtime_url),
        modules=modules,
        authorizer=Authorizer(AllowAllPolicy()),
        infrastructure_providers={
            SESSION_PROVIDER: sessions,
            AUTH_TRANSACTION_PROVIDER: transactions,
            OIDC_BROWSER_PROVIDER: oidc,
            WEB_SESSION_CONFIGURATION: configuration,
        },
    )
    assert application.runtime is not None
    application.runtime.migrations.upgrade(postgres_database.migration_url)
    seed_context = RequestContext(
        correlation_id="phase45-http-contract",
        trace_id=uuid4().hex,
        tenant=TenantContext(
            installation_id=installation_id,
            tenant_id=tenant_id,
            principal_id=principal_id,
            authentication_strength="mfa",
        ),
    )
    group_id, legal_entity_id, company_id = uuid4(), uuid4(), uuid4()
    await application.startup()
    try:
        await dispatch(
            application,
            ProvisionTenant(
                tenant_id=tenant_id,
                slug=f"phase45-{tenant_id.hex[:8]}",
                name="Phase 4.5 Tenant",
                deployment_mode=DeploymentMode.SHARED_SCHEMA,
                region="test",
            ),
            seed_context,
        )
        await dispatch(
            application,
            TransitionTenant(tenant_id=tenant_id, target=TenantStatus.PROVISIONING),
            seed_context,
        )
        await dispatch(
            application,
            TransitionTenant(tenant_id=tenant_id, target=TenantStatus.ACTIVE),
            seed_context,
        )
        await dispatch(
            application,
            CreateUser(
                user_id=principal_id,
                tenant_id=tenant_id,
                email="operator@example.test",
                display_name="Phase 4.5 Operator",
            ),
            seed_context,
        )
        await dispatch(
            application,
            GrantMembership(
                tenant_id=tenant_id,
                principal_id=principal_id,
                principal_type="user",
            ),
            seed_context,
        )
        await dispatch(
            application,
            CreateEnterpriseGroup(
                id=group_id, tenant_id=tenant_id, code="GROUP", name="Enterprise Group"
            ),
            seed_context,
        )
        await dispatch(
            application,
            CreateLegalEntity(
                id=legal_entity_id,
                tenant_id=tenant_id,
                enterprise_group_id=group_id,
                code="LEGAL",
                name="Legal Entity",
                country_code="US",
            ),
            seed_context,
        )
        await dispatch(
            application,
            CreateCompany(
                id=company_id,
                tenant_id=tenant_id,
                legal_entity_id=legal_entity_id,
                code="COMPANY",
                name="Company",
                base_currency="USD",
                timezone="UTC",
            ),
            seed_context,
        )
        await dispatch(
            application,
            AssignPrincipal(
                tenant_id=tenant_id,
                principal_id=principal_id,
                scope_type=OrganizationScopeType.COMPANY,
                scope_id=company_id,
            ),
            seed_context,
        )
        await dispatch(
            application,
            RegisterPermissionCommand(code="sales.read", name="Read sales", category="sales"),
            seed_context,
        )
        role = await dispatch(
            application,
            CreateRoleCommand(tenant_id=tenant_id, code="operator", name="Operator"),
            seed_context,
        )
        role_id = cast(Any, role).id
        await dispatch(
            application,
            AssignPermissionToRoleCommand(
                tenant_id=tenant_id, role_id=role_id, permission_code="sales.read"
            ),
            seed_context,
        )
        await dispatch(
            application,
            AssignRoleToSubjectCommand(
                tenant_id=tenant_id, subject_id=principal_id, role_id=role_id
            ),
            seed_context,
        )

        transport = httpx.ASGITransport(app=cast(Any, application))
        async with httpx.AsyncClient(
            transport=transport, base_url="https://businessos.example.test"
        ) as client:
            await client.post("/api/v1/auth/login/start", json={"return_to": "/dashboard"})
            callback = await client.get(
                "/api/v1/auth/callback",
                params={"state": oidc.state, "code": "authorization-code"},
                follow_redirects=False,
            )
            assert callback.status_code == 303
            current = (await client.get("/api/v1/auth/session")).json()
            headers = {
                "x-csrf-token": current["csrf_token"],
                "origin": "https://businessos.example.test",
                "sec-fetch-site": "same-origin",
            }

            hierarchy = await client.get("/api/v1/organization/hierarchy")
            assert hierarchy.status_code == 200
            assert hierarchy.json()["companies"][0]["id"] == str(company_id)

            selected = await client.post(
                "/api/v1/organization/active-scope",
                json={
                    "enterprise_group_id": str(group_id),
                    "legal_entity_id": str(legal_entity_id),
                    "company_id": str(company_id),
                },
                headers=headers,
            )
            assert selected.status_code == 200
            selected_body = selected.json()
            assert selected_body["scope"]["company_id"] == str(company_id)
            rotated_headers = {**headers, "x-csrf-token": selected_body["csrf_token"]}

            validated = await client.post(
                "/api/v1/organization/validate-scope",
                json={
                    "enterprise_group_id": str(group_id),
                    "legal_entity_id": str(legal_entity_id),
                    "company_id": str(company_id),
                },
                headers=rotated_headers,
            )
            assert validated.status_code == 200
            assert validated.json()["valid"] is True

            decision = await client.post(
                "/api/v1/policy/authorize",
                json={"action": "sales.read", "resource": "sales"},
                headers=rotated_headers,
            )
            assert decision.status_code == 200
            assert decision.json()["allowed"] is True

            field_access = await client.post(
                "/api/v1/policy/field-access",
                json={"resource_type": "sales", "field_name": "margin"},
                headers=rotated_headers,
            )
            assert field_access.status_code == 200
            approval = await client.post(
                "/api/v1/policy/approval-limit",
                json={"action_type": "sales.approve", "amount": "100", "currency": "USD"},
                headers=rotated_headers,
            )
            assert approval.status_code == 200

            stale_logout = await client.post("/api/v1/auth/logout", headers=headers)
            assert stale_logout.status_code == 403
            assert stale_logout.json()["code"] == "invalid_csrf"
            reconciled = await client.get("/api/v1/auth/session")
            assert reconciled.status_code == 200
            assert reconciled.json()["active_scope"]["company_id"] == str(company_id)
            confirmed_logout = await client.post(
                "/api/v1/auth/logout",
                headers={**headers, "x-csrf-token": reconciled.json()["csrf_token"]},
            )
            assert confirmed_logout.status_code == 204
            assert (await client.get("/api/v1/auth/session")).status_code == 401
    finally:
        await application.shutdown()
        application.runtime.migrations.downgrade(postgres_database.migration_url)
