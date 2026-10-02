"""Metadata-owned read-only published-schema port and canonical value validation."""

from __future__ import annotations

import json
import operator
from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import cast

from sqlalchemy import and_, select

from businessos.sdk import (
    AUTHORIZER,
    PUBLISHED_CUSTOM_FIELD_SCHEMA,
    RESOURCE_OWNER_RESOLVER,
    BusinessOSError,
    CustomSchemaPin,
    HandlingContext,
    PublishedCustomFieldSchema,
    ResourceLocator,
    TenantContext,
    UnitOfWork,
)

from .contracts import Comparison, DefinitionSnapshot, FieldType, MetadataLimits, MoneyLiteral
from .models import DEFINITIONS, REVISIONS

SchemaReadTransaction = Callable[[TenantContext], AbstractAsyncContextManager[UnitOfWork]]


@dataclass(frozen=True, slots=True)
class _PublishedSchema:
    pin: CustomSchemaPin
    _snapshot: DefinitionSnapshot
    _limits: MetadataLimits

    @property
    def canonical_schema_json(self) -> str:
        return self._snapshot.model_dump_json()

    @property
    def supported_field_types(self) -> tuple[str, ...]:
        return tuple(kind.value for kind in FieldType if kind is not FieldType.REFERENCE)

    def validate_values(self, values: Mapping[str, object], *, cleared: bool = False) -> str:
        try:
            # Revalidate even retained schemas: classification/reference support is not certified.
            self._snapshot.validate_limits(self._limits)
            fields = {str(field.field_id): field for field in self._snapshot.fields}
            if any(field.classification_ref is not None for field in fields.values()):
                raise BusinessOSError(
                    "classification_unavailable", "Classified custom fields unavailable"
                )
            if any(field.value_type is FieldType.REFERENCE for field in fields.values()):
                raise BusinessOSError(
                    "custom_reference_unsupported", "Reference custom fields unsupported"
                )
            if set(values) - fields.keys():
                raise ValueError("Unknown stable field ID")
            if cleared:
                if values:
                    raise ValueError("Cleared document must be empty")
                return "{}"
            literals: dict[str, object] = {}
            for key, field in fields.items():
                value = values.get(key)
                if value is None:
                    if not field.nullable:
                        raise ValueError("Required non-nullable field missing")
                    continue
                if field.value_type is FieldType.MONEY:
                    value = MoneyLiteral.model_validate(value)
                if not isinstance(value, (str, int, bool, MoneyLiteral)):
                    raise ValueError("Unsupported custom value")
                field.validate_literal(value)
                literals[field.name] = value
            for rule in self._snapshot.rules:
                left = literals.get(rule.left_field)
                if left is None:
                    continue
                field = next(field for field in fields.values() if field.name == rule.left_field)
                right: object = rule.right_literal
                if field.value_type is FieldType.DECIMAL:
                    left, right = Decimal(str(left)), Decimal(str(right))
                elif field.value_type is FieldType.DATE:
                    left, right = date.fromisoformat(str(left)), date.fromisoformat(str(right))
                elif field.value_type is FieldType.INSTANT:
                    left, right = (
                        datetime.fromisoformat(str(left)),
                        datetime.fromisoformat(str(right)),
                    )
                # The certified grammar forbids ordering of all other non-orderable types.
                comparisons = {
                    Comparison.EQ: operator.eq,
                    Comparison.NE: operator.ne,
                    Comparison.LT: operator.lt,
                    Comparison.LE: operator.le,
                    Comparison.GT: operator.gt,
                    Comparison.GE: operator.ge,
                }
                compare = cast(Callable[[object, object], bool], comparisons[rule.comparison])
                comparison = compare(left, right)
                if rule.require_field is None and not comparison:
                    raise ValueError("Custom value validation rule failed")
                if (
                    comparison
                    and rule.require_field is not None
                    and rule.require_field not in literals
                ):
                    raise ValueError("Conditionally required field missing")
            document = json.dumps(
                dict(values),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            if len(document.encode("utf-8")) > self._limits.max_document_bytes:
                raise ValueError("Custom value document exceeds byte budget")
            return document
        except (ValueError, TypeError, OverflowError):
            raise BusinessOSError(
                "custom_values_invalid", "Custom values violate published schema"
            ) from None


class PublishedSchemaReader:
    version = "1.0"

    def __init__(self, factory: SchemaReadTransaction | None, limits: MetadataLimits) -> None:
        self._factory = factory
        # Owner v1 capability is bounded even when definition-authoring limits are larger.
        self._limits = limits.model_copy(
            update={
                "max_fields": min(limits.max_fields, 128),
                "max_document_bytes": min(limits.max_document_bytes, 65536),
            }
        )
        self.active = False

    async def resolve(
        self,
        locator: ResourceLocator,
        context: HandlingContext,
        *,
        pin: CustomSchemaPin | None = None,
    ) -> PublishedCustomFieldSchema:
        if not self.active or self._factory is None:
            raise BusinessOSError(
                "custom_schema_unavailable",
                "Published schema resolver unavailable",
                status_code=503,
            )
        # Re-admit cached callers through the reserved, generation-bound DI entry.
        if await context.dependencies.resolve(PUBLISHED_CUSTOM_FIELD_SCHEMA) is not self:
            raise BusinessOSError(
                "custom_schema_unavailable", "Stale published schema resolver", status_code=503
            )
        tenant = context.request.tenant
        if tenant is None or tenant.tenant_id != locator.tenant_id:
            raise BusinessOSError("forbidden", "Trusted resource tenant required", status_code=403)
        owners = await context.dependencies.resolve(RESOURCE_OWNER_RESOLVER)
        owners.assert_owner_handler(locator, context.request, context.unit_of_work)
        owner = owners.resolve_owner(locator.namespace, locator.contract_version)
        authorizer = await context.dependencies.resolve(AUTHORIZER)
        await authorizer.require(context.request, "foundation.metadata.definition.read")
        condition = [
            DEFINITIONS.c.tenant_id == tenant.tenant_id,
            DEFINITIONS.c.owner_module_id == owner.ownership.owner_module_id,
            DEFINITIONS.c.resource_namespace == locator.namespace,
            DEFINITIONS.c.owner_contract_version == locator.contract_version,
            DEFINITIONS.c.kind == "field_set",
        ]
        if pin is None:
            condition.extend(
                [
                    DEFINITIONS.c.lifecycle == "published",
                    REVISIONS.c.id == DEFINITIONS.c.active_revision_id,
                ]
            )
        else:
            condition.extend(
                [
                    DEFINITIONS.c.id == pin.definition_id,
                    REVISIONS.c.id == pin.revision_id,
                    REVISIONS.c.digest == pin.digest,
                ]
            )
        async with self._factory(tenant) as unit:
            result = await unit.persistence.execute(
                select(
                    REVISIONS.c.id,
                    REVISIONS.c.definition_id,
                    REVISIONS.c.digest,
                    REVISIONS.c.snapshot,
                )
                .select_from(
                    DEFINITIONS.join(
                        REVISIONS,
                        and_(
                            REVISIONS.c.tenant_id == DEFINITIONS.c.tenant_id,
                            REVISIONS.c.definition_id == DEFINITIONS.c.id,
                        ),
                    )
                )
                .where(*condition)
            )
            row = result.one_or_none()
        if row is None:
            raise BusinessOSError(
                "custom_schema_unavailable",
                "Published custom-field revision required",
                status_code=409,
            )
        try:
            snapshot = DefinitionSnapshot.model_validate(row.snapshot)
            if snapshot.digest() != row.digest:
                raise ValueError("Revision digest mismatch")
            projection = _PublishedSchema(
                CustomSchemaPin(row.definition_id, row.id, row.digest), snapshot, self._limits
            )
            projection.validate_values({}, cleared=True)
        except ValueError:
            raise BusinessOSError(
                "custom_schema_invalid", "Published revision integrity failure", status_code=503
            ) from None
        return projection
