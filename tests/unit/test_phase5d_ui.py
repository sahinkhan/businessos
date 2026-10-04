"""Adversarial presentation grammar, deterministic composition and SDK admission."""

import asyncio
import json
from dataclasses import replace
from itertools import permutations
from typing import Any, cast
from uuid import uuid4

import pytest
from businessos_metadata.module import CreateUIOverlay, ResolvePublishedUI
from businessos_metadata.ui_composition import apply_overlay, compose
from businessos_metadata.ui_contracts import (
    UIConflict,
    UIDiagnosticCode,
    UIOverlayDocument,
    UIOverlayScope,
    UITranslation,
    canonical_json,
)
from businessos_metadata.ui_runtime import PublishedUIRuntime
from businessos_party.ui_declarations import published_ui_declarations, ui_id
from pydantic import ValidationError

from businessos.activation import ContributionGate, ContributionGeneration
from businessos.metadata import (
    AdmittedMetadataDeclaration,
    MetadataCatalog,
    MetadataDeclaration,
    MetadataRegistry,
)
from businessos.sdk import (
    BusinessOSError,
    HandlerTransaction,
    HandlingContext,
    RequestContext,
    RequestDependencyScope,
)


def sources() -> tuple[AdmittedMetadataDeclaration, ...]:
    return tuple(
        AdmittedMetadataDeclaration(
            d.key,
            d.kind,
            1,
            "foundation.party",
            ContributionGeneration("foundation.party", 1),
            "0.4.0",
            (),
            canonical_json(d.value),
        )
        for d in published_ui_declarations()
    )


def extension(*, node_id: object | None = None, **changes: object) -> AdmittedMetadataDeclaration:
    base = sources()[0]
    document: dict[str, Any] = {
        "contract_version": "1.0",
        "view_id": str(ui_id("detail.v1")),
        "contribution_id": str(uuid4()),
        "base_revision_id": str(ui_id("detail.revision.1")),
        "base_version": ">=0.4,<1",
        "priority": 0,
        "nodes": [
            {
                "node_id": str(node_id or uuid4()),
                "parent_id": str(ui_id("detail.extension_slot")),
                "kind": "section",
                "primitive": "Card",
                "presentation": {"label_key": "extension.title"},
            }
        ],
        **changes,
    }
    return replace(
        base,
        key="example.partner.ui.extension",
        kind="ui.extension.v1",
        owner="example.partner",
        generation=ContributionGeneration("example.partner", 1),
        module_version="0.1.0",
        dependencies=(("foundation.party", ">=0.4,<1"),),
        document_json=canonical_json(document),
    )


def test_deterministic_registration_independent_base_and_extension_composition() -> None:
    declarations = (*sources()[:2], extension(), extension(priority=1))
    expected = canonical_json(compose(declarations).view)
    for order in permutations(declarations):
        assert canonical_json(compose(order).view) == expected


def test_localization_precedes_overlays_without_mutating_authority_or_translation_catalog() -> None:
    result = compose(sources())
    assert result.localized("ar")["party.detail.title"] == "جهة"
    assert result.localized("es")["party.detail.title"] == "Contacto"
    assert result.localized("fr") == {}
    original = canonical_json(result.view)
    view = result.view
    for kind, order in zip(UIOverlayScope, (11, 22, 33, 44), strict=True):
        view = apply_overlay(
            view,
            UIOverlayDocument.model_validate(
                {
                    "patches": [{"target_id": str(view.view_id), "order": order}],
                }
            ),
            kind,
        )
        assert view.presentation.order == order
    assert view.resource_namespace == result.view.resource_namespace
    assert view.permission == result.view.permission
    assert canonical_json(result.view) == original


@pytest.mark.parametrize(
    "name",
    [
        "tenant_id",
        "scope_id",
        "company_id",
        "resource_namespace",
        "owner",
        "permission",
        "classification_ref",
        "field_id",
        "action_id",
        "primitive",
        "binding",
        "readonly",
        "required",
        "lifecycle",
        "capabilities",
        "security",
        "audit",
        "url",
        "script",
        "method",
        "css",
    ],
)
def test_overlay_protected_properties_have_no_wire_surface(name: str) -> None:
    with pytest.raises(ValidationError):
        UIOverlayDocument.model_validate(
            {"patches": [{"target_id": str(uuid4()), name: "forged", "order": 1}]}
        )


