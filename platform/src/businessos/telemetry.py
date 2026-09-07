"""OpenTelemetry bootstrap owned by the protected runtime."""

from collections.abc import Generator, Mapping
from contextlib import contextmanager

from opentelemetry import propagate, trace
from opentelemetry.context import Context
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import SpanKind

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


def inject_trace_context() -> dict[str, str]:
    """Serialize only standard propagation fields from the current span."""
    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    return carrier


def _extracted(carrier: Mapping[str, str]) -> Context:
    return propagate.extract(dict(carrier))


def _trace_id() -> str:
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return "0" * 32
    return f"{span_context.trace_id:032x}"


@contextmanager
def server_span(method: str, path: str, headers: Mapping[str, str]) -> Generator[str]:
    tracer = trace.get_tracer("businessos.http")
    with tracer.start_as_current_span(
        f"{method.upper()} {path}",
        context=_extracted(headers),
        kind=SpanKind.SERVER,
        attributes={"http.request.method": method.upper(), "url.path": path},
    ):
        yield _trace_id()


@contextmanager
def dispatch_span(kind: str, name: str) -> Generator[None]:
    tracer = trace.get_tracer("businessos.dispatch")
    with tracer.start_as_current_span(
        f"businessos.{kind} {name}",
        kind=SpanKind.INTERNAL,
        attributes={"businessos.dispatch.kind": kind, "businessos.message.type": name},
    ):
        yield


@contextmanager
def consumer_span(event_type: str, carrier: Mapping[str, str]) -> Generator[str]:
    tracer = trace.get_tracer("businessos.eventing")
    with tracer.start_as_current_span(
        f"consume {event_type}",
        context=_extracted(carrier),
        kind=SpanKind.CONSUMER,
        attributes={
            "messaging.operation.type": "process",
            "messaging.destination.name": event_type,
        },
    ):
        yield _trace_id()
