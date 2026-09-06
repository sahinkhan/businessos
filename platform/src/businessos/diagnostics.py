"""Liveness, readiness and version diagnostics."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from businessos.di import RequestDependencyScope
from businessos.http import Request, Response, Router

ReadinessCheck = Callable[[], Awaitable[None]]
ModuleSnapshot = Callable[[], tuple[dict[str, object], ...]]


@dataclass(frozen=True, slots=True)
class ReadinessResult:
    name: str
    ready: bool
    detail: str | None = None


class Diagnostics:
    def __init__(self, version: str, module_snapshot: ModuleSnapshot | None = None) -> None:
        self._version = version
        self._checks: dict[str, ReadinessCheck] = {}
        self._module_snapshot = module_snapshot or (lambda: ())

    def add_readiness_check(self, name: str, check: ReadinessCheck) -> None:
        if name in self._checks:
            raise ValueError(f"Readiness check already registered: {name}")
        self._checks[name] = check

    async def check_readiness(self) -> tuple[ReadinessResult, ...]:
        async def run(name: str, check: ReadinessCheck) -> ReadinessResult:
            try:
                await check()
                return ReadinessResult(name=name, ready=True)
            except Exception as exc:  # readiness converts provider failures to status
                return ReadinessResult(name=name, ready=False, detail=type(exc).__name__)

        return tuple(
            await asyncio.gather(*(run(name, self._checks[name]) for name in sorted(self._checks)))
        )

    def register_routes(self, router: Router) -> None:
        async def live(_: Request, __: RequestDependencyScope) -> Response:
            return Response.json({"status": "live"})

        async def ready(_: Request, __: RequestDependencyScope) -> Response:
            checks = await self.check_readiness()
            is_ready = all(check.ready for check in checks)
            return Response.json(
                {
                    "status": "ready" if is_ready else "not_ready",
                    "checks": [
                        {"name": item.name, "ready": item.ready, "detail": item.detail}
                        for item in checks
                    ],
                },
                status_code=200 if is_ready else 503,
            )

        async def version(_: Request, __: RequestDependencyScope) -> Response:
            return Response.json({"version": self._version})

        async def modules(_: Request, __: RequestDependencyScope) -> Response:
            return Response.json({"modules": list(self._module_snapshot())})

        router.add_route("GET", "/livez", live, name="platform.liveness")
        router.add_route("GET", "/readyz", ready, name="platform.readiness")
        router.add_route("GET", "/version", version, name="platform.version")
        router.add_route("GET", "/diagnostics/modules", modules, name="platform.modules")
