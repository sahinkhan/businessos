"""OpenTelemetry bootstrap owned by the protected runtime."""

from opentelemetry import trace
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider

_provider: TracerProvider | None = None


def configure_telemetry(*, service_name: str, service_version: str) -> TracerProvider:
    """Install the process tracer provider before modules are loaded."""
    global _provider
    if _provider is not None:
        return _provider
    _provider = TracerProvider(
        resource=Resource.create(
            {
                SERVICE_NAME: service_name,
                SERVICE_VERSION: service_version,
            }
        )
    )
    trace.set_tracer_provider(_provider)
    return _provider
