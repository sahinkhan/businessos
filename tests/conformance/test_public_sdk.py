import ast
import tomllib
from pathlib import Path

from businessos.sdk import (
    ModuleManifest,
    ResourceLocator,
    ResourceOwnerFacts,
    ResourceOwnerFactsProvider,
    ResourceOwnerOperationProvider,
    ResourceOwnership,
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
