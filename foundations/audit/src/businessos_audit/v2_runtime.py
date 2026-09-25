"""Audit-owned V2 write authority and provenance projection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from businessos_identity import AUTHENTICATED_PRINCIPAL, AuthenticatedPrincipalBinding

from businessos.sdk import (
    BusinessOSError,
    DependencyResolver,
    HandlerInvocationKind,
    HandlingContext,
    validate_handler_invocation,
)

from .models import AuditRecord
from .v2_contracts import AUDIT_APPENDER_V2, AuditEvidenceV2

if TYPE_CHECKING:
    from .module import AuditModule


async def trusted_interactive_actor(ctx: HandlingContext) -> dict[str, object]:
    binding = await ctx.dependencies.resolve(AUTHENTICATED_PRINCIPAL)
    tenant = ctx.request.tenant
    if (
        type(binding) is not AuthenticatedPrincipalBinding
        or binding.request is not ctx.request
        or tenant is None
        or binding.principal.tenant_id != tenant.tenant_id
        or binding.principal.principal_id != tenant.principal_id
        or binding.principal.principal_type not in {"user", "service_account", "device"}
    ):
        raise BusinessOSError("unauthenticated", "Trusted actor required", status_code=401)
    return {
        "type": binding.principal.principal_type,
        "id": str(binding.principal.principal_id),
        "source": "identity.authenticated_principal.v1",
        "scope": {
            "installation_id": str(tenant.installation_id),
            "company_id": str(tenant.active_company_id) if tenant.active_company_id else None,
            "legal_entity_id": str(tenant.legal_entity_id) if tenant.legal_entity_id else None,
            "operating_site_id": str(tenant.operating_site_id)
            if tenant.operating_site_id
            else None,
        },
    }


@dataclass(slots=True)
class AuditAppenderProvider:
    owner: AuditModule
    resolver: DependencyResolver
    active: bool = True

    async def append(self, evidence: AuditEvidenceV2, ctx: HandlingContext) -> AuditRecord:
        if not self.active or ctx.dependencies is not self.resolver:
            raise PermissionError("Audit appender is not active in this dependency scope")
        resolved = await self.resolver.resolve(AUDIT_APPENDER_V2)
        if resolved is not self:
            raise PermissionError("Audit appender provider generation changed")
        invocation = validate_handler_invocation(
            ctx.invocation,
            ctx.request,
            ctx.unit_of_work,
            invocation_kind=HandlerInvocationKind.COMMAND,
        )
        if (
            invocation.generation.owner != invocation.owner_module_id
            or not invocation.has_direct_dependency("foundation.audit")
        ):
            raise PermissionError("Command owner lacks a direct Audit dependency")
        actor = await trusted_interactive_actor(ctx)
        return await self.owner._append_v3(  # pyright: ignore[reportPrivateUsage]
            ctx.request,
            ctx.unit_of_work,
            evidence,
            provenance={
                "version": "audit.provenance.v3",
                "path": "handler-command",
                "actual_actor": actor,
                "origin_actor": None,
                "support": None,
                "handler": {
                    "owner": invocation.owner_module_id,
                    "generation": invocation.generation.number,
                },
                "correlation_source": "request-context",
                "trace_source": "request-context",
            },
        )
