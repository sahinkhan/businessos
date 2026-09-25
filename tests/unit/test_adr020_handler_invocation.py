"""ADR-020 dispatcher-issued authority and reserved provider registration."""

import asyncio
from copy import copy
from dataclasses import replace

import pytest

from businessos.bootstrap import create_application
from businessos.config import Settings
from businessos.context import RequestContext
from businessos.di import DependencyKey
from businessos.errors import ConfigurationError, NotFoundError
from businessos.handler_invocation import (
    HandlerInvocationBinding,
    HandlerInvocationKind,
    validate_handler_invocation,
)
from businessos.messages import (
    Command,
    HandlingContext,
    Query,
    handler_transaction_view,
)
from businessos.modules.artifact import ApprovedModuleArtifact
from businessos.modules.manifest import ModuleDependency, ModuleManifest
from businessos.modules.sdk import ModuleRegistration
from tests.unit.test_messages import FakeUnitOfWork, FakeUnitOfWorkFactory


class ProbeCommand(Command):
    pass


class ProbeQuery(Query):
    pass


class NestedCommand(Command):
    pass


class ProbeModule:
    def __init__(
        self,
        module_id: str,
        *,
        dependencies: tuple[ModuleDependency, ...] = (),
        command_handler: object | None = None,
        query_handler: object | None = None,
        dependency_key: DependencyKey[object] | None = None,
    ) -> None:
        self.manifest = ModuleManifest(
            module_id=module_id,
            name=module_id,
            publisher="test-publisher",
            version="1.0.0",
            platform=">=0.1,<1",
            sdk=">=0.1,<1",
            python=">=3.12",
            entry_point="test:module",
            dependencies=dependencies,
        )
        self.command_handler = command_handler
        self.query_handler = query_handler
        self.dependency_key = dependency_key
        self.registrations: list[ModuleRegistration] = []

    async def register(self, registration: ModuleRegistration) -> None:
        self.registrations.append(registration)
        if self.command_handler is not None:
            registration.command(ProbeCommand, self.command_handler)  # type: ignore[arg-type]
        if self.query_handler is not None:
            registration.query(ProbeQuery, self.query_handler)  # type: ignore[arg-type]
        if self.dependency_key is not None:
            registration.dependency(self.dependency_key, lambda _: object())

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


def _settings() -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql+psycopg://test:test@db/test",
        database_readiness_enabled=False,
    )


def _grant(module: ProbeModule) -> ApprovedModuleArtifact:
    return ApprovedModuleArtifact(
        loaded_module=module,
        module_id=module.manifest.module_id,
        publisher=module.manifest.publisher,
        package_identity="operator-approved-first-party-package",
        loaded_type=f"{type(module).__module__}:{type(module).__qualname__}",
        install_identity="operator-approved-install-1",
        first_party=True,
    )


def _dependency(module_id: str) -> ModuleDependency:
    return ModuleDependency(module_id=module_id, version=">=1,<2")


