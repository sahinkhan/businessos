"""Published UI resolver/publication in the framework-owned protected Metadata UOW."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from businessos_identity.principal_binding import (
    AUTHENTICATED_PRINCIPAL,
    AuthenticatedPrincipalBinding,
)
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import and_, func, insert, or_, select, text, update
from sqlalchemy.engine import RowMapping

from businessos.sdk import (
    AUTHORIZER,
    METADATA_CATALOG,
    RESOURCE_OWNER_RESOLVER,
    BusinessOSError,
    HandlerInvocationKind,
    HandlingContext,
    NotFoundError,
    validate_handler_invocation,
)

from .models import CONTRACT_FENCE, MODULE_FENCE
from .ui_composition import UIComposition, apply_overlay, compose
from .ui_contracts import (
    Key,
    ResolvedUILabel,
    ResolvedUISchema,
    UIConflict,
    UIDeclarationProvenance,
    UIDiagnostic,
    UIModuleProvenance,
    UIOverlayDocument,
    UIOverlayProvenance,
    UIOverlayRecord,
    UIOverlayScope,
    UIOwnerCapabilities,
    UIResolution,
    UIResolutionProvenance,
    digest,
)
from .ui_contracts import (
    UIDiagnosticCode as Code,
)
from .ui_models import UI_OVERLAYS, UI_REVISIONS


@dataclass(frozen=True, slots=True)
class _Snapshot:
    composition: UIComposition
    compatibility_digest: str
    modules: tuple[UIModuleProvenance, ...]
    declarations: tuple[UIDeclarationProvenance, ...]
    schema_generation: int
    ui_generation: int


class _UIReadAuthority(BaseModel):
    """Private authority header; authorize disclosure before classification/conflict detail."""

    model_config = ConfigDict(frozen=True, extra="ignore")
    resource_namespace: Key
    owner_contract_version: str
    permission: Key


async def _guard(
    ctx: HandlingContext, kind: HandlerInvocationKind
) -> AuthenticatedPrincipalBinding:
    try:
        binding = validate_handler_invocation(
            ctx.invocation, ctx.request, ctx.unit_of_work, invocation_kind=kind
        )
    except PermissionError:
        raise BusinessOSError(
            "ui_invocation_required", "Issued Metadata invocation required", status_code=403
        ) from None
    if binding.owner_module_id != "foundation.metadata":
        raise BusinessOSError("ui_invocation_required", "Metadata owner required", status_code=403)
    principal = await ctx.dependencies.resolve(AUTHENTICATED_PRINCIPAL)
    tenant = ctx.request.tenant
    if (
        tenant is None
        or principal.request is not ctx.request
        or principal.principal.tenant_id != tenant.tenant_id
        or principal.principal.principal_id != tenant.principal_id
        or (
            tenant.credential_expires_at is not None
            and tenant.credential_expires_at <= datetime.now(UTC)
        )
    ):
        raise BusinessOSError(
            "ui_context_invalid", "Current authenticated context required", status_code=403
        )
    return principal


def _scope(
    ctx: HandlingContext, kind: UIOverlayScope, principal: AuthenticatedPrincipalBinding
) -> UUID:
    tenant = ctx.request.tenant
    if tenant is None:
        raise BusinessOSError("ui_scope_unavailable", "Trusted scope required", status_code=403)
    values = {
        UIOverlayScope.TENANT: tenant.tenant_id,
        UIOverlayScope.COMPANY: tenant.active_company_id,
        UIOverlayScope.SITE: tenant.operating_site_id,
        UIOverlayScope.USER: tenant.principal_id
        if principal.principal.principal_type == "user"
        else None,
    }
    value = values[kind]
    if type(value) is not UUID:
        raise BusinessOSError(
            "ui_scope_unavailable", "Eligible backend scope required", status_code=403
        )
    return value


async def _policy(ctx: HandlingContext, permissions: tuple[str, ...]) -> None:
    authorizer = await ctx.dependencies.resolve(AUTHORIZER)
    for permission in sorted(set(permissions)):
        await authorizer.require(ctx.request, permission)


async def _view_fence(ctx: HandlingContext, view_id: UUID, *, shared: bool) -> None:
    tenant = ctx.request.tenant
    assert tenant is not None
    # Both modes use the same transaction-scoped key. Normal operations acquire
    # contract -> sorted modules -> creation quota (if any) -> tenant/view -> row.
    await ctx.unit_of_work.persistence.execute(text("SET LOCAL lock_timeout = '5s'"))
    function = "pg_advisory_xact_lock_shared" if shared else "pg_advisory_xact_lock"
    await ctx.unit_of_work.persistence.execute(
        text(f"SELECT {function}(hashtextextended('ui:' || :tenant || ':' || :view,0))"),
        {"tenant": str(tenant.tenant_id), "view": str(view_id)},
    )


@asynccontextmanager
async def _snapshot(ctx: HandlingContext, view_id: UUID) -> AsyncGenerator[_Snapshot]:
    catalog = await ctx.dependencies.resolve(METADATA_CATALOG)
    try:
        async with catalog.admitted(
            kind_prefix="ui.", discriminator="view_id", value=str(view_id)
        ) as sources:
            bases = [s for s in sources if s.kind == "ui.base.v1"]
            capabilities = [s for s in sources if s.kind == "ui.capabilities.v1"]
            if len(bases) != 1 or len(capabilities) != 1:
                raise UIConflict(Code.STABLE_ID_CONFLICT if bases else Code.BASE_UNAVAILABLE)
            base = bases[0]
            header = _UIReadAuthority.model_validate_json(base.document_json)
            caps = UIOwnerCapabilities.model_validate_json(capabilities[0].document_json)
            owners = await ctx.dependencies.resolve(RESOURCE_OWNER_RESOLVER)
            binding = owners.resolve_owner(header.resource_namespace, header.owner_contract_version)
            if (
                binding.ownership.owner_module_id != base.owner
                or binding.ownership.resource_namespace != header.resource_namespace
                or binding.generation != base.generation
                or capabilities[0].owner != base.owner
                or capabilities[0].generation != base.generation
                or (caps.resource_namespace, caps.owner_contract_version)
                != (header.resource_namespace, header.owner_contract_version)
            ):
                raise UIConflict(Code.CAPABILITY_UNAVAILABLE)
            permissions = (
                header.permission,
                *(x.permission for x in caps.fields),
                *(x.permission for x in caps.actions),
            )
            if any(not p.startswith(base.owner + ".") for p in permissions):
                raise UIConflict(Code.CAPABILITY_UNAVAILABLE)
            await _policy(ctx, permissions)
            composition = compose(sources)
            session = ctx.unit_of_work.persistence
            await session.execute(text("SET LOCAL lock_timeout = '5s'"))
            fence = (
                (
                    await session.execute(
                        select(CONTRACT_FENCE)
                        .where(CONTRACT_FENCE.c.id == 1)
                        .with_for_update(read=True)
                    )
                )
                .mappings()
                .one()
            )
            source_modules = {s.owner: s for s in sources}
            generations = {s.owner: s.generation.number for s in sources}
            for source in sources:
                for generation in source.dependency_generations:
                    previous = generations.setdefault(generation.owner, generation.number)
                    if previous != generation.number:
                        raise UIConflict(Code.INCOMPATIBLE)
            module_ids = sorted(generations)
            if len(module_ids) > 128:
                raise UIConflict(Code.LIMIT_EXCEEDED)
            module_rows = (
                (
                    await session.execute(
                        select(MODULE_FENCE)
                        .where(MODULE_FENCE.c.module_id.in_(module_ids))
                        .order_by(MODULE_FENCE.c.module_id)
                        .with_for_update(read=True)
                    )
                )
                .mappings()
                .all()
            )
            if len(module_rows) != len(module_ids):
                raise UIConflict(Code.INCOMPATIBLE)
            modules = tuple(
                UIModuleProvenance(
                    module_id=row["module_id"],
                    module_version=source_modules[row["module_id"]].module_version
                    if row["module_id"] in source_modules
                    else "",
                    artifact_identity=row["artifact_identity"],
                    generation=row["generation"],
                    admission_generation=generations[row["module_id"]],
                )
                for row in module_rows
            )
            declarations = tuple(
                UIDeclarationProvenance(
                    key=s.key,
                    owner=s.owner,
                    kind=s.kind,
                    digest=digest(json.loads(s.document_json)),
                )
                for s in sorted(sources, key=lambda s: (s.owner, s.key))
            )
            # Artifact identity/generation survives process restart. Invocation-only
            # admission numbers are provenance, not persisted compatibility pins.
            fingerprint = digest(
                {
                    "modules": [m.model_dump(exclude={"admission_generation"}) for m in modules],
                    "declarations": [d.model_dump() for d in declarations],
                    "schema_generation": fence["schema_generation"],
                    "ui_generation": fence["ui_generation"],
                }
            )
            yield _Snapshot(
                composition,
                fingerprint,
                modules,
                declarations,
                fence["schema_generation"],
                fence["ui_generation"],
            )
    except NotFoundError:
        raise UIConflict(Code.INCOMPATIBLE) from None
    except (ValidationError, ValueError, KeyError):
        raise UIConflict(Code.INVALID_DOCUMENT) from None


def _record(row: RowMapping, snapshot: _Snapshot) -> UIOverlayRecord:
    # SQLAlchemy row mappings are dynamically typed at the private persistence boundary.
    return UIOverlayRecord(
        overlay_id=row["id"],
        view_id=row["view_id"],
        scope_kind=row["scope_kind"],
        lifecycle=row["lifecycle"],
        draft_generation=row["draft_generation"],
        active_generation=row["active_generation"],
        active_revision_id=row["active_revision_id"],
        draft_document=UIOverlayDocument.model_validate(row["draft_document"]),
        draft_compatibility_digest=row["draft_compatibility_digest"],
        current_compatibility_digest=snapshot.compatibility_digest,
    )


class PublishedUIRuntime:
    version = "1.0"

    async def resolve(self, view_id: UUID, locale: str, ctx: HandlingContext) -> UIResolution:
        principal = await _guard(ctx, HandlerInvocationKind.QUERY)
        await _policy(ctx, ("foundation.metadata.ui.read",))
        request = ctx.request
        try:
            async with _snapshot(ctx, view_id) as snapshot:
                await _view_fence(ctx, view_id, shared=True)
                assert request.tenant is not None
                eligible = [
                    (kind.value, _scope(ctx, kind, principal))
                    for kind in UIOverlayScope
                    if kind is UIOverlayScope.TENANT
                    or (
                        kind is UIOverlayScope.COMPANY
                        and request.tenant.active_company_id is not None
                    )
                    or (
                        kind is UIOverlayScope.SITE and request.tenant.operating_site_id is not None
                    )
                    or (
                        kind is UIOverlayScope.USER and principal.principal.principal_type == "user"
                    )
                ]
                rows = (
                    (
                        await ctx.unit_of_work.persistence.execute(
                            select(UI_OVERLAYS)
                            .where(
                                UI_OVERLAYS.c.tenant_id == request.tenant.tenant_id,
                                UI_OVERLAYS.c.view_id == view_id,
                                UI_OVERLAYS.c.lifecycle == "published",
                                or_(
                                    *(
                                        and_(
                                            UI_OVERLAYS.c.scope_kind == kind,
                                            UI_OVERLAYS.c.scope_id == scope_id,
                                        )
                                        for kind, scope_id in eligible
                                    )
                                ),
                            )
                            .order_by(UI_OVERLAYS.c.id)
                            .limit(5)
                            .with_for_update(read=True)
                        )
                    )
                    .mappings()
                    .all()
                )
                if len(rows) > 4 or len({r["scope_kind"] for r in rows}) != len(rows):
                    raise UIConflict(Code.STABLE_ID_CONFLICT)
                by_scope = {r["scope_kind"]: r for r in rows}
                view = snapshot.composition.view
                provenance: list[UIOverlayProvenance] = []
                for kind in UIOverlayScope:  # explicit tenant -> company -> site -> user precedence
                    row = by_scope.get(kind.value)
                    if row is None:
                        continue
                    revision = (
                        (
                            await ctx.unit_of_work.persistence.execute(
                                select(UI_REVISIONS).where(
                                    UI_REVISIONS.c.tenant_id == request.tenant.tenant_id,
                                    UI_REVISIONS.c.overlay_id == row["id"],
                                    UI_REVISIONS.c.id == row["active_revision_id"],
                                )
                            )
                        )
                        .mappings()
                        .one()
                    )
                    if (
                        revision["compatibility_digest"] != snapshot.compatibility_digest
                        or digest(revision["document"]) != revision["digest"]
                    ):
                        raise UIConflict(Code.STALE_OVERLAY)
                    document = UIOverlayDocument.model_validate(revision["document"])
                    view = apply_overlay(view, document, kind)
                    provenance.append(
                        UIOverlayProvenance(
                            overlay_id=row["id"],
                            revision_id=revision["id"],
                            active_generation=row["active_generation"],
                            scope_kind=kind,
                            digest=revision["digest"],
                        )
                    )
                translations = snapshot.composition.localized(locale)
                presentations = [
                    (view.view_id, view.presentation),
                    *((n.node_id, n.presentation) for n in view.nodes),
                ]
                result = ResolvedUISchema(
                    view=view,
                    capabilities=snapshot.composition.capabilities,
                    labels=tuple(
                        ResolvedUILabel(
                            target_id=identity,
                            label_key=p.label_key,
                            text=translations.get(p.label_key),
                            help_key=p.help_key,
                            help_text=translations.get(p.help_key) if p.help_key else None,
                        )
                        for identity, p in presentations
                    ),
                    provenance=UIResolutionProvenance(
                        base_revision_id=view.revision_id,
                        compatibility_digest=snapshot.compatibility_digest,
                        schema_generation=snapshot.schema_generation,
                        ui_generation=snapshot.ui_generation,
                        modules=snapshot.modules,
                        declarations=snapshot.declarations,
                        overlays=tuple(provenance),
                        locale=locale,
                    ),
                )
                if len(result.model_dump_json().encode("utf-8")) > 131072:
                    raise UIConflict(Code.LIMIT_EXCEEDED)
                await _policy(
                    ctx, ("foundation.metadata.ui.read", *snapshot.composition.permissions)
                )
                if (
                    ctx.request is not request
                    or await _guard(ctx, HandlerInvocationKind.QUERY) is not principal
                ):
                    raise UIConflict(Code.STALE_CONTEXT)
                response = UIResolution(resolved=result)
            return response
        except UIConflict as error:
            return UIResolution(diagnostics=(UIDiagnostic(code=error.code),))
        except (ValidationError, ValueError):
            return UIResolution(diagnostics=(UIDiagnostic(code=Code.INVALID_DOCUMENT),))

    async def create(
        self,
        view_id: UUID,
        scope: UIOverlayScope,
        document: UIOverlayDocument,
        ctx: HandlingContext,
    ) -> UIOverlayRecord:
        principal = await _guard(ctx, HandlerInvocationKind.COMMAND)
        await _policy(ctx, ("foundation.metadata.ui.draft",))
        scope_id = _scope(ctx, scope, principal)
        assert ctx.request.tenant is not None
        async with _snapshot(ctx, view_id) as snapshot:
            apply_overlay(snapshot.composition.view, document, scope)
            session = ctx.unit_of_work.persistence
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended('ui-quota:' || :tenant,0))"),
                {"tenant": str(ctx.request.tenant.tenant_id)},
            )
            await _view_fence(ctx, view_id, shared=False)
            count = (
                await session.execute(
                    select(func.count())
                    .select_from(UI_OVERLAYS)
                    .where(UI_OVERLAYS.c.tenant_id == ctx.request.tenant.tenant_id)
                )
            ).scalar_one()
            if count >= 1024:
                raise UIConflict(Code.LIMIT_EXCEEDED)
            existing = (
                await session.execute(
                    select(UI_OVERLAYS.c.id).where(
                        UI_OVERLAYS.c.tenant_id == ctx.request.tenant.tenant_id,
                        UI_OVERLAYS.c.view_id == view_id,
                        UI_OVERLAYS.c.scope_kind == scope.value,
                        UI_OVERLAYS.c.scope_id == scope_id,
                    )
                )
            ).first()
            if existing is not None:
                raise UIConflict(Code.STABLE_ID_CONFLICT)
            row = (
                (
                    await session.execute(
                        insert(UI_OVERLAYS)
                        .values(
                            id=uuid4(),
                            tenant_id=ctx.request.tenant.tenant_id,
                            view_id=view_id,
                            scope_kind=scope.value,
                            scope_id=scope_id,
                            lifecycle="draft",
                            draft_generation=1,
                            draft_document=document.model_dump(mode="json"),
                            draft_compatibility_digest=snapshot.compatibility_digest,
                            active_generation=0,
                            created_by=ctx.request.tenant.principal_id,
                        )
                        .returning(UI_OVERLAYS)
                    )
                )
                .mappings()
                .one()
            )
            await _policy(ctx, ("foundation.metadata.ui.draft", *snapshot.composition.permissions))
            if await _guard(ctx, HandlerInvocationKind.COMMAND) is not principal:
                raise UIConflict(Code.STALE_CONTEXT)
            return _record(row, snapshot)

    async def _row(
        self,
        overlay_id: UUID,
        ctx: HandlingContext,
        principal: AuthenticatedPrincipalBinding,
        *,
        lock: bool = False,
    ) -> RowMapping:
        assert ctx.request.tenant is not None
        statement = select(UI_OVERLAYS).where(
            UI_OVERLAYS.c.tenant_id == ctx.request.tenant.tenant_id, UI_OVERLAYS.c.id == overlay_id
        )
        if lock:
            statement = statement.with_for_update()
        row = (await ctx.unit_of_work.persistence.execute(statement)).mappings().one_or_none()
        if (
            row is None
            or _scope(ctx, UIOverlayScope(row["scope_kind"]), principal) != row["scope_id"]
        ):
            raise BusinessOSError(
                "ui_overlay_unavailable", "Eligible overlay unavailable", status_code=404
            )
        return row

    async def read(self, overlay_id: UUID, ctx: HandlingContext) -> UIOverlayRecord:
        principal = await _guard(ctx, HandlerInvocationKind.QUERY)
        await _policy(ctx, ("foundation.metadata.ui.draft",))
        row = await self._row(overlay_id, ctx, principal)
        async with _snapshot(ctx, row["view_id"]) as snapshot:
            await _view_fence(ctx, row["view_id"], shared=True)
            row = await self._row(overlay_id, ctx, principal)
            await _policy(ctx, ("foundation.metadata.ui.draft", *snapshot.composition.permissions))
            if await _guard(ctx, HandlerInvocationKind.QUERY) is not principal:
                raise UIConflict(Code.STALE_CONTEXT)
            return _record(row, snapshot)

    async def mutate(
        self,
        overlay_id: UUID,
        expected_draft: int,
        expected_active: int,
        ctx: HandlingContext,
        *,
        document: UIOverlayDocument | None = None,
        revision_id: UUID | None = None,
        retire: bool = False,
    ) -> UIOverlayRecord:
        principal = await _guard(ctx, HandlerInvocationKind.COMMAND)
        permission = (
            "draft"
            if document is not None
            else "retire"
            if retire
            else "rollback"
            if revision_id
            else "publish"
        )
        await _policy(ctx, ("foundation.metadata.ui." + permission,))
        initial = await self._row(overlay_id, ctx, principal)
        async with _snapshot(ctx, initial["view_id"]) as snapshot:
            await _view_fence(ctx, initial["view_id"], shared=False)
            row = await self._row(overlay_id, ctx, principal, lock=True)
            if (
                row["draft_generation"] != expected_draft
                or row["active_generation"] != expected_active
                or row["lifecycle"] == "retired"
            ):
                raise UIConflict(Code.STALE_OVERLAY)
            session = ctx.unit_of_work.persistence
            if document is not None:
                apply_overlay(
                    snapshot.composition.view, document, UIOverlayScope(row["scope_kind"])
                )
                values = dict(
                    draft_document=document.model_dump(mode="json"),
                    draft_compatibility_digest=snapshot.compatibility_digest,
                    draft_generation=expected_draft + 1,
                )
                # An identical edit does not invent a generation or alter active publication.
                if (
                    row["draft_document"] == values["draft_document"]
                    and row["draft_compatibility_digest"] == snapshot.compatibility_digest
                ):
                    await _policy(
                        ctx,
                        ("foundation.metadata.ui." + permission, *snapshot.composition.permissions),
                    )
                    if await _guard(ctx, HandlerInvocationKind.COMMAND) is not principal:
                        raise UIConflict(Code.STALE_CONTEXT)
                    return _record(row, snapshot)
            elif retire:
                values = dict(
                    lifecycle="retired",
                    active_revision_id=None,
                    active_generation=expected_active + 1,
                )
            else:
                if revision_id is not None:
                    revision = (
                        (
                            await session.execute(
                                select(UI_REVISIONS).where(
                                    UI_REVISIONS.c.tenant_id == row["tenant_id"],
                                    UI_REVISIONS.c.overlay_id == overlay_id,
                                    UI_REVISIONS.c.id == revision_id,
                                )
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if revision is None:
                        raise UIConflict(Code.STALE_OVERLAY)
                    raw = revision["document"]
                    compatibility = revision["compatibility_digest"]
                    if digest(raw) != revision["digest"]:
                        raise UIConflict(Code.STALE_OVERLAY)
                else:
                    raw = row["draft_document"]
                    compatibility = row["draft_compatibility_digest"]
                if compatibility != snapshot.compatibility_digest:
                    raise UIConflict(Code.STALE_OVERLAY)
                patch = UIOverlayDocument.model_validate(raw)
                apply_overlay(snapshot.composition.view, patch, UIOverlayScope(row["scope_kind"]))
                if revision_id is None:
                    count = (
                        await session.execute(
                            select(func.count())
                            .select_from(UI_REVISIONS)
                            .where(
                                UI_REVISIONS.c.tenant_id == row["tenant_id"],
                                UI_REVISIONS.c.overlay_id == overlay_id,
                            )
                        )
                    ).scalar_one()
                    if count >= 64:
                        raise UIConflict(Code.LIMIT_EXCEEDED)
                    revision_id = uuid4()
                    await session.execute(
                        insert(UI_REVISIONS).values(
                            id=revision_id,
                            tenant_id=row["tenant_id"],
                            overlay_id=overlay_id,
                            sequence=count + 1,
                            document=raw,
                            digest=digest(raw),
                            compatibility_digest=compatibility,
                            published_by=principal.principal.principal_id,
                        )
                    )
                values = dict(
                    lifecycle="published",
                    active_revision_id=revision_id,
                    active_generation=expected_active + 1,
                )
            updated = (
                (
                    await session.execute(
                        update(UI_OVERLAYS)
                        .where(
                            UI_OVERLAYS.c.id == overlay_id,
                            UI_OVERLAYS.c.tenant_id == row["tenant_id"],
                        )
                        .values(**values)
                        .returning(UI_OVERLAYS)
                    )
                )
                .mappings()
                .one()
            )
            await _policy(
                ctx, ("foundation.metadata.ui." + permission, *snapshot.composition.permissions)
            )
            if await _guard(ctx, HandlerInvocationKind.COMMAND) is not principal:
                raise UIConflict(Code.STALE_CONTEXT)
            return _record(updated, snapshot)
