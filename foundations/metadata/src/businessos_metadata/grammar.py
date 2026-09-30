"""Validation and type grammar foundation for metadata definitions."""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .diagnostics import MetadataDiagnosticCode, MetadataDiagnosticError

# Operator-governed capacity and quota controls (ADR-023)
MAX_PAYLOAD_BYTES: int = 65536
MAX_FIELDS_PER_DEFINITION: int = 100
MAX_RULE_DEPTH: int = 5
MAX_DEFINITIONS_PER_TENANT: int = 500
MAX_BULK_REFERENCE_BATCH: int = 100

_FIELD_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
_PHONE_PATTERN = re.compile(r"^\+[1-9]\d{1,14}$")
_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")

_MALICIOUS_SUBSTRINGS: tuple[str, ...] = (
    "<script",
    "</script>",
    "javascript:",
    "eval(",
    "onload=",
    "onerror=",
    "__proto__",
    "constructor.prototype",
)

_SQL_INJECTION_KEYWORDS: tuple[str, ...] = (
    "drop table",
    "select * from",
    "delete from",
    "update platform",
    "insert into",
    "--",
    ";--",
)


def _check_string_safety(val: str, field_desc: str) -> None:
    val_lower = val.lower()
    for needle in _MALICIOUS_SUBSTRINGS:
        if needle in val_lower:
            raise MetadataDiagnosticError(
                MetadataDiagnosticCode.VALIDATION_FAILED,
                f"Malicious script or prototype payload detected in {field_desc}: '{needle}'",
                details={"field": field_desc, "forbidden_sequence": needle},
            )
    for kw in _SQL_INJECTION_KEYWORDS:
        if kw in val_lower:
            raise MetadataDiagnosticError(
                MetadataDiagnosticCode.VALIDATION_FAILED,
                f"SQL injection sequence detected in {field_desc}: '{kw}'",
                details={"field": field_desc, "forbidden_keyword": kw},
            )


def check_payload_safety(data: Any, path: str = "root") -> None:
    """Recursively validates that untrusted JSON structures do not contain injection attempts."""
    if isinstance(data, str):
        _check_string_safety(data, path)
    elif isinstance(data, dict):
        for k, v in data.items():
            if not isinstance(k, str):
                raise MetadataDiagnosticError(
                    MetadataDiagnosticCode.VALIDATION_FAILED,
                    f"Invalid non-string key in {path}",
                )
            _check_string_safety(k, f"{path}.key[{k}]")
            check_payload_safety(v, f"{path}.{k}")
    elif isinstance(data, (list, tuple)):
        for idx, item in enumerate(data):
            check_payload_safety(item, f"{path}[{idx}]")


class SupportedFieldType(StrEnum):
    STRING = "string"
    TEXT = "text"
    INTEGER = "integer"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    MONEY = "money"
    EMAIL = "email"
    PHONE = "phone"
    URL = "url"
    REFERENCE = "reference"


class RuleOperator(StrEnum):
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    GREATER_THAN = "greater_than"
    LESS_THAN = "less_than"
    IN_SET = "in_set"
    IS_EMPTY = "is_empty"
    IS_NOT_EMPTY = "is_not_empty"


class RuleAction(StrEnum):
    REQUIRE_FIELD = "require_field"
    PROHIBIT_FIELD = "prohibit_field"
    REJECT_WITH_MESSAGE = "reject_with_message"


class FieldDefinitionModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str = Field(min_length=2, max_length=64)
    field_type: SupportedFieldType
    label: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    required: bool = False
    default_value: Any | None = None
    constraints: dict[str, Any] = Field(default_factory=dict)
    classification_ref: str | None = Field(default=None, max_length=255)
    target_resource_namespace: str | None = Field(default=None, max_length=100)
    target_cardinality: str | None = Field(default=None, max_length=20)

    @model_validator(mode="after")
    def validate_grammar(self) -> FieldDefinitionModel:
        if not _FIELD_KEY_PATTERN.match(self.key):
            raise MetadataDiagnosticError(
                MetadataDiagnosticCode.VALIDATION_FAILED,
                f"Field key '{self.key}' must be snake_case alphanumeric starting with a letter",
            )
        _check_string_safety(self.label, f"label for field {self.key}")
        if self.description:
            _check_string_safety(self.description, f"description for field {self.key}")

        if self.field_type == SupportedFieldType.REFERENCE:
            if not self.target_resource_namespace:
                raise MetadataDiagnosticError(
                    MetadataDiagnosticCode.VALIDATION_FAILED,
                    f"Reference field '{self.key}' requires 'target_resource_namespace'",
                )
            if self.target_cardinality and self.target_cardinality not in (
                "many_to_one",
                "one_to_one",
            ):
                raise MetadataDiagnosticError(
                    MetadataDiagnosticCode.VALIDATION_FAILED,
                    f"Reference field '{self.key}' unsupported cardinality '{self.target_cardinality}'. Phase 5 supports many_to_one or one_to_one.",
                )

        if self.default_value is not None:
            self._validate_default_value(self.default_value)

        return self

    def _validate_default_value(self, val: Any) -> None:
        t = self.field_type
        if t in (SupportedFieldType.STRING, SupportedFieldType.TEXT):
            if not isinstance(val, str):
                raise MetadataDiagnosticError(
                    MetadataDiagnosticCode.VALIDATION_FAILED,
                    f"Default value for {t} field '{self.key}' must be a string",
                )
            _check_string_safety(val, f"default_value for {self.key}")
        elif t == SupportedFieldType.INTEGER:
            if not isinstance(val, int) or isinstance(val, bool):
                raise MetadataDiagnosticError(
                    MetadataDiagnosticCode.VALIDATION_FAILED,
                    f"Default value for integer field '{self.key}' must be an integer",
                )
        elif t == SupportedFieldType.DECIMAL:
            if not isinstance(val, (int, float, str)):
                raise MetadataDiagnosticError(
                    MetadataDiagnosticCode.VALIDATION_FAILED,
                    f"Default value for decimal field '{self.key}' must be a numeric value or decimal string",
                )
            try:
                Decimal(str(val))
            except Exception as exc:
                raise MetadataDiagnosticError(
                    MetadataDiagnosticCode.VALIDATION_FAILED,
                    f"Invalid decimal default value '{val}' for field '{self.key}'",
                ) from exc
        elif t == SupportedFieldType.BOOLEAN:
            if not isinstance(val, bool):
                raise MetadataDiagnosticError(
                    MetadataDiagnosticCode.VALIDATION_FAILED,
                    f"Default value for boolean field '{self.key}' must be a boolean",
                )
        elif t == SupportedFieldType.DATE:
            if not isinstance(val, str):
                raise MetadataDiagnosticError(
                    MetadataDiagnosticCode.VALIDATION_FAILED,
                    f"Default date for '{self.key}' must be ISO 8601 string YYYY-MM-DD",
                )
            try:
                date.fromisoformat(val)
            except Exception as exc:
                raise MetadataDiagnosticError(
                    MetadataDiagnosticCode.VALIDATION_FAILED,
                    f"Invalid ISO date '{val}' for field '{self.key}'",
                ) from exc
        elif t == SupportedFieldType.DATETIME:
            if not isinstance(val, str):
                raise MetadataDiagnosticError(
                    MetadataDiagnosticCode.VALIDATION_FAILED,
                    f"Default datetime for '{self.key}' must be ISO 8601 string",
                )
            try:
                datetime.fromisoformat(val)
            except Exception as exc:
                raise MetadataDiagnosticError(
                    MetadataDiagnosticCode.VALIDATION_FAILED,
                    f"Invalid ISO datetime '{val}' for field '{self.key}'",
                ) from exc
        elif t == SupportedFieldType.MONEY:
            if not isinstance(val, dict) or "amount" not in val or "currency" not in val:
                raise MetadataDiagnosticError(
                    MetadataDiagnosticCode.VALIDATION_FAILED,
                    f"Money default for '{self.key}' must be a dict with 'amount' and 'currency'",
                )
            if not _CURRENCY_PATTERN.match(str(val["currency"])):
                raise MetadataDiagnosticError(
                    MetadataDiagnosticCode.VALIDATION_FAILED,
                    f"Invalid currency code '{val['currency']}' in default value for '{self.key}'",
                )
        elif t == SupportedFieldType.EMAIL:
            if not isinstance(val, str) or not _EMAIL_PATTERN.match(val):
                raise MetadataDiagnosticError(
                    MetadataDiagnosticCode.VALIDATION_FAILED,
                    f"Invalid email default '{val}' for field '{self.key}'",
                )
        elif t == SupportedFieldType.PHONE:
            if not isinstance(val, str) or not _PHONE_PATTERN.match(val):
                raise MetadataDiagnosticError(
                    MetadataDiagnosticCode.VALIDATION_FAILED,
                    f"Invalid E.164 phone default '{val}' for field '{self.key}'",
                )
        elif t == SupportedFieldType.URL:
            if not isinstance(val, str) or not (val.startswith("http://") or val.startswith("https://")):
                raise MetadataDiagnosticError(
                    MetadataDiagnosticCode.VALIDATION_FAILED,
                    f"Invalid URL default '{val}' for field '{self.key}'. Must begin with http:// or https://",
                )
            _check_string_safety(val, f"URL default for {self.key}")
        elif t == SupportedFieldType.REFERENCE:
            if not isinstance(val, str):
                raise MetadataDiagnosticError(
                    MetadataDiagnosticCode.VALIDATION_FAILED,
                    f"Default reference for '{self.key}' must be a valid UUID string",
                )
            try:
                UUID(val)
            except Exception as exc:
                raise MetadataDiagnosticError(
                    MetadataDiagnosticCode.VALIDATION_FAILED,
                    f"Invalid UUID reference default '{val}' for field '{self.key}'",
                ) from exc


class CrossFieldRuleModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    condition_field: str = Field(min_length=1, max_length=64)
    operator: RuleOperator
    comparison_value: Any
    action: RuleAction
    target_field: str | None = Field(default=None, max_length=64)
    error_message: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_rule(self) -> CrossFieldRuleModel:
        _check_string_safety(self.name, f"rule name {self.name}")
        _check_string_safety(self.error_message, f"error_message for rule {self.name}")
        if self.action in (RuleAction.REQUIRE_FIELD, RuleAction.PROHIBIT_FIELD) and not self.target_field:
            raise MetadataDiagnosticError(
                MetadataDiagnosticCode.VALIDATION_FAILED,
                f"Rule '{self.name}' action '{self.action}' requires 'target_field'",
            )
        return self


class MetadataPayloadModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = Field(default="1", max_length=20)
    fields: list[FieldDefinitionModel] = Field(default_factory=list)
    cross_field_rules: list[CrossFieldRuleModel] = Field(default_factory=list)
    custom_attributes: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_quotas_and_uniqueness(self) -> MetadataPayloadModel:
        # Check quota: fields count
        if len(self.fields) > MAX_FIELDS_PER_DEFINITION:
            raise MetadataDiagnosticError(
                MetadataDiagnosticCode.QUOTA_EXCEEDED,
                f"Definition exceeds maximum field quota ({len(self.fields)} > {MAX_FIELDS_PER_DEFINITION})",
                details={"quota": "max_fields", "limit": MAX_FIELDS_PER_DEFINITION, "actual": len(self.fields)},
            )

        # Check quota: rule depth
        if len(self.cross_field_rules) > MAX_RULE_DEPTH:
            raise MetadataDiagnosticError(
                MetadataDiagnosticCode.QUOTA_EXCEEDED,
                f"Definition exceeds maximum cross-field rule quota ({len(self.cross_field_rules)} > {MAX_RULE_DEPTH})",
                details={"quota": "max_rules", "limit": MAX_RULE_DEPTH, "actual": len(self.cross_field_rules)},
            )

        # Check field key uniqueness
        seen_keys: set[str] = set()
        for f in self.fields:
            if f.key in seen_keys:
                raise MetadataDiagnosticError(
                    MetadataDiagnosticCode.VALIDATION_FAILED,
                    f"Duplicate field key '{f.key}' in metadata definition",
                )
            seen_keys.add(f.key)

        # Check cross-field rule references valid fields
        for rule in self.cross_field_rules:
            if rule.condition_field not in seen_keys:
                raise MetadataDiagnosticError(
                    MetadataDiagnosticCode.VALIDATION_FAILED,
                    f"Rule '{rule.name}' references undeclared condition_field '{rule.condition_field}'",
                )
            if rule.target_field and rule.target_field not in seen_keys:
                raise MetadataDiagnosticError(
                    MetadataDiagnosticCode.VALIDATION_FAILED,
                    f"Rule '{rule.name}' references undeclared target_field '{rule.target_field}'",
                )

        # Check payload byte size
        payload_bytes = len(
            json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        if payload_bytes > MAX_PAYLOAD_BYTES:
            raise MetadataDiagnosticError(
                MetadataDiagnosticCode.QUOTA_EXCEEDED,
                f"Definition payload size {payload_bytes} exceeds quota {MAX_PAYLOAD_BYTES} bytes",
                details={"quota": "max_bytes", "limit": MAX_PAYLOAD_BYTES, "actual": payload_bytes},
            )

        check_payload_safety(self.custom_attributes, "custom_attributes")
        return self