@pytest.mark.asyncio
async def test_command_binding_is_exact_task_bound_and_unforgeable() -> None:
    saved: list[HandlerInvocationBinding] = []
    request = RequestContext(correlation_id="exact", trace_id="exact")
    factory = FakeUnitOfWorkFactory([])

    async def handler(_: ProbeCommand, handling: HandlingContext) -> object:
        binding = handling.invocation
        assert binding is not None
        saved.append(binding)
        assert binding.owner_module_id == "example.probe"
        assert binding.generation is module.registrations[-1].generation
        assert binding.invocation_kind is HandlerInvocationKind.COMMAND
        assert binding.direct_dependencies == ()
        assert (
            validate_handler_invocation(
                binding,
                handling.request,
                handling.unit_of_work,
                invocation_kind=HandlerInvocationKind.COMMAND,
            )
            is binding
        )
        with pytest.raises(PermissionError):
            validate_handler_invocation(
                binding,
                replace(handling.request),
                handling.unit_of_work,
                invocation_kind=HandlerInvocationKind.COMMAND,
            )
        with pytest.raises(PermissionError):
            validate_handler_invocation(
                binding,
                RequestContext(),
                handling.unit_of_work,
                invocation_kind=HandlerInvocationKind.COMMAND,
            )
        with pytest.raises(PermissionError):
            validate_handler_invocation(
                binding,
                handling.request,
                handler_transaction_view(factory.created[-1]),
                invocation_kind=HandlerInvocationKind.COMMAND,
            )
        with pytest.raises(PermissionError):
            validate_handler_invocation(
                binding,
                handling.request,
                handler_transaction_view(FakeUnitOfWorkFactory([])._create()),
                invocation_kind=HandlerInvocationKind.COMMAND,
            )

        async def child() -> None:
            with pytest.raises(PermissionError):
                validate_handler_invocation(
                    binding,
                    handling.request,
                    handling.unit_of_work,
                    invocation_kind=HandlerInvocationKind.COMMAND,
                )

        await asyncio.create_task(child())
        with pytest.raises(PermissionError):
            await asyncio.to_thread(
                validate_handler_invocation,
                binding,
                handling.request,
                handling.unit_of_work,
                invocation_kind=HandlerInvocationKind.COMMAND,
            )
        with pytest.raises(PermissionError):
            validate_handler_invocation(
                copy(binding),
                handling.request,
                handling.unit_of_work,
                invocation_kind=HandlerInvocationKind.COMMAND,
            )
        with pytest.raises(AttributeError):
            object.__setattr__(binding, "owner_module_id", "attacker")
        return "ok"

    module = ProbeModule("example.probe", command_handler=handler)
    app = create_application(_settings(), modules=(module,))
    assert app.runtime is not None
    app.runtime.messages._unit_of_work_factory = factory
    await app.runtime.lifecycle.install_all()
    await app.runtime.lifecycle.enable_all()
    async with app.runtime.container.request_scope() as dependencies:
        assert await app.runtime.messages.command(ProbeCommand(), request, dependencies) == "ok"
    with pytest.raises(PermissionError):
        validate_handler_invocation(
            saved[0],
            request,
            handler_transaction_view(factory.created[0]),
            invocation_kind=HandlerInvocationKind.COMMAND,
        )
    with pytest.raises(PermissionError):
        validate_handler_invocation(
            object(),
            request,
            handler_transaction_view(factory.created[0]),
            invocation_kind=HandlerInvocationKind.COMMAND,
        )

    class ForgedBinding:
        owner_module_id = "example.probe"
        generation = module.registrations[-1].generation
        invocation_kind = HandlerInvocationKind.COMMAND
        direct_dependencies: tuple[object, ...] = ()

        def assert_active(self, *_: object, **__: object) -> None:
            return None

    with pytest.raises(PermissionError):
        validate_handler_invocation(
            ForgedBinding(),
            request,
            handler_transaction_view(factory.created[0]),
            invocation_kind=HandlerInvocationKind.COMMAND,
        )


@pytest.mark.asyncio
async def test_query_binding_cannot_validate_as_command() -> None:
    async def handler(_: ProbeQuery, handling: HandlingContext) -> object:
        binding = handling.invocation
        assert binding is not None
        assert binding.invocation_kind is HandlerInvocationKind.QUERY
        assert (
            validate_handler_invocation(
                binding,
                handling.request,
                handling.unit_of_work,
                invocation_kind=HandlerInvocationKind.QUERY,
            )
            is binding
        )
        with pytest.raises(PermissionError):
            validate_handler_invocation(
                binding,
                handling.request,
                handling.unit_of_work,
                invocation_kind=HandlerInvocationKind.COMMAND,
            )
        return "query"

    module = ProbeModule("example.probe", query_handler=handler)
    app = create_application(_settings(), modules=(module,))
    assert app.runtime is not None
    app.runtime.messages._unit_of_work_factory = FakeUnitOfWorkFactory([])
    await app.runtime.lifecycle.install_all()
    await app.runtime.lifecycle.enable_all()
    async with app.runtime.container.request_scope() as dependencies:
        assert (
            await app.runtime.messages.query(ProbeQuery(), RequestContext(), dependencies)
            == "query"
        )


