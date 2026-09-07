"""Deterministic BusinessOS route registry and matcher."""

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from businessos.activation import ContributionGate, ContributionGeneration
from businessos.di import RequestDependencyScope
from businessos.errors import ConflictError, MethodNotAllowedError, NotFoundError
from businessos.http.request import Request
from businessos.http.response import Response

RouteHandler = Callable[[Request, RequestDependencyScope], Awaitable[Response]]

_PARAMETER = re.compile(r"^\{([A-Za-z_][A-Za-z0-9_]*)\}$")


@dataclass(frozen=True, slots=True)
class Route:
    method: str
    path: str
    handler: RouteHandler
    name: str
    permission: str | None = None
    owner: str | None = None
    generation: ContributionGeneration | None = None


@dataclass(frozen=True, slots=True)
class RouteMatch:
    route: Route
    path_params: dict[str, str]


@dataclass(frozen=True, slots=True)
class _CompiledRoute:
    route: Route
    segments: tuple[str, ...]
    parameter_names: tuple[str | None, ...]
    shape: tuple[str, ...]
    dynamic_count: int

    def match(self, path_segments: tuple[str, ...]) -> dict[str, str] | None:
        if len(path_segments) != len(self.segments):
            return None
        parameters: dict[str, str] = {}
        for expected, parameter, actual in zip(
            self.segments, self.parameter_names, path_segments, strict=True
        ):
            if parameter is None and expected != actual:
                return None
            if parameter is not None:
                parameters[parameter] = actual
        return parameters


class Router:
    """Framework-owned router with conflict rejection and stable precedence."""

    def __init__(self, gate: ContributionGate | None = None) -> None:
        self._routes: dict[tuple[str, tuple[str, ...]], _CompiledRoute] = {}
        self._gate = gate

    @property
    def routes(self) -> tuple[Route, ...]:
        return tuple(compiled.route for compiled in self._ordered_routes())

    def add_route(
        self,
        method: str,
        path: str,
        handler: RouteHandler,
        *,
        name: str | None = None,
        permission: str | None = None,
        owner: str | None = None,
        generation: ContributionGeneration | None = None,
    ) -> Route:
        compiled = self._compile(
            Route(
                method=method.upper(),
                path=path,
                handler=handler,
                name=name or f"{method.lower()}:{path}",
                permission=permission,
                owner=owner,
                generation=generation,
            )
        )
        key = (compiled.route.method, compiled.shape)
        if key in self._routes:
            raise ConflictError(
                f"Route conflicts with an existing route: {compiled.route.method} {path}"
            )
        self._routes[key] = compiled
        return compiled.route

    def match(self, method: str, path: str) -> RouteMatch:
        path_segments = self._split_path(path)
        allowed: set[str] = set()
        for compiled in self._ordered_routes():
            parameters = compiled.match(path_segments)
            if parameters is None:
                continue
            if compiled.route.method == method.upper():
                return RouteMatch(compiled.route, parameters)
            allowed.add(compiled.route.method)
        if allowed:
            raise MethodNotAllowedError(tuple(sorted(allowed)))
        raise NotFoundError()

    def _ordered_routes(self) -> tuple[_CompiledRoute, ...]:
        return tuple(
            sorted(
                (
                    compiled
                    for compiled in self._routes.values()
                    if self._gate is None or self._gate.is_active(compiled.route.generation)
                ),
                key=lambda item: (
                    item.dynamic_count,
                    -len(item.segments),
                    item.route.path,
                    item.route.method,
                ),
            )
        )

    def remove_owner_generation(self, generation: ContributionGeneration) -> None:
        self._routes = {
            key: compiled
            for key, compiled in self._routes.items()
            if compiled.route.generation != generation
        }

    @classmethod
    def _compile(cls, route: Route) -> _CompiledRoute:
        segments = cls._split_path(route.path)
        parameter_names: list[str | None] = []
        shape: list[str] = []
        seen: set[str] = set()
        for segment in segments:
            match = _PARAMETER.match(segment)
            if match is None:
                if "{" in segment or "}" in segment:
                    raise ValueError(f"Invalid path segment: {segment}")
                parameter_names.append(None)
                shape.append(segment)
                continue
            parameter = match.group(1)
            if parameter in seen:
                raise ValueError(f"Duplicate route parameter: {parameter}")
            seen.add(parameter)
            parameter_names.append(parameter)
            shape.append("{}")
        return _CompiledRoute(
            route=route,
            segments=segments,
            parameter_names=tuple(parameter_names),
            shape=tuple(shape),
            dynamic_count=sum(value is not None for value in parameter_names),
        )

    @staticmethod
    def _split_path(path: str) -> tuple[str, ...]:
        if not path.startswith("/"):
            raise ValueError("Route paths must begin with '/'")
        if path != "/" and path.endswith("/"):
            path = path[:-1]
        return tuple(segment for segment in path.split("/") if segment)
