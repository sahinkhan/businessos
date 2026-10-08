"""Published UI v1 values. Presentation metadata has no operation authority."""

from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator

Key = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.-]{1,119}$")]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Locale = Annotated[str, Field(pattern=r"^[a-z]{2,3}(?:-[A-Z]{2})?$")]


class _Value(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class UIPrimitive(StrEnum):
    """Existing Phase 4.5 controls only; no renderer, executable payload or URL."""

    FORM_SECTION = "FormSection"
    CARD = "Card"
    GRID = "Grid"
    TEXT = "TextInput"
    TEXT_AREA = "TextArea"
    NUMBER = "NumberInput"
    MONEY = "MoneyInput"
    DATE = "DateInput"
    INSTANT = "DateTimeInput"
    SELECT = "Select"
    CHECKBOX = "Checkbox"
    BUTTON = "Button"


class UIPresentation(_Value):
    label_key: Key
    help_key: Key | None = None
    order: StrictInt = Field(default=0, ge=0, le=10000)
    visible: StrictBool = True
    density: Literal["comfortable", "compact"] = "comfortable"
    columns: StrictInt = Field(default=1, ge=1, le=4)


class UIPresentationPatch(_Value):
    """Explicit allowlist; security, bindings, capabilities and IDs cannot be patched."""

    target_id: UUID
    label_key: Key | None = None
    help_key: Key | None = None
    order: StrictInt | None = Field(default=None, ge=0, le=10000)
    visible: StrictBool | None = None
    density: Literal["comfortable", "compact"] | None = None
    columns: StrictInt | None = Field(default=None, ge=1, le=4)

    @model_validator(mode="after")
    def nonempty(self) -> Self:
        if not self.properties():
            raise ValueError("Empty presentation mutation")
        return self

    def properties(self) -> dict[str, object]:
        return self.model_dump(exclude={"target_id"}, exclude_none=True)


class UIFieldCapability(_Value):
    field_id: UUID
    binding: Key
    value_type: Literal["text", "integer", "decimal", "money", "date", "instant", "boolean", "enum"]
    permission: Key
    # The owner must explicitly declare an unclassified public projection (null).
    # Omission is unknown, not permission to disclose.
    classification_ref: str | None = Field(max_length=200)


class UIActionCapability(_Value):
    action_id: UUID
    permission: Key


class UIExtensionSlot(_Value):
    slot_id: UUID
    primitives: tuple[UIPrimitive, ...] = Field(min_length=1, max_length=12)


class UICustomization(_Value):
    target_id: UUID
    scopes: tuple[Literal["tenant", "company", "site", "user"], ...] = Field(min_length=1)
    properties: tuple[
        Literal["label_key", "help_key", "order", "visible", "density", "columns"], ...
    ] = Field(min_length=1)


class UIOwnerCapabilities(_Value):
    contract_version: Literal["1.0"] = "1.0"
    view_id: UUID
    resource_namespace: Key
    owner_contract_version: Annotated[str, Field(pattern=r"^[0-9]+(?:\.[0-9]+){0,2}$")]
    fields: tuple[UIFieldCapability, ...] = Field(default=(), max_length=128)
    actions: tuple[UIActionCapability, ...] = Field(default=(), max_length=32)
    extension_slots: tuple[UIExtensionSlot, ...] = Field(default=(), max_length=64)
    customization: tuple[UICustomization, ...] = Field(default=(), max_length=256)

    @model_validator(mode="after")
    def unique(self) -> Self:
        ids = [x.field_id for x in self.fields] + [x.action_id for x in self.actions]
        if len(ids) != len(set(ids)) or len({x.binding for x in self.fields}) != len(self.fields):
            raise ValueError("Conflicting owner capability IDs")
        for values in (
            [x.slot_id for x in self.extension_slots],
            [x.target_id for x in self.customization],
        ):
            if len(values) != len(set(values)):
                raise ValueError("Conflicting owner presentation capability IDs")
        return self


class UINode(_Value):
    node_id: UUID
    parent_id: UUID
    kind: Literal["section", "slot", "field", "action"]
    primitive: UIPrimitive
    presentation: UIPresentation
    field_id: UUID | None = None
    action_id: UUID | None = None

    @model_validator(mode="after")
    def structure(self) -> Self:
        allowed = {
            "section": {UIPrimitive.FORM_SECTION, UIPrimitive.CARD, UIPrimitive.GRID},
            "slot": {UIPrimitive.GRID},
            "field": set(UIPrimitive)
            - {UIPrimitive.FORM_SECTION, UIPrimitive.CARD, UIPrimitive.GRID, UIPrimitive.BUTTON},
            "action": {UIPrimitive.BUTTON},
        }
        if self.primitive not in allowed[self.kind]:
            raise ValueError("Primitive does not match node kind")
        if (self.kind == "field") != (self.field_id is not None):
            raise ValueError("Field capability binding required only on fields")
        if (self.kind == "action") != (self.action_id is not None):
            raise ValueError("Action capability binding required only on actions")
        return self


class UIViewSchema(_Value):
    contract_version: Literal["1.0"] = "1.0"
    view_id: UUID
    revision_id: UUID
    resource_namespace: Key
    owner_contract_version: Annotated[str, Field(pattern=r"^[0-9]+(?:\.[0-9]+){0,2}$")]
    permission: Key
    presentation: UIPresentation
    nodes: tuple[UINode, ...] = Field(default=(), max_length=256)

    @model_validator(mode="after")
    def topology(self) -> Self:
        validate_nodes(self.view_id, self.nodes)
        return self


class UIExtension(_Value):
    contract_version: Literal["1.0"] = "1.0"
    view_id: UUID
    contribution_id: UUID
    base_revision_id: UUID
    base_version: Annotated[str, Field(min_length=1, max_length=100)]
    priority: StrictInt = Field(default=0, ge=0, le=10000)
    nodes: tuple[UINode, ...] = Field(default=(), max_length=64)


class UITranslation(_Value):
    key: Key
    text: Annotated[str, Field(min_length=1, max_length=240)]

    @model_validator(mode="after")
    def inert_text(self) -> Self:
        if any(ord(c) < 32 for c in self.text) or any(c in self.text for c in "<>{}\\="):
            raise ValueError("Unsafe localization text")
        if re.search(
            r"(?:https?://|javascript:|data:|\b(?:eval|exec)\s*\(|"
            r"\b(?:select|insert|delete|drop|update)\s+(?:table|from|into|.+\bfrom\b))",
            self.text,
            re.IGNORECASE,
        ):
            raise ValueError("Executable/URL localization payload rejected")
        return self


class UILocalization(_Value):
    contract_version: Literal["1.0"] = "1.0"
    view_id: UUID
    contribution_id: UUID
    base_revision_id: UUID
    base_version: Annotated[str, Field(min_length=1, max_length=100)]
    locale: Locale
    translations: tuple[UITranslation, ...] = Field(max_length=512)

    @model_validator(mode="after")
    def unique(self) -> Self:
        if len({x.key for x in self.translations}) != len(self.translations):
            raise ValueError("Duplicate localization keys")
        return self


class UIOverlayScope(StrEnum):
    TENANT = "tenant"
    COMPANY = "company"
    SITE = "site"
    USER = "user"


class UIOverlayDocument(_Value):
    contract_version: Literal["1.0"] = "1.0"
    patches: tuple[UIPresentationPatch, ...] = Field(max_length=128)

    @model_validator(mode="after")
    def unique(self) -> Self:
        if len({x.target_id for x in self.patches}) != len(self.patches):
            raise ValueError("Duplicate patch targets")
        return self


class UIOverlayMutationResult(_Value):
    contract_version: Literal["1.0"] = "1.0"
    resource_namespace: Literal["foundation.metadata.ui_overlay"] = "foundation.metadata.ui_overlay"
    overlay_id: UUID
    view_id: UUID
    scope_kind: UIOverlayScope
    lifecycle: Literal["draft", "published", "retired"]
    draft_generation: int
    active_generation: int
    active_revision_id: UUID | None
    current_compatibility_digest: Digest


class UIOverlayRecord(UIOverlayMutationResult):
    """Draft disclosure is restricted to the separately authorized draft query."""

    draft_document: UIOverlayDocument
    draft_compatibility_digest: Digest


class UIModuleProvenance(_Value):
    module_id: Key
    module_version: str
    artifact_identity: str
    generation: int
    admission_generation: int


class UIDeclarationProvenance(_Value):
    key: Key
    owner: Key
    kind: str
    digest: Digest


class UIOverlayProvenance(_Value):
    overlay_id: UUID
    revision_id: UUID
    active_generation: int
    scope_kind: UIOverlayScope
    digest: Digest


class UIResolutionProvenance(_Value):
    base_revision_id: UUID
    compatibility_digest: Digest
    schema_generation: int
    ui_generation: int
    modules: tuple[UIModuleProvenance, ...]
    declarations: tuple[UIDeclarationProvenance, ...]
    overlays: tuple[UIOverlayProvenance, ...]
    locale: Locale
    # Security-complete scope is retained privately on the server, not echoed in diagnostics.
    security_validation: Literal["live-no-shared-cache"] = "live-no-shared-cache"


class ResolvedUILabel(_Value):
    target_id: UUID
    label_key: Key
    text: str | None = None
    help_key: Key | None = None
    help_text: str | None = None


class ResolvedUISchema(_Value):
    contract_version: Literal["1.0"] = "1.0"
    view: UIViewSchema
    capabilities: UIOwnerCapabilities
    labels: tuple[ResolvedUILabel, ...]
    provenance: UIResolutionProvenance
    presentation_only: Literal[True] = True


class UIDiagnosticCode(StrEnum):
    BASE_UNAVAILABLE = "base_unavailable"
    STABLE_ID_CONFLICT = "stable_id_conflict"
    INCOMPATIBLE = "incompatible"
    UNSUPPORTED_SCHEMA = "unsupported_schema"
    UNSUPPORTED_PRIMITIVE = "unsupported_primitive"
    INVALID_DOCUMENT = "invalid_document"
    CAPABILITY_UNAVAILABLE = "capability_unavailable"
    CLASSIFICATION_UNAVAILABLE = "classification_unavailable"
    LOCALIZATION_CONFLICT = "localization_conflict"
    STALE_OVERLAY = "stale_overlay"
    LIMIT_EXCEEDED = "limit_exceeded"
    STALE_CONTEXT = "stale_context"


class UIDiagnostic(_Value):
    code: UIDiagnosticCode
    # Codes are deliberately sufficient: no untrusted values or secret facts in diagnostics.


class UIResolution(_Value):
    contract_version: Literal["1.0"] = "1.0"
    resolved: ResolvedUISchema | None = None
    diagnostics: tuple[UIDiagnostic, ...] = Field(default=(), max_length=1)

    @model_validator(mode="after")
    def exclusive(self) -> Self:
        if (self.resolved is None) == (len(self.diagnostics) == 0):
            raise ValueError("Resolution must be either schema or one bounded diagnostic")
        return self


class UIConflict(Exception):
    def __init__(self, code: UIDiagnosticCode) -> None:
        self.code = code
        super().__init__(code.value)


def canonical_json(value: BaseModel | object) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def digest(value: BaseModel | object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def validate_nodes(view_id: UUID, nodes: tuple[UINode, ...]) -> None:
    by_id = {x.node_id: x for x in nodes}
    if len(by_id) != len(nodes) or view_id in by_id:
        raise ValueError("Conflicting stable node IDs")
    fields = [x.field_id for x in nodes if x.field_id is not None]
    actions = [x.action_id for x in nodes if x.action_id is not None]
    if len(fields) != len(set(fields)) or len(actions) != len(set(actions)):
        raise ValueError("Duplicate owner bindings")
    for node in nodes:
        visited = {node.node_id}
        parent = node.parent_id
        for _ in range(4):
            if parent == view_id:
                break
            ancestor = by_id.get(parent)
            if ancestor is None or ancestor.kind not in {"section", "slot"} or parent in visited:
                raise ValueError("Invalid UI topology")
            visited.add(parent)
            parent = ancestor.parent_id
        else:
            raise ValueError("UI nesting exceeds depth budget")