@pytest.mark.asyncio
async def test_nested_legacy_handler_cannot_borrow_outer_invocation() -> None:
    async def outer(_: ProbeCommand, handling: HandlingContext) -> object:
        binding = handling.invocation
        assert binding is not None
        assert app.runtime is not None
        await app.runtime.messages.command(NestedCommand(), handling.request, handling.dependencies)
        validate_handler_invocation(
            binding,
            handling.request,
            handling.unit_of_work,
            invocation_kind=HandlerInvocationKind.COMMAND,
        )
        return None

    async def inner(_: NestedCommand, handling: HandlingContext) -> object:
        assert handling.invocation is None
        outer_binding, outer_context = active[0]
        with pytest.raises(PermissionError):
            validate_handler_invocation(
                outer_binding,
                outer_context.request,
                outer_context.unit_of_work,
                invocation_kind=HandlerInvocationKind.COMMAND,
            )
        return None

    active: list[tuple[HandlerInvocationBinding, HandlingContext]] = []

    class CheckingFactory(FakeUnitOfWorkFactory):
        def _create(self) -> FakeUnitOfWork:
            if active:
                outer_binding, outer_context = active[0]
                with pytest.raises(PermissionError):
                    validate_handler_invocation(
                        outer_binding,
                        outer_context.request,
                        outer_context.unit_of_work,
                        invocation_kind=HandlerInvocationKind.COMMAND,
                    )
            return super()._create()

    async def capturing_outer(message: ProbeCommand, handling: HandlingContext) -> object:
        assert handling.invocation is not None
        active.append((handling.invocation, handling))
        return await outer(message, handling)

    module = ProbeModule("example.probe", command_handler=capturing_outer)
    app = create_application(_settings(), modules=(module,))
    assert app.runtime is not None
    app.runtime.messages._unit_of_work_factory = CheckingFactory([])
    await app.runtime.lifecycle.install_all()
    await app.runtime.lifecycle.enable_all()
    app.runtime.messages.commands.register(NestedCommand, "example.legacy", inner)
    async with app.runtime.container.request_scope() as dependencies:
        await app.runtime.messages.command(ProbeCommand(), RequestContext(), dependencies)


@pytest.mark.asyncio
async def test_direct_only_snapshot_and_manifest_replacement_do_not_change_authority() -> None:
    async def handler(_: ProbeCommand, handling: HandlingContext) -> object:
        binding = handling.invocation
        assert binding is not None
        assert binding.has_direct_dependency("example.middle")
        assert not binding.has_direct_dependency("foundation.audit")
        assert binding.direct_dependencies[0].version == ">=1,<2"
        return None

    audit = ProbeModule("foundation.audit")
    middle = ProbeModule("example.middle", dependencies=(_dependency("foundation.audit"),))
    module = ProbeModule(
        "example.probe", dependencies=(_dependency("example.middle"),), command_handler=handler
    )
    app = create_application(_settings(), modules=(module, middle, audit))
    assert app.runtime is not None
    app.runtime.messages._unit_of_work_factory = FakeUnitOfWorkFactory([])
    await app.runtime.lifecycle.install_all()
    await app.runtime.lifecycle.enable_all()
    module.manifest = module.manifest.model_copy(update={"dependencies": ()})
    async with app.runtime.container.request_scope() as dependencies:
        await app.runtime.messages.command(ProbeCommand(), RequestContext(), dependencies)


