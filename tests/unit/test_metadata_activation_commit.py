"""Deterministic activation commit and full-artifact identity regressions."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import pytest

from businessos.bootstrap import create_application
from businessos.errors import NotFoundError
from businessos.modules import LifecycleManager, ModuleState
from businessos.modules.artifact import ApprovedModuleArtifact
from tests.unit.test_modules import ProofModule, _settings


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "failure", "cancel"])
async def test_contributions_wait_for_successful_fence_commit(outcome: str) -> None:
    reached = asyncio.Event()
    release = asyncio.Event()

    class Fence:
        @asynccontextmanager
        async def activation(self, module_id: str, artifact_identity: str) -> AsyncGenerator[None]:
            yield
            reached.set()
            await release.wait()
            if outcome == "failure":
                raise RuntimeError("injected commit failure")

    module = ProofModule(migrations=())
    app = create_application(_settings(), modules=(module,))
    assert app.runtime is not None
    lifecycle = LifecycleManager(
        app.runtime.modules, app.runtime.registration, activation_fence=Fence()
    )
    await lifecycle.install_all()
    task = asyncio.create_task(lifecycle.enable_all())
    await asyncio.wait_for(reached.wait(), 2)
    with pytest.raises(NotFoundError):
        app.runtime.router.match("GET", "/proof")
    if outcome == "cancel":
        task.cancel()
    release.set()
    if outcome == "success":
        await task
        assert app.runtime.router.match("GET", "/proof") is not None
        await lifecycle.disable_all()
    else:
        with pytest.raises((RuntimeError, asyncio.CancelledError)):
            await task
        with pytest.raises(NotFoundError):
            app.runtime.router.match("GET", "/proof")
        registered = app.runtime.modules.get(module.manifest.module_id)
        assert registered.state is ModuleState.FAILED
        assert registered.registration is None
        assert not registered.started
        assert module.lifecycle == ["register", "start", "stop"]


def test_activation_digest_uses_complete_approved_installation_identity() -> None:
    module = ProofModule(migrations=())
    identities = []
    for suffix in ("a", "b"):
        artifact = ApprovedModuleArtifact(
            loaded_module=module,
            module_id=module.manifest.module_id,
            publisher=module.manifest.publisher,
            package_identity="test-package",
            loaded_type=f"{type(module).__module__}:{type(module).__qualname__}",
            install_identity="x" * 200 + suffix,
        )
        app = create_application(
            _settings(),
            modules=(module,),
            approved_module_artifacts={module.manifest.module_id: artifact},
        )
        assert app.runtime is not None
        identities.append(app.runtime.modules.activation_identity(module.manifest.module_id))
    assert identities[0] != identities[1]
    assert all(len(identity) == 64 for identity in identities)
