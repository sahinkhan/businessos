from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from businessos_identity import (
    AuthenticatedPrincipal,
    AuthenticationStrength,
    InMemoryAuthorizationTransactionStore,
    InMemoryWebSessionStore,
    OIDCAuthorizationCodeAdapter,
    PrincipalIdentity,
    WebSessionApplicationService,
    WebSessionConfiguration,
)
from businessos_identity.web_sessions import (
    AUTH_TRANSACTION_COOKIE,
    SESSION_COOKIE,
    AuthorizationTransaction,
    expire_cookie,
    session_cookie,
    transaction_cookie,
)

from businessos.errors import BusinessOSError


class FakeOIDCProvider:
    def __init__(self) -> None:
        self.authorization: dict[str, str] = {}
        self.exchange: dict[str, str] = {}
        self.fail_exchange = False

    async def authorization_url(self, **values: str) -> tuple[str, str]:
        self.authorization = values
        query = f"state={values['state']}&nonce={values['nonce']}"
        return f"https://idp.example.test/authorize?{query}", "https://idp.example.test"

    async def exchange_code(self, **values: str) -> AuthenticatedPrincipal:
        self.exchange = values
        if self.fail_exchange:
            raise BusinessOSError("invalid_oidc_response", "Authentication failed", status_code=401)
        return AuthenticatedPrincipal(
            identity=PrincipalIdentity(
                tenant_id=uuid4(),
                principal_id=uuid4(),
                principal_type="user",
                authentication_strength=AuthenticationStrength.MFA,
            ),
            display_name="Test Operator",
            email="operator@example.test",
        )


class AcceptPrincipal:
    async def validate(self, principal: PrincipalIdentity) -> None:
        return None


class FakeAuthorizationClient:
    issuer = "https://idp.example.test"

    def __init__(self) -> None:
        self.authorization: dict[str, str] = {}
        self.exchange: dict[str, str] = {}

    async def authorization_url(self, **values: str) -> str:
        self.authorization = values
        return "https://idp.example.test/authorize"

    async def exchange_code(self, **values: str) -> str:
        self.exchange = values
        return "signed-id-token"


class FakeIdentityResolver:
    def __init__(self) -> None:
        self.token = ""
        self.nonce = ""
        self.required_nonce: str | None = None

    async def authenticate_token(
        self, token: str, *, expected_nonce: str | None = None
    ) -> PrincipalIdentity:
        self.token = token
        self.nonce = expected_nonce or ""
        if self.required_nonce is not None and expected_nonce != self.required_nonce:
            raise BusinessOSError("invalid_oidc_nonce", "Authentication failed", status_code=401)
        return PrincipalIdentity(
            tenant_id=uuid4(),
            principal_id=uuid4(),
            principal_type="user",
            authentication_strength=AuthenticationStrength.MFA,
        )


def service() -> tuple[
    WebSessionApplicationService,
    InMemoryWebSessionStore,
    InMemoryAuthorizationTransactionStore,
    FakeOIDCProvider,
]:
    sessions = InMemoryWebSessionStore()
    transactions = InMemoryAuthorizationTransactionStore()
    oidc = FakeOIDCProvider()
    application = WebSessionApplicationService(
        configuration=WebSessionConfiguration(
            installation_id=uuid4(),
            callback_url="https://businessos.example.test/api/v1/auth/callback",
        ),
        sessions=sessions,
        transactions=transactions,
        oidc=oidc,
        principal_validator=AcceptPrincipal(),
    )
    return application, sessions, transactions, oidc


@pytest.mark.asyncio
async def test_oidc_adapter_enforces_s256_issuer_and_nonce_validation() -> None:
    client = FakeAuthorizationClient()
    resolver = FakeIdentityResolver()
    adapter = OIDCAuthorizationCodeAdapter(
        {"enterprise": client},
        {"enterprise": resolver},  # type: ignore[dict-item]
    )

    with pytest.raises(BusinessOSError, match="not valid"):
        await adapter.authorization_url(
            provider_id="enterprise",
            redirect_uri="https://businessos.example.test/api/v1/auth/callback",
            state="state",
            nonce="nonce",
            code_challenge="challenge",
            code_challenge_method="plain",
        )

    url, issuer = await adapter.authorization_url(
        provider_id="enterprise",
        redirect_uri="https://businessos.example.test/api/v1/auth/callback",
        state="state",
        nonce="nonce",
        code_challenge="challenge",
        code_challenge_method="S256",
    )
    assert url.endswith("/authorize")
    assert issuer == client.issuer
    await adapter.exchange_code(
        provider_id="enterprise",
        code="code",
        redirect_uri="https://businessos.example.test/api/v1/auth/callback",
        pkce_verifier="verifier",
        expected_nonce="expected-nonce",
        expected_issuer=client.issuer,
    )
    assert client.exchange["pkce_verifier"] == "verifier"
    assert resolver.token == "signed-id-token"
    assert resolver.nonce == "expected-nonce"

    resolver.required_nonce = "transaction-nonce"
    with pytest.raises(BusinessOSError, match="Authentication failed"):
        await adapter.exchange_code(
            provider_id="enterprise",
            code="code",
            redirect_uri="https://businessos.example.test/api/v1/auth/callback",
            pkce_verifier="verifier",
            expected_nonce="wrong-nonce",
            expected_issuer=client.issuer,
        )


@pytest.mark.asyncio
async def test_login_uses_transaction_specific_s256_and_browser_binding() -> None:
    application, _, transactions, oidc = service()
    started = await application.start_login("enterprise", "/dashboard")
    state = oidc.authorization["state"]

    assert oidc.authorization["code_challenge_method"] == "S256"
    assert oidc.authorization["nonce"]
    assert oidc.authorization["code_challenge"]
    transaction = await transactions.consume(state, started.browser_binding)
    assert transaction.return_to == "/dashboard"
    assert transaction.pkce_challenge == oidc.authorization["code_challenge"]
    assert transaction.pkce_verifier not in started.authorization_url


