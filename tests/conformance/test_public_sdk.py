import ast
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
