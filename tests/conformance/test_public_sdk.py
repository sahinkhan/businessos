import ast
import tomllib
from pathlib import Path

from businessos.sdk import (
    DependencyKey,
    HandlerInvocationBinding,
    HandlerInvocationDependency,
    HandlerInvocationKind,
    HandlingContext,
    ModuleManifest,
    ResourceLocator,
    ResourceOwnerFacts,
    ResourceOwnerFactsProvider,
    ResourceOwnerOperationProvider,
    ResourceOwnership,
    validate_handler_invocation,
)


def test_external_proof_module_imports_businessos_only_through_public_sdk() -> None:
    package = Path("examples/proof_module/src/businessos_proof")
    imports: list[tuple[Path, str]] = []
    for source_path in sorted(package.rglob("*.py")):
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        imports.extend(
            (source_path, node.module)
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and node.module is not None
            and (node.module == "businessos" or node.module.startswith("businessos."))
        )

    assert imports == [(package / "module.py", "businessos.sdk")]


def test_external_proof_module_declares_every_direct_runtime_dependency() -> None:
    configuration = tomllib.loads(
        Path("examples/proof_module/pyproject.toml").read_text(encoding="utf-8")
    )

    assert configuration["project"]["dependencies"] == [
        "alembic>=1.14,<2",
        "businessos>=0.1,<1",
        "pydantic>=2.10,<3",
        "sqlalchemy>=2.0.36,<3",
    ]


def test_resource_owner_contracts_are_available_through_stable_sdk() -> None:
    assert "resource_ownership" in ModuleManifest.model_fields
    assert ResourceOwnership.__module__ == "businessos.modules.manifest"
    assert ResourceLocator.__module__ == "businessos.resources"
    assert ResourceOwnerFacts.__module__ == "businessos.resources"
    assert "read_facts" in ResourceOwnerFactsProvider.__dict__
    assert "validate_operation" in ResourceOwnerOperationProvider.__dict__
    assert "apply_operation" in ResourceOwnerOperationProvider.__dict__


def test_handler_invocation_contract_is_additive_and_public() -> None:
    assert HandlerInvocationBinding.__module__ == "businessos.handler_invocation"
    assert HandlerInvocationDependency.__module__ == "businessos.handler_invocation"
    assert HandlerInvocationKind.COMMAND.value == "command"
    assert HandlerInvocationKind.QUERY.value == "query"
    assert callable(validate_handler_invocation)
    assert "invocation" in HandlingContext.__dataclass_fields__
    assert DependencyKey[object]("example.key").required_owner is None
    assert DependencyKey[object]("example.key", required_owner="example.owner").required_owner == (
        "example.owner"
    )
