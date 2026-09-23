"""Create the canonical, globally shared Currency foundation.

Revision ID: currency_0001
Revises: 0005_durable_event_subscribers
"""

from collections.abc import Sequence
from uuid import UUID, uuid5

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "currency_0001"
down_revision: str | Sequence[str] | None = "0005_durable_event_subscribers"
branch_labels: str | Sequence[str] | None = ("foundation_currency",)
depends_on: str | Sequence[str] | None = None

SCHEMA = "platform_currency"
_NAMESPACE = UUID("eb917e07-90c6-4a13-820b-11c713988d62")

# Versioned ISO 4217 seed used by this release. Additions and corrections require
# a new migration so installed databases remain reproducible.
_CURRENCIES = (
    ("AED", "784", "UAE Dirham", 2),
    ("AUD", "036", "Australian Dollar", 2),
    ("BDT", "050", "Taka", 2),
    ("BRL", "986", "Brazilian Real", 2),
    ("CAD", "124", "Canadian Dollar", 2),
    ("CHF", "756", "Swiss Franc", 2),
    ("CNY", "156", "Yuan Renminbi", 2),
    ("CZK", "203", "Czech Koruna", 2),
    ("DKK", "208", "Danish Krone", 2),
    ("EGP", "818", "Egyptian Pound", 2),
    ("EUR", "978", "Euro", 2),
    ("GBP", "826", "Pound Sterling", 2),
    ("HKD", "344", "Hong Kong Dollar", 2),
    ("HUF", "348", "Forint", 2),
    ("IDR", "360", "Rupiah", 2),
    ("ILS", "376", "New Israeli Sheqel", 2),
    ("INR", "356", "Indian Rupee", 2),
    ("JPY", "392", "Yen", 0),
    ("KES", "404", "Kenyan Shilling", 2),
    ("KRW", "410", "Won", 0),
    ("KWD", "414", "Kuwaiti Dinar", 3),
    ("MXN", "484", "Mexican Peso", 2),
    ("MYR", "458", "Malaysian Ringgit", 2),
    ("NGN", "566", "Naira", 2),
    ("NOK", "578", "Norwegian Krone", 2),
    ("NPR", "524", "Nepalese Rupee", 2),
    ("NZD", "554", "New Zealand Dollar", 2),
    ("OMR", "512", "Rial Omani", 3),
    ("PKR", "586", "Pakistan Rupee", 2),
    ("PLN", "985", "Zloty", 2),
    ("QAR", "634", "Qatari Rial", 2),
    ("RUB", "643", "Russian Ruble", 2),
    ("SAR", "682", "Saudi Riyal", 2),
    ("SEK", "752", "Swedish Krona", 2),
    ("SGD", "702", "Singapore Dollar", 2),
    ("THB", "764", "Baht", 2),
    ("TRY", "949", "Turkish Lira", 2),
    ("USD", "840", "US Dollar", 2),
    ("VND", "704", "Dong", 0),
    ("XAF", "950", "CFA Franc BEAC", 0),
    ("XOF", "952", "CFA Franc BCEAO", 0),
    ("ZAR", "710", "Rand", 2),
)


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    op.execute(f"REVOKE ALL ON SCHEMA {SCHEMA} FROM PUBLIC")
    table = op.create_table(
        "currencies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(3), nullable=False),
        sa.Column("numeric_code", sa.String(3), nullable=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("minor_unit", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("source", sa.String(80), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.CheckConstraint("minor_unit BETWEEN 0 AND 6", name="ck_currency_minor_unit"),
        sa.CheckConstraint("code ~ '^[A-Z]{3}$'", name="ck_currency_alpha_code"),
        sa.CheckConstraint(
            "numeric_code IS NULL OR numeric_code ~ '^[0-9]{3}$'",
            name="ck_currency_numeric_code",
        ),
        sa.CheckConstraint("source_version > 0", name="ck_currency_source_version"),
        sa.PrimaryKeyConstraint("id", name="pk_currencies"),
        sa.UniqueConstraint("code", name="uq_currencies_code"),
        sa.UniqueConstraint("numeric_code", name="uq_currencies_numeric_code"),
        schema=SCHEMA,
    )
    op.bulk_insert(
        table,
        [
            {
                "id": uuid5(_NAMESPACE, code),
                "code": code,
                "numeric_code": numeric,
                "name": name,
                "minor_unit": minor,
                "is_active": True,
                "source": "ISO-4217",
                "source_version": 1,
            }
            for code, numeric, name, minor in _CURRENCIES
        ],
    )
    op.execute(f"GRANT USAGE ON SCHEMA {SCHEMA} TO businessos_app")
    op.execute(f"GRANT SELECT ON {SCHEMA}.currencies TO businessos_app")


def downgrade() -> None:
    op.drop_table("currencies", schema=SCHEMA)
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA}")
