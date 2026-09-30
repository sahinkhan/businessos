"""Unit tests for Phase 5A versioned metadata contracts, grammar, and diagnostics."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from businessos_metadata import (
    BulkReferenceResolutionQuery,
    FieldDefinitionModel,
    MetadataDiagnosticCode,
    MetadataDiagnosticError,
    MetadataPayloadModel,
    PublishPreflightInput,
    ReferenceResolutionQuery,
    RuleAction,
    RuleOperator,
    SupportedFieldType,
    TargetReferenceState,
    check_payload_safety,
    validate_cross_owner_deletion,
)
from businessos_metadata.grammar import (
    MAX_BULK_REFERENCE_BATCH,
    MAX_FIELDS_PER_DEFINITION,
    MAX_PAYLOAD_BYTES,
    MAX_RULE_DEPTH,
)
from businessos_metadata.service import _compute_digest


def test_supported_field_types_and_defaults_validation() -> None:
    # 1. String
    f_str = FieldDefinitionModel(
        key="customer_code",
        field_type=SupportedFieldType.STRING,
        label="Customer Code",
        default_value="CUST-001",
    )
    assert f_str.key == "customer_code"

    # 2. Integer
    f_int = FieldDefinitionModel(
        key="priority_level",
        field_type=SupportedFieldType.INTEGER,
        label="Priority",
        default_value=5,
    )
    assert f_int.default_value == 5

    # 3. Decimal
    f_dec = FieldDefinitionModel(
        key="discount_rate",
        field_type=SupportedFieldType.DECIMAL,
        label="Discount Rate",
        default_value="0.15",
    )
    assert f_dec.default_value == "0.15"

    # 4. Boolean
    f_bool = FieldDefinitionModel(
        key="is_vip",
        field_type=SupportedFieldType.BOOLEAN,
        label="Is VIP",
        default_value=True,
    )
    assert f_bool.default_value is True

    # 5. Date
    f_date = FieldDefinitionModel(
        key="contract_date",
        field_type=SupportedFieldType.DATE,
        label="Contract Date",
        default_value="2026-09-30",
    )
    assert f_date.default_value == "2026-09-30"

    # 6. DateTime
    f_dt = FieldDefinitionModel(
        key="effective_timestamp",
        field_type=SupportedFieldType.DATETIME,
        label="Effective Timestamp",
        default_value="2026-09-30T12:00:00Z",
    )
    assert f_dt.default_value == "2026-09-30T12:00:00Z"

    # 7. Money
    f_money = FieldDefinitionModel(
        key="credit_limit",
        field_type=SupportedFieldType.MONEY,
        label="Credit Limit",
        default_value={"amount": "5000.00", "currency": "USD"},
    )
    assert f_money.default_value["currency"] == "USD"

    # 8. Email
    f_email = FieldDefinitionModel(
        key="billing_email",
        field_type=SupportedFieldType.EMAIL,
        label="Billing Email",
        default_value="billing@example.com",
    )
    assert f_email.default_value == "billing@example.com"

    # 9. Phone
    f_phone = FieldDefinitionModel(
        key="support_phone",
        field_type=SupportedFieldType.PHONE,
        label="Support Phone",
        default_value="+14155552671",
    )
    assert f_phone.default_value == "+14155552671"

    # 10. URL
    f_url = FieldDefinitionModel(
        key="website_url",
        field_type=SupportedFieldType.URL,
        label="Website",
        default_value="https://example.com/portal",
    )
    assert f_url.default_value == "https://example.com/portal"

    # 11. Text
    f_text = FieldDefinitionModel(
        key="internal_notes",
        field_type=SupportedFieldType.TEXT,
        label="Internal Notes",
        default_value="Approved on review",
    )
    assert f_text.default_value == "Approved on review"

    # 12. Reference
    ref_id = str(uuid4())
    f_ref = FieldDefinitionModel(
        key="parent_party_id",
        field_type=SupportedFieldType.REFERENCE,
        label="Parent Party",
        target_resource_namespace="foundation.party",
        target_cardinality="many_to_one",
        default_value=ref_id,
    )
    assert f_ref.target_resource_namespace == "foundation.party"


def test_invalid_deterministic_defaults_rejected() -> None:
    # Invalid boolean
    with pytest.raises(MetadataDiagnosticError, match="must be a boolean"):
        FieldDefinitionModel(
            key="flag",
            field_type=SupportedFieldType.BOOLEAN,
            label="Flag",
            default_value="yes",
        )

    # Invalid integer
    with pytest.raises(MetadataDiagnosticError, match="must be an integer"):
        FieldDefinitionModel(
            key="count",
            field_type=SupportedFieldType.INTEGER,
            label="Count",
            default_value=True,
        )

    # Invalid date
    with pytest.raises(MetadataDiagnosticError, match="Invalid ISO date"):
        FieldDefinitionModel(
            key="due_date",
            field_type=SupportedFieldType.DATE,
            label="Due Date",
            default_value="30-09-2026",
        )

    # Invalid money currency
    with pytest.raises(MetadataDiagnosticError, match="Invalid currency code"):
        FieldDefinitionModel(
            key="price",
            field_type=SupportedFieldType.MONEY,
            label="Price",
            default_value={"amount": 100, "currency": "usd"},
        )

    # Invalid email
    with pytest.raises(MetadataDiagnosticError, match="Invalid email default"):
        FieldDefinitionModel(
            key="email",
            field_type=SupportedFieldType.EMAIL,
            label="Email",
            default_value="not-an-email",
        )

    # Invalid phone
    with pytest.raises(MetadataDiagnosticError, match="Invalid E.164 phone default"):
        FieldDefinitionModel(
            key="phone",
            field_type=SupportedFieldType.PHONE,
            label="Phone",
            default_value="12345",
        )

    # Invalid URL scheme
    with pytest.raises(MetadataDiagnosticError, match="Must begin with http"):
        FieldDefinitionModel(
            key="link",
            field_type=SupportedFieldType.URL,
            label="Link",
            default_value="ftp://example.com",
        )


def test_malicious_payload_rejection() -> None:
    # 1. Script tag injection in label
    with pytest.raises(MetadataDiagnosticError, match="Malicious script"):
        FieldDefinitionModel(
            key="clean_key",
            field_type=SupportedFieldType.STRING,
            label="Customer <script>alert('xss')</script>",
        )

    # 2. Prototype pollution sequence
    with pytest.raises(MetadataDiagnosticError, match="prototype payload detected"):
        check_payload_safety({"__proto__": {"polluted": True}})

    # 3. JavaScript URL injection
    with pytest.raises(MetadataDiagnosticError, match="Malicious script"):
        check_payload_safety({"action": "javascript:alert(1)"})

    # 4. SQL injection keyword sequence in description
    with pytest.raises(MetadataDiagnosticError, match="SQL injection sequence detected"):
        FieldDefinitionModel(
            key="sql_test",
            field_type=SupportedFieldType.STRING,
            label="Safe Label",
            description="attempting drop table platform_metadata",
        )


def test_quota_limits_rejection() -> None:
    # 1. Max fields exceeded
    too_many_fields = [
        FieldDefinitionModel(
            key=f"field_{i}",
            field_type=SupportedFieldType.STRING,
            label=f"Field {i}",
        )
        for i in range(MAX_FIELDS_PER_DEFINITION + 1)
    ]
    with pytest.raises(MetadataDiagnosticError) as exc_info:
        MetadataPayloadModel(fields=too_many_fields)
    assert exc_info.value.diagnostic_code == MetadataDiagnosticCode.QUOTA_EXCEEDED

    # 2. Max payload byte size exceeded
    huge_custom = {"large_text": "x" * (MAX_PAYLOAD_BYTES + 500)}
    with pytest.raises(MetadataDiagnosticError) as exc_info:
        MetadataPayloadModel(custom_attributes=huge_custom)
    assert exc_info.value.diagnostic_code == MetadataDiagnosticCode.QUOTA_EXCEEDED

    # 3. Bulk reference batch size exceeded
    with pytest.raises(MetadataDiagnosticError) as exc_info:
        BulkReferenceResolutionQuery(
            source_resource_namespace="foundation.order",
            target_resource_namespace="foundation.party",
            target_record_ids=[uuid4() for _ in range(MAX_BULK_REFERENCE_BATCH + 1)],
            tenant_id=uuid4(),
        )
    assert exc_info.value.diagnostic_code == MetadataDiagnosticCode.QUOTA_EXCEEDED


def test_cross_field_rules_grammar() -> None:
    f1 = FieldDefinitionModel(key="tax_exempt", field_type=SupportedFieldType.BOOLEAN, label="Tax Exempt")
    f2 = FieldDefinitionModel(key="tax_id", field_type=SupportedFieldType.STRING, label="Tax ID")

    # Valid rule
    payload = MetadataPayloadModel(
        fields=[f1, f2],
        cross_field_rules=[
            {
                "name": "tax_id_required_if_exempt",
                "condition_field": "tax_exempt",
                "operator": RuleOperator.EQUALS,
                "comparison_value": True,
                "action": RuleAction.REQUIRE_FIELD,
                "target_field": "tax_id",
                "error_message": "Tax ID is required when Tax Exempt is enabled",
            }
        ],
    )
    assert len(payload.cross_field_rules) == 1

    # Invalid rule: references undeclared field
    with pytest.raises(MetadataDiagnosticError, match="references undeclared condition_field"):
        MetadataPayloadModel(
            fields=[f1],
            cross_field_rules=[
                {
                    "name": "invalid_rule",
                    "condition_field": "nonexistent_field",
                    "operator": RuleOperator.EQUALS,
                    "comparison_value": True,
                    "action": RuleAction.REJECT_WITH_MESSAGE,
                    "error_message": "Invalid",
                }
            ],
        )


def test_cross_owner_deletion_invariant() -> None:
    # Same owner can specify restrict or cascade
    validate_cross_owner_deletion("foundation.party", "foundation.party", "cascade")
    validate_cross_owner_deletion("foundation.party", "foundation.party", "restrict")

    # Cross owner MUST reject synchronous restrict/nullify/cascade
    with pytest.raises(MetadataDiagnosticError) as exc_info:
        validate_cross_owner_deletion("business.order", "foundation.party", "cascade")
    assert exc_info.value.diagnostic_code == MetadataDiagnosticCode.UNSUPPORTED_CROSS_OWNER_DELETION

    with pytest.raises(MetadataDiagnosticError) as exc_info:
        validate_cross_owner_deletion("business.order", "foundation.party", "restrict")
    assert exc_info.value.diagnostic_code == MetadataDiagnosticCode.UNSUPPORTED_CROSS_OWNER_DELETION


def test_content_digest_deterministic() -> None:
    p1 = {"b": 2, "a": 1, "c": [3, 2, 1]}
    p2 = {"a": 1, "c": [3, 2, 1], "b": 2}
    digest1 = _compute_digest(p1)
    digest2 = _compute_digest(p2)
    assert digest1 == digest2
    assert len(digest1) == 64