@pytest.mark.parametrize(
    "extra", ["tenant_id", "principal_id", "active_company_id", "operating_site_id", "permission"]
)
def test_query_and_overlay_create_cannot_accept_browser_authority(extra: str) -> None:
    with pytest.raises(ValidationError):
        ResolvePublishedUI.model_validate(
            {"view_id": str(uuid4()), "locale": "en", extra: str(uuid4())}
        )
    with pytest.raises(ValidationError):
        CreateUIOverlay.model_validate(
            {
                "view_id": str(uuid4()),
                "scope_kind": "tenant",
                "document": {"patches": []},
                extra: str(uuid4()),
            }
        )


@pytest.mark.parametrize(
    "text",
    [
        "<script>alert(1)</script>",
        "javascript:alert(1)",
        "https://evil.test",
        "DROP TABLE users",
        "SELECT secret FROM users",
        "exec('python')",
        "${expression}",
        "foo\nbar",
    ],
)
def test_localization_is_inert_bounded_text(text: str) -> None:
    with pytest.raises(ValidationError):
        UITranslation(key="label.key", text=text)


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"contract_version": "99"}, UIDiagnosticCode.UNSUPPORTED_SCHEMA),
        ({"base_revision_id": str(uuid4())}, UIDiagnosticCode.INCOMPATIBLE),
        ({"base_version": ">=9"}, UIDiagnosticCode.INCOMPATIBLE),
        ({"script": "alert(1)"}, UIDiagnosticCode.INVALID_DOCUMENT),
    ],
)
def test_extension_incompatibility_is_typed(
    changes: dict[str, object], code: UIDiagnosticCode
) -> None:
    with pytest.raises(UIConflict) as error:
        compose((*sources(), extension(**changes)))
    assert error.value.code is code


def test_unsupported_primitive_conflicting_slot_and_foreign_capability_rejected() -> None:
    for primitive, node_id, field_id, code in (
        ("PrivateComponent", uuid4(), None, UIDiagnosticCode.UNSUPPORTED_PRIMITIVE),
        ("Card", ui_id("detail.extension_slot"), None, UIDiagnosticCode.STABLE_ID_CONFLICT),
        ("TextInput", uuid4(), uuid4(), UIDiagnosticCode.CAPABILITY_UNAVAILABLE),
    ):
        source = extension(node_id=node_id)
        document = json.loads(source.document_json)
        document["nodes"][0]["primitive"] = primitive
        if field_id:
            document["nodes"][0].update(kind="field", field_id=str(field_id))
        with pytest.raises(UIConflict) as error:
            compose((*sources(), replace(source, document_json=canonical_json(document))))
        assert error.value.code is code


def test_owner_mismatch_missing_dependency_and_classification_refuse() -> None:
    original = sources()
    wrong_owner = replace(
        original[1],
        owner="example.partner",
        generation=ContributionGeneration("example.partner", 1),
    )
    with pytest.raises(UIConflict, match="capability_unavailable"):
        compose((original[0], wrong_owner))
    with pytest.raises(UIConflict, match="incompatible"):
        compose((*original, replace(extension(), dependencies=())))
    document = json.loads(original[1].document_json)
    document["fields"][0]["classification_ref"] = "unknown-sensitive-classification"
    with pytest.raises(UIConflict, match="classification_unavailable"):
        compose((original[0], replace(original[1], document_json=canonical_json(document))))


def test_conflicting_localization_has_no_registration_order_winner() -> None:
    original = sources()
    document = json.loads(original[2].document_json)
    document["contribution_id"] = str(uuid4())
    document["translations"][0]["text"] = "Conflicting title"
    changed = replace(
        original[2], key="foundation.party.ui.conflict", document_json=canonical_json(document)
    )
    for order in ((*original, changed), (changed, *original)):
        with pytest.raises(UIConflict, match="localization_conflict"):
            compose(order)


def test_user_preferences_are_narrower_and_unknown_targets_and_budget_reject() -> None:
    view = compose(sources()).view
    with pytest.raises(UIConflict, match="invalid_document"):
        apply_overlay(
            view,
            UIOverlayDocument.model_validate(
                {"patches": [{"target_id": str(view.view_id), "label_key": "replacement.label"}]}
            ),
            UIOverlayScope.USER,
        )
    with pytest.raises(UIConflict, match="stable_id_conflict"):
        apply_overlay(
            view,
            UIOverlayDocument.model_validate(
                {"patches": [{"target_id": str(uuid4()), "order": 1}]}
            ),
            UIOverlayScope.TENANT,
        )
    with pytest.raises(ValidationError):
        UIOverlayDocument.model_validate(
            {"patches": [{"target_id": str(uuid4()), "order": 1} for _ in range(129)]}
        )
    with pytest.raises(ValidationError):
        UITranslation(key="label.key", text="x" * 241)


