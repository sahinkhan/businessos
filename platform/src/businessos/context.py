"""Trusted execution contexts and logging propagation."""

from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from types import TracebackType
from uuid import UUID, uuid4


@dataclass(frozen=True, slots=True)
class TenantContext:
    """Trusted tenant and principal scope resolved by the platform identity boundary."""

    installation_id: UUID
    tenant_id: UUID
    principal_id: UUID
    active_company_id: UUID | None = None
    authentication_strength: str = "unspecified"
    enterprise_group_id: UUID | None = None
    legal_entity_id: UUID | None = None
    business_unit_id: UUID | None = None
    division_id: UUID | None = None
    department_id: UUID | None = None
    team_id: UUID | None = None
    region_id: UUID | None = None
    operating_site_id: UUID | None = None
    warehouse_id: UUID | None = None
    cost_center_id: UUID | None = None
    profit_center_id: UUID | None = None
    project_id: UUID | None = None
    delegation_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Framework context propagated through one request/command/query operation."""

    correlation_id: str = field(default_factory=lambda: str(uuid4()))
    trace_id: str = field(default_factory=lambda: uuid4().hex)
    tenant: TenantContext | None = None


_current_context: ContextVar[RequestContext | None] = ContextVar(
    "businessos_request_context", default=None
)


def current_request_context() -> RequestContext | None:
    """Expose current context for telemetry only; application code receives it explicitly."""
    return _current_context.get()


class bind_request_context:
    """Bind a request context for logging/telemetry and restore it reliably."""

    def __init__(self, context: RequestContext) -> None:
        self._context = context
        self._token: Token[RequestContext | None] | None = None

    def __enter__(self) -> RequestContext:
        self._token = _current_context.set(self._context)
        return self._context

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._token is not None:
            _current_context.reset(self._token)