@pytest.mark.asyncio
async def test_direct_audit_dependency_is_proven_from_exact_manifest() -> None:
    async def handler(_: ProbeCommand, handling: HandlingContext) -> object:
        binding = handling.invocation
        assert binding is not None
        validate_handler_invocation(
            binding,
            handling.request,
            handling.unit_of_work,
            invocation_kind=HandlerInvocationKind.COMMAND,
        )
        assert binding.has_direct_dependency("foundation.audit")
        assert binding.direct_dependencies[0].module_id == "foundation.audit"
        assert binding.direct_dependencies[0].version == ">=1,<2"
        return None

    audit = ProbeModule("foundation.audit")
    module = ProbeModule(
        "example.probe",
        dependencies=(_dependency("foundation.audit"),),
        command_handler=handler,
    )
    app = create_application(_settings(), modules=(module, audit))
    assert app.runtime is not None
    app.runtime.messages._unit_of_work_factory = FakeUnitOfWorkFactory([])
    await app.runtime.lifecycle.install_all()
    await app.runtime.lifecycle.enable_all()
    async with app.runtime.container.request_scope() as dependencies:
        await app.runtime.messages.command(ProbeCommand(), RequestContext(), dependencies)


@pytest.mark.asyncio
async def test_drain_preserves_admitted_binding_then_revokes_it() -> None:
    entered = asyncio.Event()
    resume = asyncio.Event()
    saved: list[tuple[HandlerInvocationBinding, HandlingContext]] = []

    async def handler(_: ProbeCommand, handling: HandlingContext) -> object:
        assert handling.invocation is not None
        saved.append((handling.invocation, handling))
        entered.set()
        await resume.wait()
        validate_handler_invocation(
            handling.invocation,
            handling.request,
            handling.unit_of_work,
            invocation_kind=HandlerInvocationKind.COMMAND,
        )
        return None

    module = ProbeModule("example.probe", command_handler=handler)
    app = create_application(_settings(), modules=(module,))
    assert app.runtime is not None
    app.runtime.messages._unit_of_work_factory = FakeUnitOfWorkFactory([])
    await app.runtime.lifecycle.install_all()
    await app.runtime.lifecycle.enable_all()
    async with app.runtime.container.request_scope() as dependencies:
        first = asyncio.create_task(
            app.runtime.messages.command(ProbeCommand(), RequestContext(), dependencies)
        )
        await entered.wait()
        drain = asyncio.create_task(module.registrations[-1].stop_accepting(timeout_seconds=2))
        await asyncio.sleep(0)
        with pytest.raises(NotFoundError):
            await app.runtime.messages.command(ProbeCommand(), RequestContext(), dependencies)
        resume.set()
        await first
        await drain
    binding, handling = saved[0]
    with pytest.raises(PermissionError):
        validate_handler_invocation(
            binding,
            handling.request,
            handling.unit_of_work,
            invocation_kind=HandlerInvocationKind.COMMAND,
        )


@pytest.mark.asyncio
async def test_cancellation_and_generation_replacement_revoke_old_binding() -> None:
    entered = asyncio.Event()
    saved: list[tuple[HandlerInvocationBinding, HandlingContext]] = []

    async def handler(_: ProbeCommand, handling: HandlingContext) -> object:
        assert handling.invocation is not None
        saved.append((handling.invocation, handling))
        entered.set()
        if len(saved) == 1:
            await asyncio.Event().wait()
        return None

    module = ProbeModule("example.probe", command_handler=handler)
    app = create_application(_settings(), modules=(module,))
    assert app.runtime is not None
    app.runtime.messages._unit_of_work_factory = FakeUnitOfWorkFactory([])
    await app.runtime.lifecycle.install_all()
    await app.runtime.lifecycle.enable_all()
    async with app.runtime.container.request_scope() as dependencies:
        attempt = asyncio.create_task(
            app.runtime.messages.command(ProbeCommand(), RequestContext(), dependencies)
        )
        await entered.wait()
        attempt.cancel()
        with pytest.raises(asyncio.CancelledError):
            await attempt
        first_binding, first_handling = saved[0]
        with pytest.raises(PermissionError):
            validate_handler_invocation(
                first_binding,
                first_handling.request,
                first_handling.unit_of_work,
                invocation_kind=HandlerInvocationKind.COMMAND,
            )
        await app.runtime.lifecycle.disable(module.manifest.module_id)
        await app.runtime.lifecycle.enable(module.manifest.module_id)
        await app.runtime.messages.command(ProbeCommand(), RequestContext(), dependencies)
    second_binding, second_handling = saved[1]
    assert second_binding.generation is not first_binding.generation
    assert second_binding.generation.number > first_binding.generation.number
    with pytest.raises(PermissionError):
        validate_handler_invocation(
            first_binding,
            second_handling.request,
            second_handling.unit_of_work,
            invocation_kind=HandlerInvocationKind.COMMAND,
        )


