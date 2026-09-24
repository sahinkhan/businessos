"""Bounded preflight and atomic operator-reviewed legacy classification mapping.

This executable uses the migrator credential. It never infers a legacy row's
ownership. A reviewed file must exactly cover every legacy row before apply.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from .classification_v2 import parse_ref

_LIMIT = 100


def _connection(url: str) -> psycopg.Connection[Any]:
    return psycopg.connect(
        url.replace("postgresql+psycopg://", "postgresql://", 1),
        row_factory=cast(Any, dict_row),
    )


def preflight(connection: psycopg.Connection[Any]) -> dict[str, object]:
    """Inventory bounded row evidence without writing or guessing provenance."""
    with connection.transaction():
        connection.execute("SET TRANSACTION READ ONLY")
        count_row = connection.execute(
            "SELECT count(*) AS n FROM platform_gov.data_classifications"
        ).fetchone()
        assert count_row is not None
        legacy_count = count_row["n"]
        rows = connection.execute(
            "SELECT d.code, d.name, d.sensitivity_level, "
            "left(d.description, 200) AS description_preview, "
            "length(d.description) AS description_length, "
            "encode(sha256(convert_to(d.description, 'UTF8')), 'hex') "
            "AS description_sha256, "
            "m.qualified_ref, m.definition_id, m.definition_version, m.tenant_id, "
            "m.legacy_description_sha256 AS approved_description_sha256, "
            "(SELECT count(*) FROM platform_gov.sensitive_field_tags t "
            " WHERE t.classification_code = d.code) AS tag_count, "
            "(SELECT count(*) FROM platform_gov.retention_policies p "
            " WHERE p.classification_code = d.code) AS retention_count, "
            "(SELECT count(DISTINCT tenant_id) FROM ("
            " SELECT tenant_id FROM platform_gov.sensitive_field_tags "
            " WHERE classification_code = d.code UNION "
            " SELECT tenant_id FROM platform_gov.retention_policies "
            " WHERE classification_code = d.code) uses) AS tenant_count "
            "FROM platform_gov.data_classifications d "
            "LEFT JOIN platform_gov.classification_legacy_mappings m ON m.legacy_code = d.code "
            "ORDER BY d.code LIMIT %s",
            (_LIMIT + 1,),
        ).fetchall()
        collisions = connection.execute(
            "SELECT upper(code) AS normalized_code, count(*) AS n "
            "FROM platform_gov.data_classifications GROUP BY upper(code) "
            "HAVING count(*) > 1 ORDER BY upper(code) LIMIT %s",
            (_LIMIT + 1,),
        ).fetchall()
        orphans: dict[str, int] = {}
        inconsistent_references: dict[str, int] = {}
        for table in ("sensitive_field_tags", "retention_policies"):
            # Fixed allowlisted table names; never interpolate operator input.
            orphan_row = connection.execute(
                f"SELECT count(*) AS n FROM platform_gov.{table} r "
                "LEFT JOIN platform_gov.data_classifications d "
                "ON d.code = r.classification_code "
                "WHERE r.classification_code IS NOT NULL AND d.code IS NULL"
            ).fetchone()
            assert orphan_row is not None
            orphans[table] = orphan_row["n"]
            inconsistent_row = connection.execute(
                f"SELECT count(*) AS n FROM platform_gov.{table} r "
                "LEFT JOIN platform_gov.classification_legacy_mappings m "
                "ON m.legacy_code = r.classification_code "
                "WHERE (r.classification_code IS NOT NULL AND "
                "(m.legacy_code IS NULL OR "
                "r.classification_ref IS DISTINCT FROM m.qualified_ref OR "
                "r.classification_version IS DISTINCT FROM m.definition_version OR "
                "r.classification_definition_id IS DISTINCT FROM m.definition_id OR "
                "(m.tenant_id IS NOT NULL AND r.tenant_id <> m.tenant_id))) "
                "OR (r.classification_ref IS NOT NULL AND "
                "(r.classification_version IS NULL OR "
                "r.classification_definition_id IS NULL))"
            ).fetchone()
            assert inconsistent_row is not None
            inconsistent_references[table] = inconsistent_row["n"]
        unresolved_row = connection.execute(
            "SELECT count(*) AS n FROM platform_gov.data_classifications d "
            "LEFT JOIN platform_gov.classification_legacy_mappings m "
            "ON m.legacy_code = d.code WHERE m.legacy_code IS NULL"
        ).fetchone()
        assert unresolved_row is not None
        unresolved = unresolved_row["n"]
        changed_meaning_row = connection.execute(
            "SELECT count(*) AS n FROM platform_gov.data_classifications d "
            "JOIN platform_gov.classification_legacy_mappings m "
            "ON m.legacy_code = d.code WHERE m.legacy_description_sha256 "
            "IS DISTINCT FROM encode(sha256(convert_to(d.description, 'UTF8')), 'hex')"
        ).fetchone()
        assert changed_meaning_row is not None
        changed_mapping_meaning_count = changed_meaning_row["n"]
        output_rows = [
            {
                "code": row["code"],
                "name": row["name"],
                "sensitivity_level": row["sensitivity_level"],
                "description_preview": row["description_preview"],
                "description_length": row["description_length"],
                "description_sha256": row["description_sha256"],
                "tag_count": row["tag_count"],
                "retention_count": row["retention_count"],
                "referencing_tenant_count": row["tenant_count"],
                "approved_ref": row["qualified_ref"],
                "approved_definition_id": str(row["definition_id"])
                if row["definition_id"] is not None
                else None,
                "approved_version": row["definition_version"],
                "approved_description_sha256": row["approved_description_sha256"],
                "approved_tenant_id": str(row["tenant_id"])
                if row["tenant_id"] is not None
                else None,
                "provenance": "APPROVED_MAPPING"
                if row["qualified_ref"]
                else "UNKNOWN_REVIEW_REQUIRED",
            }
            for row in rows[:_LIMIT]
        ]
        truncated = legacy_count > _LIMIT or len(collisions) > _LIMIT
        return {
            "status": "BLOCK"
            if unresolved
            or collisions
            or any(orphans.values())
            or any(inconsistent_references.values())
            or changed_mapping_meaning_count
            else "PASS",
            "legacy_total": legacy_count,
            "unresolved_total": unresolved,
            "collision_sample": [dict(row) for row in collisions[:_LIMIT]],
            "orphan_counts": orphans,
            "inconsistent_reference_counts": inconsistent_references,
            "changed_mapping_meaning_count": changed_mapping_meaning_count,
            "truncated": truncated,
            "rows": output_rows,
            "note": (
                "Unmapped meanings and tenant provenance require operator review; "
                "counts do not infer ownership."
            ),
        }


def _load_reviewed_file(path: Path) -> list[dict[str, object]]:
    data: object = json.loads(path.read_text(encoding="utf-8"))
    if type(data) is not dict:
        raise ValueError("Reviewed mapping file has an invalid schema")
    data_values = cast(dict[str, object], data)
    if set(data_values) != {"reviewed_mappings"}:
        raise ValueError("Reviewed mapping file has an invalid schema")
    entries = data_values["reviewed_mappings"]
    if type(entries) is not list:
        raise ValueError("Reviewed mapping count is invalid or exceeds the bound")
    entry_values = cast(list[object], entries)
    if len(entry_values) > 10000:
        raise ValueError("Reviewed mapping count is invalid or exceeds the bound")
    required = {
        "legacy_code",
        "legacy_name",
        "legacy_sensitivity_level",
        "legacy_description_sha256",
        "qualified_ref",
        "definition_id",
        "definition_version",
        "tenant_id",
        "approved_by",
        "evidence_reference",
        "tenant_provenance",
    }
    reviewed: list[dict[str, object]] = []
    for entry in entry_values:
        if type(entry) is not dict:
            raise ValueError("Reviewed mapping entry has an invalid schema")
        entry = cast(dict[str, object], entry)
        if set(entry) != required:
            raise ValueError("Reviewed mapping entry has an invalid schema")
        if any(
            type(entry[key]) is not str or not entry[key]
            for key in (
                "legacy_code",
                "legacy_name",
                "legacy_description_sha256",
                "qualified_ref",
                "definition_id",
                "approved_by",
                "evidence_reference",
            )
        ):
            raise ValueError("Reviewed mapping identity or evidence is missing")
        if (
            type(entry["legacy_sensitivity_level"]) is not int
            or type(entry["definition_version"]) is not int
        ):
            raise ValueError("Reviewed mapping version or sensitivity is invalid")
        if entry["definition_version"] <= 0:
            raise ValueError("Reviewed mapping version must be positive")
        digest = cast(str, entry["legacy_description_sha256"])
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError("Reviewed legacy description fingerprint is invalid")
        if entry["tenant_id"] is not None and (
            type(entry["tenant_id"]) is not str or not entry["tenant_id"]
        ):
            raise ValueError("Reviewed mapping tenant is invalid")
        if entry["tenant_id"] is None and entry["tenant_provenance"] is not None:
            raise ValueError("Canonical mapping cannot claim tenant provenance")
        if entry["tenant_id"] is not None and (
            type(entry["tenant_provenance"]) is not str or not entry["tenant_provenance"]
        ):
            raise ValueError("Tenant mapping requires deterministic provenance evidence")
        reviewed.append(entry)
    return reviewed


def apply_reviewed_mapping(connection: psycopg.Connection[Any], path: Path) -> int:
    """Verify all rows and backfill both reference tables in one transaction."""
    entries = _load_reviewed_file(path)
    codes = [str(entry["legacy_code"]) for entry in entries]
    if len(codes) != len(set(codes)):
        raise ValueError("Duplicate legacy mapping is ambiguous")
    with connection.transaction():
        connection.execute("SELECT pg_advisory_xact_lock(hashtextextended('gov-0003-map', 0))")
        count_row = connection.execute(
            "SELECT count(*) AS n FROM platform_gov.data_classifications"
        ).fetchone()
        assert count_row is not None
        if count_row["n"] > 10000:
            raise ValueError("Legacy classification catalog exceeds reviewed mapping bound")
        legacy_rows = connection.execute(
            "SELECT code, name, sensitivity_level, "
            "encode(sha256(convert_to(description, 'UTF8')), 'hex') "
            "AS description_sha256 "
            "FROM platform_gov.data_classifications ORDER BY code FOR SHARE"
        ).fetchall()
        legacy = {row["code"]: row for row in legacy_rows}
        if set(legacy) != set(codes):
            raise ValueError("Reviewed mapping must cover every legacy row exactly once")
        for entry in entries:
            code = str(entry["legacy_code"])
            row = legacy[code]
            if (
                row["name"] != entry["legacy_name"]
                or row["sensitivity_level"] != entry["legacy_sensitivity_level"]
                or row["description_sha256"] != entry["legacy_description_sha256"]
            ):
                raise ValueError(f"Legacy meaning changed since review: {code}")
            tenant = UUID(str(entry["tenant_id"])) if entry["tenant_id"] is not None else None
            reference = str(entry["qualified_ref"])
            kind, _ = parse_ref(reference, tenant or UUID(int=0))
            if (kind == "core") != (tenant is None):
                raise ValueError(f"Mapping namespace/tenant mismatch: {code}")
            definition_id = UUID(str(entry["definition_id"]))
            version = int(str(entry["definition_version"]))
            if kind == "core":
                target = connection.execute(
                    "SELECT d.name, v.sensitivity_level FROM "
                    "platform_gov.classification_definitions d JOIN "
                    "platform_gov.classification_versions v ON v.definition_id = d.id "
                    "WHERE d.id = %s AND d.qualified_ref = %s AND v.version = %s",
                    (definition_id, reference, version),
                ).fetchall()
            else:
                target = connection.execute(
                    "SELECT d.name, v.sensitivity_level FROM "
                    "platform_gov.tenant_classifications d JOIN "
                    "platform_gov.tenant_classification_versions v ON "
                    "v.tenant_id = d.tenant_id AND v.definition_id = d.id "
                    "WHERE d.id = %s AND d.tenant_id = %s "
                    "AND d.qualified_ref = %s AND v.version = %s",
                    (definition_id, tenant, reference, version),
                ).fetchall()
                for table in ("sensitive_field_tags", "retention_policies"):
                    foreign_use = connection.execute(
                        f"SELECT 1 FROM platform_gov.{table} "
                        "WHERE classification_code = %s AND tenant_id <> %s LIMIT 1",
                        (code, tenant),
                    ).fetchone()
                    if foreign_use is not None:
                        raise ValueError(
                            f"Legacy tenant provenance conflicts with references: {code}"
                        )
            if (
                len(target) != 1
                or target[0]["name"] != row["name"]
                or target[0]["sensitivity_level"] != row["sensitivity_level"]
            ):
                raise ValueError(f"Reviewed target changes legacy meaning: {code}")
            existing = connection.execute(
                "SELECT qualified_ref, definition_id, definition_version, tenant_id, "
                "legacy_description_sha256 "
                "FROM platform_gov.classification_legacy_mappings WHERE legacy_code = %s",
                (code,),
            ).fetchone()
            if existing is not None and (
                existing["qualified_ref"],
                existing["definition_id"],
                existing["definition_version"],
                existing["tenant_id"],
                existing["legacy_description_sha256"],
            ) != (reference, definition_id, version, tenant, row["description_sha256"]):
                raise ValueError(f"Existing approved mapping differs: {code}")
            if existing is None:
                connection.execute(
                    "INSERT INTO platform_gov.classification_legacy_mappings "
                    "(legacy_code, qualified_ref, definition_id, definition_version, "
                    "legacy_description_sha256, tenant_id, approved_by, "
                    "evidence_reference, tenant_provenance) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        code,
                        reference,
                        definition_id,
                        version,
                        row["description_sha256"],
                        tenant,
                        entry["approved_by"],
                        entry["evidence_reference"],
                        entry["tenant_provenance"],
                    ),
                )
            for table in ("sensitive_field_tags", "retention_policies"):
                conflicting = connection.execute(
                    f"SELECT 1 FROM platform_gov.{table} WHERE classification_code = %s "
                    "AND classification_ref IS NOT NULL AND "
                    "(classification_ref IS DISTINCT FROM %s "
                    "OR classification_version IS DISTINCT FROM %s "
                    "OR classification_definition_id IS DISTINCT FROM %s) LIMIT 1",
                    (code, reference, version, definition_id),
                ).fetchone()
                if conflicting is not None:
                    raise ValueError(f"Existing qualified reference conflicts with review: {code}")
                connection.execute(
                    f"UPDATE platform_gov.{table} SET classification_ref = %s, "
                    "classification_version = %s, classification_definition_id = %s "
                    "WHERE classification_code = %s AND classification_ref IS NULL",
                    (reference, version, definition_id, code),
                )
        for table in ("sensitive_field_tags", "retention_policies"):
            if (
                connection.execute(
                    f"SELECT 1 FROM platform_gov.{table} WHERE classification_code IS NOT NULL "
                    "AND (classification_ref IS NULL OR classification_version IS NULL "
                    "OR classification_definition_id IS NULL) LIMIT 1"
                ).fetchone()
                is not None
            ):
                raise ValueError(f"Unmapped legacy references remain in {table}")
    return len(entries)


def main() -> None:
    parser = argparse.ArgumentParser(prog="businessos-classification-legacy")
    parser.add_argument("action", choices=("preflight", "apply"))
    parser.add_argument("--reviewed-file", type=Path)
    args = parser.parse_args()
    url = os.getenv("BOS_MIGRATION_DATABASE_URL")
    if not url:
        parser.error("BOS_MIGRATION_DATABASE_URL is required")
    if args.action == "apply" and args.reviewed_file is None:
        parser.error("--reviewed-file is required for apply")
    with _connection(url) as connection:
        if args.action == "preflight":
            print(json.dumps(preflight(connection), sort_keys=True))
        else:
            count = apply_reviewed_mapping(connection, args.reviewed_file)
            print(json.dumps({"status": "APPLIED", "mapping_count": count}, sort_keys=True))


if __name__ == "__main__":
    main()
