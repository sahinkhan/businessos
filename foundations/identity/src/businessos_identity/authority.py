"""Identity-owned membership read for an existing framework transaction.

Callers in another foundation can lock authority without reading Identity's
private table themselves or opening a second Unit of Work.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import select

from businessos.sdk import BusinessOSError, TransactionalPersistence

from .contracts import MembershipRecord, PrincipalReference
from .models import MEMBERSHIPS


async def lock_membership_for_authority(
    persistence: TransactionalPersistence,
    tenant_id: UUID,
    principal_id: UUID,
    principal_type: Literal["user", "service_account", "device"],
) -> MembershipRecord:
    """Hold a shared row lock until the caller's command transaction completes."""
    result = await persistence.execute(
        select(MEMBERSHIPS)
        .where(
            MEMBERSHIPS.c.tenant_id == tenant_id,
            MEMBERSHIPS.c.principal_id == principal_id,
            MEMBERSHIPS.c.principal_type == principal_type,
        )
        .with_for_update(read=True)
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise BusinessOSError("not_found", "Membership not found", status_code=404)
    return MembershipRecord(
        membership_id=row["id"],
        tenant_id=row["tenant_id"],
        principal_id=row["principal_id"],
        principal_type=row["principal_type"],
        status=row["status"],
        valid_from=row["valid_from"],
        valid_until=row["valid_until"],
        scopes=tuple(row["scopes"]),
    )


class DatabaseMembershipAuthority:
    """Identity's bounded same-transaction membership authority port."""

    async def lock_many(
        self,
        persistence: TransactionalPersistence,
        tenant_id: UUID,
        principals: tuple[PrincipalReference, ...],
        evaluated_at: datetime,
        valid_from: datetime,
        valid_until: datetime,
    ) -> tuple[MembershipRecord, ...]:
        if valid_until <= valid_from or evaluated_at.tzinfo is None:
            raise BusinessOSError("forbidden", "Invalid authority interval", status_code=403)
        records: list[MembershipRecord] = []
        for principal in sorted(set(principals)):
            try:
                record = await lock_membership_for_authority(
                    persistence, tenant_id, principal.principal_id, principal.principal_type
                )
            except BusinessOSError as error:
                if error.code == "not_found":
                    raise BusinessOSError(
                        "forbidden", "Active membership required", status_code=403
                    ) from None
                raise
            if (
                not record.is_effective(evaluated_at)
                or (record.valid_from is not None and record.valid_from > valid_from)
                or (record.valid_until is not None and record.valid_until < valid_until)
            ):
                raise BusinessOSError("forbidden", "Active membership required", status_code=403)
            records.append(record)
        return tuple(records)
