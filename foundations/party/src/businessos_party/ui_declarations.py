"""Owner-published inert Party UI v1 declarations using the existing SDK surface.

No dependency on Metadata, renderer, data query or authorization implementation.
The read capability endorses public PartyRecord bindings, never sensitive profiles.
"""

from uuid import NAMESPACE_URL, UUID, uuid5

from businessos.sdk import MetadataDeclaration


def ui_id(name: str) -> UUID:
    return uuid5(NAMESPACE_URL, "businessos.ui.foundation.party." + name)


def published_ui_declarations() -> tuple[MetadataDeclaration, ...]:
    view = str(ui_id("detail.v1"))
    revision = str(ui_id("detail.revision.1"))
    section = str(ui_id("detail.summary"))
    field = str(ui_id("field.display_name"))
    common: dict[str, object] = {"contract_version": "1.0", "view_id": view}
    base = {
        **common,
        "revision_id": revision,
        "resource_namespace": "foundation.party.party",
        "owner_contract_version": "1",
        "permission": "foundation.party.read",
        "presentation": {"label_key": "party.detail.title"},
        "nodes": [
            {
                "node_id": section,
                "parent_id": view,
                "kind": "section",
                "primitive": "FormSection",
                "presentation": {"label_key": "party.detail.summary", "order": 0},
            },
            {
                "node_id": str(ui_id("detail.display_name")),
                "parent_id": section,
                "kind": "field",
                "primitive": "TextInput",
                "field_id": field,
                "presentation": {"label_key": "party.field.display_name", "order": 1},
            },
            {
                "node_id": str(ui_id("detail.extension_slot")),
                "parent_id": section,
                "kind": "slot",
                "primitive": "Grid",
                "presentation": {"label_key": "party.detail.additional", "order": 2},
            },
        ],
    }
    caps = {
        **common,
        "resource_namespace": "foundation.party.party",
        "owner_contract_version": "1",
        "fields": [
            {
                "field_id": field,
                "binding": "display_name",
                "value_type": "text",
                "permission": "foundation.party.read",
                "classification_ref": None,
            },
            {
                "field_id": str(ui_id("field.preferred_locale")),
                "binding": "preferred_locale",
                "value_type": "text",
                "permission": "foundation.party.read",
                "classification_ref": None,
            },
        ],
        "actions": [],
        "extension_slots": [
            {
                "slot_id": str(ui_id("detail.extension_slot")),
                "primitives": ["Card", "FormSection", "Grid"],
            },
        ],
        "customization": [
            {
                "target_id": view,
                "scopes": ["tenant", "company", "site", "user"],
                "properties": ["order", "density", "label_key"],
            },
        ],
    }
    values = [
        MetadataDeclaration(key="foundation.party.ui.detail.base", kind="ui.base.v1", value=base),
        MetadataDeclaration(
            key="foundation.party.ui.detail.capabilities", kind="ui.capabilities.v1", value=caps
        ),
    ]
    for locale, labels in (
        ("en", ("Party", "Summary", "Display name", "Additional information")),
        ("ar", ("جهة", "ملخص", "الاسم المعروض", "معلومات إضافية")),
        ("es", ("Contacto", "Resumen", "Nombre visible", "Información adicional")),
    ):
        values.append(
            MetadataDeclaration(
                key="foundation.party.ui.detail.localization." + locale,
                kind="ui.localization.v1",
                value={
                    **common,
                    "contribution_id": str(ui_id("locale." + locale)),
                    "base_revision_id": revision,
                    "base_version": ">=0.3,<1",
                    "locale": locale,
                    "translations": [
                        {"key": key, "text": label}
                        for key, label in zip(
                            (
                                "party.detail.title",
                                "party.detail.summary",
                                "party.field.display_name",
                                "party.detail.additional",
                            ),
                            labels,
                            strict=True,
                        )
                    ],
                },
            )
        )
    return tuple(values)
