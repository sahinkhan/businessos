import ast
import tomllib
from pathlib import Path


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
        "businessos>=0.1,<1",
        "pydantic>=2.10,<3",
        "sqlalchemy>=2.0.36,<3",
    ]
