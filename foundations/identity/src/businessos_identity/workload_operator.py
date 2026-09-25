"""Installation-operator workload administration; no tenant API is exposed.

Run with ``python -m businessos_identity.workload_operator`` using the isolated
``BOS_OPERATIONS_DATABASE_URL``. The credential file is supplied by the
operator and never written to PostgreSQL or command output.
"""

import argparse
import hashlib
import os
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

_PURPOSES = frozenset({"worker-startup", "event-delivery", "subscriber-sync", "event-publisher"})


def _credential_digest(path: Path) -> bytes:
    with path.open("rb") as source:
        credential = source.read(4097)
    if not 32 <= len(credential) <= 4096:
        raise ValueError("Workload credential file must contain 32 to 4096 bytes")
    return hashlib.sha256(credential).digest()


def _arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="businessos-identity-workload")
    actions = parser.add_subparsers(dest="action", required=True)
    for name in ("register", "rotate", "disable", "set-authority"):
        action = actions.add_parser(name)
        action.add_argument("installation_id", type=UUID)
        action.add_argument("workload_id", type=UUID)
        if name == "register":
            action.add_argument("--name", required=True)
        if name in {"register", "rotate"}:
            action.add_argument("--credential-reference", required=True)
            action.add_argument("--credential-file", type=Path, required=True)
        if name in {"register", "set-authority"}:
            action.add_argument("--process-class", required=True)
            action.add_argument("--purpose", action="append", required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = _arguments(argv)
    url = os.getenv("BOS_OPERATIONS_DATABASE_URL")
    if not url or make_url(url).username != "businessos_ops":
        raise SystemExit("BOS_OPERATIONS_DATABASE_URL must use businessos_ops")
    purposes: tuple[str, ...] = ()
    digest = b""
    if args.action in {"register", "set-authority"}:
        purposes = tuple(sorted(set(args.purpose)))
        if (
            not purposes
            or not set(purposes) <= _PURPOSES
            or not 1 <= len(args.process_class) <= 100
        ):
            raise SystemExit("Invalid workload process class or purpose")
    if args.action in {"register", "rotate"}:
        if not 1 <= len(args.credential_reference) <= 500:
            raise SystemExit("Invalid workload credential reference")
        digest = _credential_digest(args.credential_file)
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            if connection.scalar(text("SELECT current_user")) != "businessos_ops":
                raise SystemExit("Workload administration requires businessos_ops")
            key = {"installation_id": args.installation_id, "workload_id": args.workload_id}
            if args.action == "register":
                if not 1 <= len(args.name) <= 200:
                    raise SystemExit("Invalid workload name")
                result = connection.execute(
                    text(
                        "INSERT INTO platform_identity.installation_workloads "
                        "(installation_id, workload_id, name, active, process_class, "
                        "allowed_purposes, credential_reference, credential_digest, "
                        "credential_generation) VALUES (:installation_id, :workload_id, "
                        ":name, true, :process_class, :purposes, :reference, :digest, 1)"
                    ),
                    {
                        **key,
                        "name": args.name,
                        "process_class": args.process_class,
                        "purposes": list(purposes),
                        "reference": args.credential_reference,
                        "digest": digest,
                    },
                )
            elif args.action == "rotate":
                result = connection.execute(
                    text(
                        "UPDATE platform_identity.installation_workloads SET "
                        "credential_reference=:reference, credential_digest=:digest, "
                        "credential_generation=credential_generation+1, rotated_at=now(), "
                        "updated_at=now() WHERE installation_id=:installation_id "
                        "AND workload_id=:workload_id AND active AND revoked_at IS NULL"
                    ),
                    {**key, "reference": args.credential_reference, "digest": digest},
                )
            elif args.action == "disable":
                result = connection.execute(
                    text(
                        "UPDATE platform_identity.installation_workloads SET "
                        "active=false, revoked_at=now(), updated_at=now() "
                        "WHERE installation_id=:installation_id AND workload_id=:workload_id "
                        "AND active"
                    ),
                    key,
                )
            else:
                result = connection.execute(
                    text(
                        "UPDATE platform_identity.installation_workloads SET "
                        "process_class=:process_class, allowed_purposes=:purposes, "
                        "updated_at=now() "
                        "WHERE installation_id=:installation_id AND workload_id=:workload_id "
                        "AND active AND revoked_at IS NULL"
                    ),
                    {**key, "process_class": args.process_class, "purposes": list(purposes)},
                )
            if result.rowcount != 1:
                raise SystemExit("Workload operation did not affect exactly one row")
    finally:
        engine.dispose()
    print(f"Workload {args.action} complete")


if __name__ == "__main__":
    main()
