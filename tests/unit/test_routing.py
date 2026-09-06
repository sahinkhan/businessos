from businessos.di import RequestDependencyScope
from businessos.errors import ConflictError, MethodNotAllowedError, NotFoundError
from businessos.http import Request, Response, Router


async def _handler(_: Request, __: RequestDependencyScope) -> Response:
    return Response.text("ok")


def test_static_route_wins_over_parameter_route_regardless_of_registration_order() -> None:
    router = Router()
    dynamic = router.add_route("GET", "/items/{item_id}", _handler)
    static = router.add_route("GET", "/items/current", _handler)

    assert router.match("GET", "/items/current").route == static
    match = router.match("GET", "/items/123")
    assert match.route == dynamic
    assert match.path_params == {"item_id": "123"}


def test_equivalent_parameterized_routes_conflict() -> None:
    router = Router()
    router.add_route("GET", "/items/{item_id}", _handler)

    try:
        router.add_route("GET", "/items/{other_name}", _handler)
    except ConflictError as exc:
        assert exc.code == "conflict"
    else:
        raise AssertionError("Expected route conflict")


def test_router_distinguishes_not_found_and_method_not_allowed() -> None:
    router = Router()
    router.add_route("GET", "/items", _handler)

    try:
        router.match("POST", "/items")
    except MethodNotAllowedError as exc:
        assert exc.details == {"allowed_methods": ("GET",)}
    else:
        raise AssertionError("Expected method-not-allowed error")

    try:
        router.match("GET", "/missing")
    except NotFoundError as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("Expected not-found error")