@pytest.mark.asyncio
async def test_direct_handler_registration_gets_no_manifest_authority() -> None:
    async def handler(_: ProbeCommand, handling: HandlingContext) -> object:
        assert handling.invocation is None
        return None

    app = create_application(_settings())
    assert app.runtime is not None
    app.runtime.messages._unit_of_work_factory = FakeUnitOfWorkFactory([])
    generation = app.runtime.contributions.reserve("example.probe")
    app.runtime.messages.commands.register(
        ProbeCommand, "example.probe", handler, generation=generation
    )
    app.runtime.contributions.publish(generation)
    async with app.runtime.container.request_scope() as dependencies:
        await app.runtime.messages.command(ProbeCommand(), RequestContext(), dependencies)


@pytest.mark.asyncio
async def test_owner_restricted_key_requires_exact_owner_and_approved_artifact() -> None:
    key = DependencyKey[object]("foundation.audit.appender.v2", required_owner="foundation.audit")
    wrong = ProbeModule("example.wrong", dependency_key=key)
    wrong_app = create_application(_settings(), modules=(wrong,))
    assert wrong_app.runtime is not None
    await wrong_app.runtime.lifecycle.install_all()
    with pytest.raises(PermissionError, match="another module owner"):
        await wrong_app.runtime.lifecycle.enable_all()

    missing = ProbeModule("foundation.audit", dependency_key=key)
    missing_app = create_application(_settings(), modules=(missing,))
    assert missing_app.runtime is not None
    await missing_app.runtime.lifecycle.install_all()
    with pytest.raises(PermissionError, match="approved first-party artifact"):
        await missing_app.runtime.lifecycle.enable_all()

    approved = ProbeModule("foundation.audit", dependency_key=key)
    app = create_application(
        _settings(),
        modules=(approved,),
        approved_module_artifacts={"foundation.audit": _grant(approved)},
    )
    assert app.runtime is not None
    await app.runtime.lifecycle.install_all()
    await app.runtime.lifecycle.enable_all()
    async with app.runtime.container.request_scope() as dependencies:
        assert await dependencies.resolve(key) is not None
        with pytest.raises(PermissionError):
            validate_handler_invocation(
                await dependencies.resolve(key),
                RequestContext(),
                handler_transaction_view(FakeUnitOfWorkFactory([])._create()),
                invocation_kind=HandlerInvocationKind.COMMAND,
            )
    with pytest.raises(ConfigurationError, match="another module owner"):
        app.runtime.container.register(key, lambda _: object(), owner="example.wrong")
    unentitled = DependencyKey[object](
        "foundation.audit.unentitled.v2", required_owner="foundation.audit"
    )
    with pytest.raises(ConfigurationError, match="approved artifact"):
        app.runtime.container.register(
            unentitled,
            lambda _: object(),
            owner="foundation.audit",
            generation=approved.registrations[-1].generation,
        )

    unrestricted = DependencyKey[object]("example.unrestricted")
    app.runtime.container.register(unrestricted, lambda _: object())
    async with app.runtime.container.request_scope() as dependencies:
        assert await dependencies.resolve(unrestricted) is not None
