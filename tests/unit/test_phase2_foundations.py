from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from businessos_identity import (
    ConfigureOIDCProvider,
    CreateUser,
    OIDCConfiguration,
    OIDCTokenVerifier,
)
from businessos_organization import CreateLegalEntity
from businessos_tenant import DeploymentMode, ProvisionTenant, TenantLifecycleHooks
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import ValidationError

from businessos.errors import BusinessOSError


class StaticKeyResolver:
    def __init__(self, key: object) -> None:
        self.key = key

    async def resolve(self, token: str) -> object:
        return self.key


@pytest.mark.asyncio
async def test_oidc_verifier_requires_signature_issuer_audience_and_tenant() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    configuration = OIDCConfiguration(
        issuer="https://identity.example.test",
        audience="businessos",
        jwks_uri="https://identity.example.test/jwks",
    )
    verifier = OIDCTokenVerifier(configuration, StaticKeyResolver(private_key.public_key()))
    now = datetime.now(UTC)
    tenant_id = uuid4()
    claims = {
        "iss": configuration.issuer,
        "sub": "subject-1",
        "aud": configuration.audience,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "businessos_tenant_id": str(tenant_id),
        "amr": ["pwd", "mfa"],
    }
    token = jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": "test"})

    verified = await verifier.verify(token)
    assert verified.businessos_tenant_id == tenant_id
    assert verified.amr == ("pwd", "mfa")

    wrong_audience = jwt.encode(
        {**claims, "aud": "other"}, private_key, algorithm="RS256", headers={"kid": "test"}
    )
    with pytest.raises(BusinessOSError) as failure:
        await verifier.verify(wrong_audience)
    assert failure.value.code == "invalid_token"
    assert "other" not in str(failure.value)


def test_oidc_configuration_rejects_unsafe_transport_and_algorithms() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        OIDCConfiguration(
            issuer="http://identity.example.test",
            audience="businessos",
            jwks_uri="https://identity.example.test/jwks",
        )
    with pytest.raises(ValueError, match="asymmetric"):
        OIDCConfiguration(
            issuer="https://identity.example.test",
            audience="businessos",
            jwks_uri="https://identity.example.test/jwks",
            algorithms=("HS256",),
        )


@pytest.mark.asyncio
async def test_tenant_lifecycle_hooks_are_ordered() -> None:
    calls: list[str] = []

    class Hook:
        def __init__(self, name: str) -> None:
            self.name = name

        async def export(self, tenant_id: object) -> None:
            calls.append(f"export:{self.name}")

        async def delete(self, tenant_id: object) -> None:
            calls.append(f"delete:{self.name}")

        async def restore(self, tenant_id: object) -> None:
            calls.append(f"restore:{self.name}")

    hooks = TenantLifecycleHooks()
    hooks.register("z.module", Hook("z"))
    hooks.register("a.module", Hook("a"))
    with pytest.raises(ValueError, match="already registered"):
        hooks.register("a.module", Hook("duplicate"))

    tenant_id = uuid4()
    await hooks.export(tenant_id)
    await hooks.delete(tenant_id)
    await hooks.restore(tenant_id)
    assert calls == ["export:a", "export:z", "delete:z", "delete:a", "restore:a", "restore:z"]


def test_phase2_boundary_models_reject_invalid_identity_and_organization_values() -> None:
    tenant_id = uuid4()
    ProvisionTenant(
        tenant_id=tenant_id,
        slug="global-business",
        name="Global Business",
        deployment_mode=DeploymentMode.SHARED_SCHEMA,
        region="eu-west",
    )
    with pytest.raises(ValidationError):
        CreateUser(tenant_id=tenant_id, email="not-an-email", display_name="Bad")
    with pytest.raises(ValidationError):
        ConfigureOIDCProvider(
            tenant_id=tenant_id,
            issuer="http://unsafe.example",
            audience="businessos",
            jwks_uri="https://safe.example/jwks",
        )
    with pytest.raises(ValidationError):
        CreateLegalEntity(
            tenant_id=tenant_id,
            code="LEGAL",
            name="Legal",
            enterprise_group_id=uuid4(),
            country_code="usa",
        )
