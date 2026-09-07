"""Installed-wheel Uvicorn + worker proof using a newly created disposable database.

Run inside the production-derived migration-smoke image, with the four
BOS_TEST_DATABASE_* URLs and isolated Redis/NATS/S3 test endpoints configured.
Never use an existing application database as this harness's target.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

import boto3
import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

from businessos.database_admin import provision_tenant_login

IDENTITY = '''from uuid import UUID
import os
from businessos.sdk import RequestContext, TenantContext
class ContextResolver:
    async def resolve(self, identity):
        tenant = None
        if identity.headers.get("authorization") == "Bearer " + os.environ["FIXTURE_TOKEN"]:
            tenant = TenantContext(UUID(os.environ["FIXTURE_INSTALLATION"]), UUID(os.environ["FIXTURE_TENANT"]), UUID(os.environ["FIXTURE_PRINCIPAL"]))
        return RequestContext(correlation_id=identity.correlation_id, trace_id=identity.trace_id, tenant=tenant)
class Policy:
    async def is_allowed(self, principal_id, tenant, permission):
        return str(principal_id) == os.environ["FIXTURE_PRINCIPAL"] and permission in {"example.phase1-proof.read", "example.phase1-proof.write"}
'''


def main() -> None:
    admin_base = os.environ["BOS_TEST_DATABASE_ADMIN_URL"]
    database_name = "businessos_installed_" + uuid4().hex
    tenant_id, installation_id, principal_id = uuid4(), uuid4(), uuid4()
    token = "fixture-canary-" + uuid4().hex
    password = "fixture-db-canary-" + uuid4().hex
    processes: list[subprocess.Popen[bytes]] = []
    bucket = "businessos-installed-" + uuid4().hex
    storage = boto3.client(
        "s3", endpoint_url=os.environ["BOS_TEST_S3_ENDPOINT"],
        aws_access_key_id=os.environ["BOS_TEST_S3_ACCESS_KEY"],
        aws_secret_access_key=os.environ["BOS_TEST_S3_SECRET_KEY"],
    )
    storage.create_bucket(Bucket=bucket)

    def url(kind: str, *, sqlalchemy: bool = True) -> str:
        value = make_url(os.environ[f"BOS_TEST_DATABASE_{kind}_URL"]).set(database=database_name)
        if sqlalchemy:
            value = value.set(drivername="postgresql+psycopg")
        return value.render_as_string(hide_password=False)

    with psycopg.connect(admin_base, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {} OWNER businessos_migrator").format(sql.Identifier(database_name)))
    try:
        with psycopg.connect(url("ADMIN", sqlalchemy=False)) as connection:
            connection.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO businessos_app, businessos_ops").format(sql.Identifier(database_name)))
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            (temporary / "fixture_identity.py").write_text(IDENTITY)
            env = dict(os.environ)
            env.update({
                "PYTHONPATH": directory,
                "BOS_ENVIRONMENT": "production",
                "BOS_MIGRATION_DATABASE_URL": url("MIGRATION"),
                "BOS_DATABASE_URL": url("RUNTIME"),
                "BOS_CONTEXT_RESOLVER_FACTORY": "fixture_identity:ContextResolver",
                "BOS_POLICY_EVALUATOR_FACTORY": "fixture_identity:Policy",
                "BOS_S3_BUCKET": bucket,
                "BOS_S3_ENDPOINT_URL": os.environ["BOS_TEST_S3_ENDPOINT"],
                "BOS_S3_ACCESS_KEY": os.environ["BOS_TEST_S3_ACCESS_KEY"],
                "BOS_S3_SECRET_KEY": os.environ["BOS_TEST_S3_SECRET_KEY"],
                "FIXTURE_TOKEN": token, "FIXTURE_TENANT": str(tenant_id),
                "FIXTURE_INSTALLATION": str(installation_id), "FIXTURE_PRINCIPAL": str(principal_id),
            })
            log_path = temporary / "runtime.log"
            with log_path.open("wb") as log:
                def migrate(action: str, revision: str) -> None:
                    subprocess.run(["businessos", "migrate", action, revision], env=env, cwd=directory, stdout=log, stderr=log, check=True, timeout=30)

                migrate("upgrade", "heads")
                with psycopg.connect(url("ADMIN", sqlalchemy=False)) as connection:
                    role = provision_tenant_login(connection, tenant_id=tenant_id, password=password)
                tenant_url = make_url(url("RUNTIME")).set(username=role, password=password).render_as_string(hide_password=False)
                env["BOS_TENANT_DATABASE_URLS"] = json.dumps({str(tenant_id): tenant_url})
                env.update({
                    "BOS_EVENT_WORKER_RUNTIME_DATABASE_URL": url("RUNTIME"),
                    "BOS_EVENT_WORKER_OPERATIONS_DATABASE_URL": url("OPERATIONS"),
                    "BOS_EVENT_WORKER_TENANT_DATABASE_URLS": env["BOS_TENANT_DATABASE_URLS"],
                    "BOS_EVENT_WORKER_NATS_URL": os.environ["BOS_TEST_NATS_URL"],
                    "BOS_EVENT_WORKER_INSTALLATION_ID": str(installation_id),
                    "BOS_EVENT_WORKER_PRINCIPAL_ID": str(principal_id),
                    "BOS_EVENT_WORKER_PERMISSIONS": "example.phase1-proof.read,example.phase1-proof.write",
                    "BOS_EVENT_WORKER_DURABLE_NAME": database_name,
                    "BOS_EVENT_WORKER_S3_BUCKET": bucket,
                    "BOS_EVENT_WORKER_S3_ENDPOINT_URL": os.environ["BOS_TEST_S3_ENDPOINT"],
                    "BOS_EVENT_WORKER_S3_ACCESS_KEY": os.environ["BOS_TEST_S3_ACCESS_KEY"],
                    "BOS_EVENT_WORKER_S3_SECRET_KEY": os.environ["BOS_TEST_S3_SECRET_KEY"],
                })

                def start(command: list[str]) -> subprocess.Popen[bytes]:
                    process = subprocess.Popen(command, env=env, cwd=directory, stdout=log, stderr=log)
                    processes.append(process)
                    return process

                def stop(process: subprocess.Popen[bytes]) -> None:
                    process.terminate()
                    process.wait(timeout=15)
                    processes.remove(process)

                def http(path: str, payload: dict[str, str] | None = None, *, authenticated: bool = True) -> tuple[int, object]:
                    headers = {"content-type": "application/json"}
                    if authenticated:
                        headers["authorization"] = "Bearer " + token
                    request = Request("http://127.0.0.1:18080" + path, data=json.dumps(payload).encode() if payload else None, headers=headers)
                    try:
                        with urlopen(request, timeout=2) as response:
                            return response.status, json.load(response)
                    except HTTPError as error:
                        return error.code, json.load(error)

                def wait_http() -> None:
                    deadline = time.monotonic() + 15
                    while time.monotonic() < deadline:
                        try:
                            if http("/readyz")[0] == 200:
                                return
                        except URLError:
                            pass
                        time.sleep(0.1)
                    raise RuntimeError("Installed Uvicorn startup failed")

                web = start([sys.executable, "-m", "uvicorn", "businessos.asgi:application", "--host", "127.0.0.1", "--port", "18080"])
                wait_http()
                assert http("/diagnostics/modules")[1]["modules"][0]["state"] == "enabled"
                assert http("/proof/value", authenticated=False)[0] == 401
                assert http("/proof/value", {"value": "installed-proof", "command_id": str(uuid4())})[0] == 202
                assert http("/proof/value") == (200, {"value": "installed-proof"})
                worker = start(["businessos", "events", "run"])
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    try:
                        response = storage.get_object(Bucket=bucket, Key=f"tenant/{tenant_id}/phase1-proof/value.txt")
                        assert response["Body"].read() == b"installed-proof"
                        break
                    except storage.exceptions.NoSuchKey:
                        time.sleep(0.1)
                else:
                    raise RuntimeError("Installed worker did not project proof event")
                stop(worker)
                stop(web)
                env["BOS_DISABLED_MODULES"] = '["example.phase1-proof"]'
                web = start([sys.executable, "-m", "uvicorn", "businessos.asgi:application", "--host", "127.0.0.1", "--port", "18080"])
                wait_http()
                assert http("/diagnostics/modules")[1]["modules"][0]["state"] == "disabled"
                assert http("/proof/value")[0] == 404
                stop(web)
                migrate("downgrade", "base")
                migrate("upgrade", "heads")
                with psycopg.connect(url("MIGRATION", sqlalchemy=False)) as connection:
                    assert connection.execute("SELECT version_num FROM alembic_version").fetchall() == [("proof_0004",)]
                    assert connection.execute("SELECT revision_ids FROM platform_module.installed_module_migrations").fetchone()[0][-1] == "proof_0004"
            logs = log_path.read_text()
            assert token not in logs and password not in logs
        print("Installed wheels: Uvicorn API, authorization, worker projection, disable, migration replay and log canaries passed")
    finally:
        for process in processes:
            process.kill()
            process.wait(timeout=10)
        with psycopg.connect(admin_base, autocommit=True) as connection:
            connection.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s", (database_name,))
            connection.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database_name)))
        for item in storage.list_objects_v2(Bucket=bucket).get("Contents", []):
            storage.delete_object(Bucket=bucket, Key=item["Key"])
        storage.delete_bucket(Bucket=bucket)


if __name__ == "__main__":
    main()
