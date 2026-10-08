from typing import Any

import pytest
from scripts.check_event_worker_deployment import validate_worker_deployment


def _configuration(environment: dict[str, Any]) -> dict[str, object]:
    return {
        "services": {
            "event-worker": {
                "profiles": ["events"],
                "environment": environment,
            }
        }
    }


def test_ordinary_worker_resolved_environment_accepts_only_delivery_credentials() -> None:
    validate_worker_deployment(
        _configuration(
            {
                "BOS_EVENT_WORKER_RUNTIME_DATABASE_URL": (
                    "postgresql+psycopg://businessos_worker:worker@db/businessos"
                ),
                "BOS_EVENT_WORKER_OPERATIONS_DATABASE_URL": (
                    "postgresql+psycopg://businessos_ops:operations@db/businessos"
                ),
            }
        )
    )


@pytest.mark.parametrize(
    "environment",
    (
        {"BOS_EVENT_WORKER_UI_PUBLICATION_DATABASE_URL": ""},
        {"BOS_UI_PUBLICATION_DATABASE_URL": "private-url"},
        {"BOS_UI_PUBLICATION_PASSWORD": "private-password"},
        {
            "BOS_EVENT_WORKER_RUNTIME_DATABASE_URL": (
                "postgresql+psycopg://businessos_ui_publication:private@db/businessos"
            )
        },
        {"UNKNOWN_CREDENTIAL": "worker-deployment-publication-credential-canary"},
    ),
)
def test_resolved_worker_environment_rejects_private_credential_distribution(
    environment: dict[str, Any],
) -> None:
    with pytest.raises(ValueError, match="private publication authority"):
        validate_worker_deployment(_configuration(environment))


def test_resolved_worker_deployment_requires_ordinary_events_profile() -> None:
    with pytest.raises(ValueError, match="events-profile worker is missing"):
        validate_worker_deployment({"services": {}})