@pytest.mark.asyncio
async def test_login_start_rate_limit_fails_closed() -> None:
    application, _, _, _ = service()
    application.configuration = WebSessionConfiguration(
        installation_id=uuid4(),
        callback_url="https://businessos.example.test/api/v1/auth/callback",
        login_attempt_limit=1,
    )
    await application.start_login("default", "/", rate_limit_key="browser-address")
    with pytest.raises(BusinessOSError) as limited:
        await application.start_login("default", "/", rate_limit_key="browser-address")
    assert limited.value.status_code == 429


@pytest.mark.asyncio
async def test_transaction_is_bound_consumed_once_and_replay_is_rejected() -> None:
    application, _, transactions, oidc = service()
    started = await application.start_login("default", "/")
    state = oidc.authorization["state"]

    with pytest.raises(BusinessOSError, match="Browser binding"):
        await transactions.consume(state, "wrong-browser")
    with pytest.raises(BusinessOSError) as replay:
        await transactions.consume(state, started.browser_binding)
    assert replay.value.status_code == 409


@pytest.mark.asyncio
async def test_wrong_or_missing_state_clears_the_browser_transaction() -> None:
    application, _, transactions, oidc = service()
    started = await application.start_login("default", "/")

    with pytest.raises(BusinessOSError) as missing:
        await transactions.consume("wrong-state", started.browser_binding)
    assert missing.value.status_code == 401
    with pytest.raises(BusinessOSError) as cleared:
        await transactions.consume(oidc.authorization["state"], started.browser_binding)
    assert cleared.value.status_code == 409


@pytest.mark.asyncio
async def test_missing_expired_and_unsafe_transactions_fail_closed() -> None:
    application, _, transactions, _ = service()
    with pytest.raises(BusinessOSError):
        await transactions.consume("missing", "missing")
    with pytest.raises(BusinessOSError, match="Return path"):
        await application.start_login("default", "https://attacker.example/")

    expired = AuthorizationTransaction(
        state="expired-state",
        nonce="nonce",
        pkce_verifier="verifier",
        pkce_challenge="challenge",
        browser_binding_digest=__import__("hashlib").sha256(b"binding").hexdigest(),
        provider_id="default",
        expected_issuer="https://idp.example.test",
        return_to="/",
        issued_at=datetime.now(UTC) - timedelta(minutes=10),
        expires_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    await transactions.create(expired)
    with pytest.raises(BusinessOSError, match="expired"):
        await transactions.consume("expired-state", "binding")


@pytest.mark.asyncio
async def test_failed_exchange_clears_and_cannot_resurrect_transaction() -> None:
    application, _, _, oidc = service()
    started = await application.start_login("default", "/")
    state = oidc.authorization["state"]
    oidc.fail_exchange = True

    with pytest.raises(BusinessOSError):
        await application.complete_oidc_login(
            state=state, code="bad-code", browser_binding=started.browser_binding
        )
    with pytest.raises(BusinessOSError) as replay:
        await application.complete_oidc_login(
            state=state, code="retry", browser_binding=started.browser_binding
        )
    assert replay.value.status_code == 409


@pytest.mark.asyncio
async def test_session_rotation_expiry_and_logout_invalidate_old_handles() -> None:
    application, sessions, _, oidc = service()
    started = await application.start_login("default", "/")
    handle, session, _ = await application.complete_oidc_login(
        state=oidc.authorization["state"],
        code="code",
        browser_binding=started.browser_binding,
    )
    assert application.project(session).principal.email == "operator@example.test"

    new_handle, replacement = await application.rotate_scope(handle, session.active_scope)
    assert new_handle != handle
    assert replacement.generation == session.generation + 1
    assert replacement.csrf_token != session.csrf_token
    assert await sessions.get(handle) is None
    assert await sessions.get(new_handle) is not None

    await application.logout(new_handle)
    assert await sessions.get(new_handle) is None


@pytest.mark.asyncio
async def test_expired_sessions_fail_closed_and_new_logins_do_not_fixate_handles() -> None:
    application, sessions, _, oidc = service()
    first = await application.start_login("default", "/")
    first_handle, first_session, _ = await application.complete_oidc_login(
        state=oidc.authorization["state"], code="one", browser_binding=first.browser_binding
    )
    second = await application.start_login("default", "/")
    second_handle, _, _ = await application.complete_oidc_login(
        state=oidc.authorization["state"], code="two", browser_binding=second.browser_binding
    )
    assert first_handle != second_handle

    expired = first_session.model_copy(
        update={
            "idle_expires_at": datetime.now(UTC) - timedelta(minutes=2),
            "absolute_expires_at": datetime.now(UTC) - timedelta(minutes=1),
        }
    )
    expired_handle = await sessions.create(expired)
    assert await application.get_session(expired_handle) is None


def test_cookie_contract_is_host_scoped_secure_and_http_only() -> None:
    expiry = datetime.now(UTC) + timedelta(minutes=5)
    session = session_cookie("opaque", expiry)
    transaction = transaction_cookie("binding", expiry)
    for value, name in (
        (session, SESSION_COOKIE),
        (transaction, AUTH_TRANSACTION_COOKIE),
    ):
        assert value.startswith(f"{name}=")
        assert "Secure" in value
        assert "HttpOnly" in value
        assert "SameSite=Lax" in value
        assert "Path=/" in value
        assert "Domain=" not in value
    assert "Max-Age=0" in expire_cookie(SESSION_COOKIE)
