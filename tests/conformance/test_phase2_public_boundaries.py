import ast
from pathlib import Path

from businessos.modules import discover_modules


def test_phase2_modules_discover_in_dependency_order() -> None:
    phase2 = {
        module.manifest.module_id: module
        for module in discover_modules()
        if module.manifest.module_id.startswith("foundation.")
    }
    assert set(phase2) == {
        "foundation.tenant",
        "foundation.identity",
        "foundation.organization",
    }
    assert phase2["foundation.identity"].manifest.dependencies[0].module_id == "foundation.tenant"
    assert [item.module_id for item in phase2["foundation.organization"].manifest.dependencies] == [
        "foundation.tenant",
        "foundation.identity",
    ]


def test_phase2_production_code_uses_only_public_platform_sdk() -> None:
    root = Path("foundations")
    forbidden: list[str] = []
    for path in sorted(root.glob("*/src/**/*.py")):
        if "/migrations/" in path.as_posix():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module == "businessos" or (
                    node.module.startswith("businessos.") and node.module != "businessos.sdk"
                ):
                    forbidden.append(f"{path}:{node.lineno}:{node.module}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "businessos" or alias.name.startswith("businessos."):
                        forbidden.append(f"{path}:{node.lineno}:{alias.name}")
    assert forbidden == []
