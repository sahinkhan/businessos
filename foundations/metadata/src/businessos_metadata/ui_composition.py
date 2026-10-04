"""Pure deterministic composition of admitted owner declarations and presentation patches."""

import json
from dataclasses import dataclass
from typing import cast

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import Version
from pydantic import BaseModel, ValidationError

from businessos.sdk import AdmittedMetadataDeclaration

from .ui_contracts import (
    UIConflict,
    UIExtension,
    UILocalization,
    UINode,
    UIOverlayDocument,
    UIOverlayScope,
    UIOwnerCapabilities,
    UIPresentation,
    UIPrimitive,
    UITranslation,
    UIViewSchema,
    validate_nodes,
)
from .ui_contracts import (
    UIDiagnosticCode as Code,
)


@dataclass(frozen=True, slots=True)
class UIComposition:
    view: UIViewSchema
    capabilities: UIOwnerCapabilities
    base_source: AdmittedMetadataDeclaration
    translations: tuple[tuple[str, tuple[UITranslation, ...]], ...]

    @property
    def permissions(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    self.view.permission,
                    *(f.permission for f in self.capabilities.fields),
                    *(a.permission for a in self.capabilities.actions),
                }
            )
        )

    def localized(self, locale: str) -> dict[str, str]:
        return {
            x.key: x.text
            for language, values in self.translations
            if language == locale
            for x in values
        }


def _parse[T: BaseModel](source: AdmittedMetadataDeclaration, contract: type[T]) -> T:
    raw: object = json.loads(source.document_json)
    if not isinstance(raw, dict):
        raise UIConflict(Code.INVALID_DOCUMENT)
    document = cast(dict[str, object], raw)
    if source.version != 1 or document.get("contract_version", "1.0") != "1.0":
        raise UIConflict(Code.UNSUPPORTED_SCHEMA)
    nodes = document.get("nodes", ())
    if isinstance(nodes, list):
        for node in cast(list[object], nodes):
            if isinstance(node, dict) and cast(dict[str, object], node).get("primitive") not in set(
                UIPrimitive
            ):
                raise UIConflict(Code.UNSUPPORTED_PRIMITIVE)
    try:
        return contract.model_validate(document)
    except ValidationError:
        raise UIConflict(Code.INVALID_DOCUMENT) from None


