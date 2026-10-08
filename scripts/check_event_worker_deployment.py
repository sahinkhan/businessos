"""Verify the resolved ordinary worker deployment excludes publication authority."""

import json
import os
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import cast

_PRIVATE_URL_CANARY = "postgresql+psycopg://businessos_ui_publication:canary@db/businessos"
_PRIVATE_PASSWORD_CANARY = "worker-deployment-publication-credential-canary"


def validate_worker_deployment(configuration: Mapping[str, object]) -> None:
    """Inspect resolved values so interpolation/defaults cannot hide a credential."""
    services = configuration.get("services")
    if not isinstance(services, dict):
        raise ValueError("Resolved Compose services are missing")
    worker = services.get("event-worker")
    if not isinstance(worker, dict) or "events" not in worker.get("profiles", ()):
        raise ValueError("The ordinary events-profile worker is missing")
    environment = worker.get("environment")
    if not isinstance(environment, dict):
        raise ValueError("Resolved worker environment is missing")
    for key, value in environment.items():
        if "UI_PUBLICATION" in str(key) or any(
            marker in str(value)
            for marker in (
                "businessos_ui_publication",
                _PRIVATE_URL_CANARY,
                _PRIVATE_PASSWORD_CANARY,
            )
        ):
            raise ValueError("Ordinary event worker receives private publication authority")


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    # Verify both inherited variable namespaces and Compose password defaults.
    environment["BOS_UI_PUBLICATION_DATABASE_URL"] = _PRIVATE_URL_CANARY
    environment["BOS_EVENT_WORKER_UI_PUBLICATION_DATABASE_URL"] = _PRIVATE_URL_CANARY
    environment["BOS_UI_PUBLICATION_PASSWORD"] = _PRIVATE_PASSWORD_CANARY
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--file",
            str(root / "compose.yaml"),
            "--profile",
            "events",
            "config",
            "--format",
            "json",
        ],
        cwd=root,
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    configuration = json.loads(result.stdout)
    if not isinstance(configuration, dict):
        raise ValueError("Resolved Compose configuration is invalid")
    validate_worker_deployment(cast(Mapping[str, object], configuration))
    print("Ordinary events-profile worker: private publication credential excluded")


if __name__ == "__main__":
    main()
