"""The Audit provider checks a live command invocation on every append."""

from typing import Any, cast
from uuid import uuid4

import pytest
from businessos_audit import AuditEvidenceV2, AuditModule
from businessos_audit.v2_runtime import AuditAppenderProvider

from businessos.activation import ContributionGeneration
from businessos.context import RequestContext, TenantContext
from businessos.handler_invocation import (
    HandlerInvocationDependency,
    HandlerInvocationKind,
    internal_issue_handler_invocation,
)
from businessos.messages import HandlingContext


class _Resolver:
    appender: AuditAppenderProvider

    async def resolve(self, key: object) -> AuditAppenderProvider:
        return self.appender


@pytest.mark.asyncio
async def test_appender_rejects_unissued_query_and_missing_direct_dependency() -> None:
    resolver = _Resolver()
    appender = AuditAppenderProvider(AuditModule(), cast(Any, resolver))
    resolver.appender = appender
    request = RequestContext()
    transaction = object()
    context = HandlingContext(request, cast(Any, resolver), cast(Any, transaction))
    evidence = AuditEvidenceV2(action="test", resource_type="resource")
    with pytest.raises(PermissionError, match="framework"):
        await appender.append(evidence, context)

    generation = ContributionGeneration("example.owner", 1)
    with internal_issue_handler_invocation(
        owner_module_id="example.owner",
        generation=generation,
        invocation_kind=HandlerInvocationKind.QUERY,
        direct_dependencies=(HandlerInvocationDependency("foundation.audit", ">=0.4,<1"),),
        request=request,
        transaction=cast(Any, transaction),
    ) as query:
        context.invocation = query
        with pytest.raises(PermissionError, match="does not match"):
            await appender.append(evidence, context)

    with internal_issue_handler_invocation(
        owner_module_id="example.owner",
        generation=generation,
        invocation_kind=HandlerInvocationKind.COMMAND,
        direct_dependencies=(HandlerInvocationDependency("example.intermediate", ">=1,<2"),),
        request=request,
        transaction=cast(Any, transaction),
    ) as transitive:
        context.invocation = transitive
        with pytest.raises(PermissionError, match="direct Audit dependency"):
            await appender.append(evidence, context)

    with pytest.raises(PermissionError, match="framework"):
        context.invocation = object()  # type: ignore[assignment]
        await appender.append(evidence, context)

    appender.active = False
    with pytest.raises(PermissionError, match="not active"):
        await appender.append(evidence, context)


@pytest.mark.asyncio
async def test_append_revalidates_mutated_nested_evidence_before_await() -> None:
    evidence = AuditEvidenceV2(action="test", resource_type="resource", details={"safe": {}})
    evidence.details["safe"]["api_token"] = "secret"
    request = RequestContext(
        tenant=TenantContext(installation_id=uuid4(), tenant_id=uuid4(), principal_id=uuid4())
    )
    with pytest.raises(ValueError, match="sensitive"):
        await AuditModule()._append_v3(  # pyright: ignore[reportPrivateUsage]
            request,
            cast(Any, object()),
            evidence,
            provenance={"actual_actor": {"id": "actor", "type": "user"}},
        )