def compose(sources: tuple[AdmittedMetadataDeclaration, ...]) -> UIComposition:
    if not sources:
        raise UIConflict(Code.BASE_UNAVAILABLE)
    if len(sources) > 128:
        raise UIConflict(Code.LIMIT_EXCEEDED)
    if any(not s.module_version or s.generation.owner != s.owner for s in sources):
        raise UIConflict(Code.INCOMPATIBLE)
    bases = [s for s in sources if s.kind == "ui.base.v1"]
    capabilities = [s for s in sources if s.kind == "ui.capabilities.v1"]
    if len(bases) != 1 or len(capabilities) != 1:
        raise UIConflict(Code.STABLE_ID_CONFLICT if bases else Code.BASE_UNAVAILABLE)
    base_source, capability_source = bases[0], capabilities[0]
    if (base_source.owner, base_source.generation) != (
        capability_source.owner,
        capability_source.generation,
    ):
        raise UIConflict(Code.CAPABILITY_UNAVAILABLE)
    view = _parse(base_source, UIViewSchema)
    caps = _parse(capability_source, UIOwnerCapabilities)
    if (view.view_id, view.resource_namespace, view.owner_contract_version) != (
        caps.view_id,
        caps.resource_namespace,
        caps.owner_contract_version,
    ) or not view.resource_namespace.startswith(base_source.owner + "."):
        raise UIConflict(Code.CAPABILITY_UNAVAILABLE)
    if any(f.classification_ref is not None for f in caps.fields):
        # Classification identity/control resolution alone is not a disclosure grant.
        # No certified UI classification-disclosure projection exists: refuse, never downgrade.
        raise UIConflict(Code.CLASSIFICATION_UNAVAILABLE)
    if any(
        not permission.startswith(base_source.owner + ".")
        for permission in (
            view.permission,
            *(x.permission for x in caps.fields),
            *(x.permission for x in caps.actions),
        )
    ):
        raise UIConflict(Code.CAPABILITY_UNAVAILABLE)
    extensions: list[tuple[AdmittedMetadataDeclaration, UIExtension]] = []
    localizations: list[tuple[AdmittedMetadataDeclaration, UILocalization]] = []
    for source in sorted(sources, key=lambda s: (s.owner, s.key)):
        if source.kind in {"ui.base.v1", "ui.capabilities.v1"}:
            continue
        item: UIExtension | UILocalization
        if source.kind == "ui.extension.v1":
            item = _parse(source, UIExtension)
            extensions.append((source, item))
        elif source.kind == "ui.localization.v1":
            item = _parse(source, UILocalization)
            localizations.append((source, item))
        else:
            raise UIConflict(Code.UNSUPPORTED_SCHEMA)
        dependencies = dict(source.dependencies)
        try:
            if (
                item.view_id != view.view_id
                or item.base_revision_id != view.revision_id
                or Version(base_source.module_version) not in SpecifierSet(item.base_version)
                or (
                    source.owner != base_source.owner
                    and (
                        base_source.owner not in dependencies
                        or Version(base_source.module_version)
                        not in SpecifierSet(dependencies[base_source.owner])
                    )
                )
            ):
                raise UIConflict(Code.INCOMPATIBLE)
        except (InvalidSpecifier, ValueError):
            raise UIConflict(Code.INCOMPATIBLE) from None
    contribution_ids = [x.contribution_id for _, x in extensions] + [
        x.contribution_id for _, x in localizations
    ]
    if len(set(contribution_ids)) != len(contribution_ids):
        raise UIConflict(Code.STABLE_ID_CONFLICT)
    base_nodes = {n.node_id: n for n in view.nodes}
    slots = {x.slot_id: x for x in caps.extension_slots}
    if any(identity not in base_nodes or base_nodes[identity].kind != "slot" for identity in slots):
        raise UIConflict(Code.CAPABILITY_UNAVAILABLE)
    if any(x.target_id not in {view.view_id, *base_nodes} for x in caps.customization):
        raise UIConflict(Code.CAPABILITY_UNAVAILABLE)
    nodes = list(view.nodes)
    for source, extension in sorted(
        extensions, key=lambda pair: (pair[1].priority, pair[0].owner, str(pair[1].contribution_id))
    ):
        own_nodes = {n.node_id: n for n in extension.nodes}
        if source.owner != base_source.owner:
            for node in extension.nodes:
                ancestor = node
                visited = {node.node_id}
                while ancestor.parent_id in own_nodes:
                    if ancestor.parent_id in visited:
                        raise UIConflict(Code.STABLE_ID_CONFLICT)
                    visited.add(ancestor.parent_id)
                    ancestor = own_nodes[ancestor.parent_id]
                slot = slots.get(ancestor.parent_id)
                if slot is None or node.primitive not in slot.primitives:
                    raise UIConflict(Code.CAPABILITY_UNAVAILABLE)
        nodes.extend(extension.nodes)
    if len(nodes) > 256:
        raise UIConflict(Code.LIMIT_EXCEEDED)
    try:
        validate_nodes(view.view_id, tuple(nodes))
    except ValueError:
        raise UIConflict(Code.STABLE_ID_CONFLICT) from None
    fields = {x.field_id: x for x in caps.fields}
    actions = {x.action_id: x for x in caps.actions}
    primitives = {
        "text": {UIPrimitive.TEXT, UIPrimitive.TEXT_AREA},
        "integer": {UIPrimitive.NUMBER},
        "decimal": {UIPrimitive.NUMBER},
        "money": {UIPrimitive.MONEY},
        "date": {UIPrimitive.DATE},
        "instant": {UIPrimitive.INSTANT},
        "boolean": {UIPrimitive.CHECKBOX},
        "enum": {UIPrimitive.SELECT},
    }
    for node in nodes:
        if node.field_id is not None:
            field = fields.get(node.field_id)
            if field is None or node.primitive not in primitives[field.value_type]:
                raise UIConflict(Code.CAPABILITY_UNAVAILABLE)
        if node.action_id is not None and node.action_id not in actions:
            raise UIConflict(Code.CAPABILITY_UNAVAILABLE)
    translations: dict[str, dict[str, str]] = {}
    for _source, localization in sorted(
        localizations,
        key=lambda pair: (pair[1].locale, pair[0].owner, str(pair[1].contribution_id)),
    ):
        values = translations.setdefault(localization.locale, {})
        for translation in sorted(localization.translations, key=lambda x: x.key):
            if translation.key in values and values[translation.key] != translation.text:
                raise UIConflict(Code.LOCALIZATION_CONFLICT)
            values[translation.key] = translation.text
    if sum(len(values) for values in translations.values()) > 512:
        raise UIConflict(Code.LIMIT_EXCEEDED)
    return UIComposition(
        view.model_copy(update={"nodes": _ordered(tuple(nodes))}),
        caps,
        base_source,
        tuple(
            (
                locale,
                tuple(UITranslation(key=key, text=text) for key, text in sorted(values.items())),
            )
            for locale, values in sorted(translations.items())
        ),
    )


def _ordered(nodes: tuple[UINode, ...]) -> tuple[UINode, ...]:
    return tuple(sorted(nodes, key=lambda n: (n.presentation.order, str(n.node_id))))


def apply_overlay(
    view: UIViewSchema,
    document: UIOverlayDocument,
    scope: UIOverlayScope,
    capabilities: UIOwnerCapabilities | None = None,
) -> UIViewSchema:
    presentations = {
        view.view_id: view.presentation,
        **{x.node_id: x.presentation for x in view.nodes},
    }
    for patch in sorted(document.patches, key=lambda x: str(x.target_id)):
        current = presentations.get(patch.target_id)
        if current is None:
            raise UIConflict(Code.STABLE_ID_CONFLICT)
        properties = patch.properties()
        opt_in = (
            next(
                (x for x in capabilities.customization if x.target_id == patch.target_id),
                None,
            )
            if capabilities is not None
            else None
        )
        if (
            opt_in is None
            or scope.value not in opt_in.scopes
            or set(properties) - set(opt_in.properties)
        ):
            raise UIConflict(Code.CAPABILITY_UNAVAILABLE)
        if scope is UIOverlayScope.USER and set(properties) - {"visible", "density", "order"}:
            raise UIConflict(Code.INVALID_DOCUMENT)
        presentations[patch.target_id] = UIPresentation.model_validate(
            {
                **current.model_dump(),
                **properties,
            }
        )
    return view.model_copy(
        update={
            "presentation": presentations[view.view_id],
            "nodes": _ordered(
                tuple(
                    x.model_copy(update={"presentation": presentations[x.node_id]})
                    for x in view.nodes
                )
            ),
        }
    )