@pytest.mark.asyncio
async def test_sdk_catalog_rejects_changed_snapshot_and_is_read_only() -> None:
    gate = ContributionGate()
    registry = MetadataRegistry(gate)
    generation = gate.reserve("foundation.party")
    for declaration in published_ui_declarations():
        registry.add("foundation.party", declaration, generation=generation, module_version="0.4.0")
    catalog = MetadataCatalog(registry)
    assert not hasattr(catalog, "register") and not hasattr(catalog, "_registry")
    gate.publish(generation)
    with pytest.raises(ValueError, match="changed during admission"):
        async with catalog.admitted(
            kind_prefix="ui.", discriminator="view_id", value=str(ui_id("detail.v1"))
        ) as captured:
            assert gate.in_flight(generation) == 5
            assert captured[0].generation is generation
            registry.get("foundation.party.ui.detail.base").value["permission"] = (
                "forged.permission"
            )
    assert gate.in_flight(generation) == 0
    await gate.close_and_drain(generation, timeout_seconds=1)
    async with catalog.admitted(
        kind_prefix="ui.", discriminator="view_id", value=str(ui_id("detail.v1"))
    ) as captured:
        assert captured == ()


@pytest.mark.asyncio
async def test_dependency_drain_rejects_inflight_catalog_and_cancellation_releases_leases() -> None:
    gate = ContributionGate()
    registry = MetadataRegistry(gate)
    owner = gate.reserve("example.partner")
    dependency = gate.reserve("foundation.party")
    gate.publish(owner)
    gate.publish(dependency)
    declaration = MetadataDeclaration(
        key="example.partner.ui.extension", kind="ui.extension.v1", value={"view_id": "selected"}
    )
    registry.add(
        "example.partner",
        declaration,
        generation=owner,
        module_version="0.1.0",
        dependencies=(("foundation.party", ">=0.4,<1"),),
    )
    catalog = MetadataCatalog(registry)
    entered, release = asyncio.Event(), asyncio.Event()

    async def read() -> None:
        async with catalog.admitted(kind_prefix="ui.", discriminator="view_id", value="selected"):
            entered.set()
            await release.wait()

    task = asyncio.create_task(read())
    await entered.wait()
    draining = asyncio.create_task(gate.close_and_drain(dependency, timeout_seconds=2))
    await asyncio.sleep(0)  # schedule drain, not a time-based race
    release.set()
    with pytest.raises(ValueError, match="dependency changed"):
        await task
    await draining
    assert gate.in_flight(owner) == gate.in_flight(dependency) == 0
    gate.publish(dependency)
    release.clear()
    entered.clear()
    task = asyncio.create_task(read())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert gate.in_flight(owner) == gate.in_flight(dependency) == 0


def test_missing_classification_is_unknown_and_topology_is_bounded() -> None:
    original = sources()
    caps = json.loads(original[1].document_json)
    del caps["fields"][0]["classification_ref"]
    with pytest.raises(UIConflict, match="invalid_document"):
        compose((original[0], replace(original[1], document_json=canonical_json(caps))))
    for cyclic in (False, True):
        view = json.loads(original[0].document_json)
        nodes = []
        parent = str(ui_id("detail.v1"))
        for _ in range(5):
            identity = str(uuid4())
            nodes.append(
                {
                    "node_id": identity,
                    "parent_id": parent,
                    "kind": "section",
                    "primitive": "Card",
                    "presentation": {"label_key": "label.key"},
                }
            )
            parent = identity
        if cyclic:
            nodes[0]["parent_id"] = nodes[-1]["node_id"]
        view["nodes"] = nodes
        with pytest.raises(UIConflict, match="invalid_document"):
            compose((replace(original[0], document_json=canonical_json(view)), original[1]))


@pytest.mark.asyncio
async def test_public_resolver_handle_has_no_authority_without_framework_invocation() -> None:
    context = HandlingContext(
        request=RequestContext(),
        dependencies=cast(RequestDependencyScope, None),
        unit_of_work=cast(HandlerTransaction, None),
    )
    with pytest.raises(BusinessOSError) as failure:
        await PublishedUIRuntime().resolve(ui_id("detail.v1"), "en", context)
    assert failure.value.code == "ui_invocation_required"
