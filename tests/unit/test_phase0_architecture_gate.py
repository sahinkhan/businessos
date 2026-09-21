"""Focused governance checks; no application runtime imports are required."""

import shutil
import subprocess
import sys
from pathlib import Path

from scripts.check_phase0_architecture import ACTIVE_REQUIRED, check

SOURCE = Path(__file__).resolve().parents[2]
SCRIPT = SOURCE / "scripts/check_phase0_architecture.py"


def baseline(tmp_path: Path) -> Path:
    for relative in ACTIVE_REQUIRED:
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SOURCE / relative, destination)
    return tmp_path


def test_current_approved_architecture_passes() -> None:
    assert check(SOURCE) == []


def test_active_go_primary_is_rejected(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    target = root / "docs/architecture/ARCHITECTURE.md"
    target.write_text(
        target.read_text(encoding="utf-8") + "\n- Go as primary backend\n", encoding="utf-8"
    )
    assert any(
        item.path == "docs/architecture/ARCHITECTURE.md" and item.rule == "go-primary"
        for item in check(root)
    )


def test_unsupported_primary_python_and_build_requirement_rejected(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    target = root / "AGENTS.md"
    target.write_text(
        target.read_text(encoding="utf-8") + "\n- Python 3.12 as primary runtime\n",
        encoding="utf-8",
    )
    project = root / "pyproject.toml"
    project.write_text(
        project.read_text(encoding="utf-8").replace(
            'requires-python = ">=3.13"', 'requires-python = ">=3.12"'
        ),
        encoding="utf-8",
    )
    assert {item.rule for item in check(root)} >= {"old-python-primary", "old-python-requirement"}


def test_superseded_adr_and_audit_history_are_excluded(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    for path in ("docs/adr/ADR-001-technology-baseline.md", "docs/development/HISTORICAL-AUDIT.md"):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "Status: Superseded\nGo as primary backend\nGin as HTTP transport adapter\n",
            encoding="utf-8",
        )
    assert check(root) == []


def test_required_source_missing_and_new_active_source_discovered(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    (root / "docs/codex/MASTER-BUILD-INSTRUCTIONS.md").unlink()
    target = root / "docs/architecture/NEW-ACTIVE.md"
    target.write_text("Gin as HTTP transport adapter\n", encoding="utf-8")
    package = root / "examples/new_module/pyproject.toml"
    package.parent.mkdir(parents=True)
    package.write_text('requires-python = ">=3.12"\n', encoding="utf-8")
    found = {(item.path, item.rule) for item in check(root)}
    assert ("docs/codex/MASTER-BUILD-INSTRUCTIONS.md", "missing-active-source") in found
    assert ("docs/architecture/NEW-ACTIVE.md", "gin-primary") in found
    assert ("examples/new_module/pyproject.toml", "old-python-requirement") in found


def test_canonical_map_and_derived_feature_flags_are_enforced(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    canonical = root / "docs/architecture/KERNEL-RESPONSIBILITIES.md"
    canonical.write_text(
        canonical.read_text(encoding="utf-8").replace("- feature flags\n", ""), encoding="utf-8"
    )
    derived = root / "docs/architecture/MODULE-CATALOG.md"
    derived.write_text(
        derived.read_text(encoding="utf-8").replace("- feature flags\n", ""), encoding="utf-8"
    )
    assert {item.rule for item in check(root)} >= {"kernel-map", "feature-flags"}


def test_cli_fails_deterministically_with_file_and_rule(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    target = root / "docs/architecture/ARCHITECTURE.md"
    target.write_text(
        target.read_text(encoding="utf-8") + "\nGo as primary backend\n", encoding="utf-8"
    )
    command = [sys.executable, str(SCRIPT), "--root", str(root)]
    first = subprocess.run(command, capture_output=True, text=True, check=False)
    second = subprocess.run(command, capture_output=True, text=True, check=False)
    assert first.returncode == second.returncode == 1
    assert first.stderr == second.stderr
    assert "docs/architecture/ARCHITECTURE.md" in first.stderr
    assert "go-primary" in first.stderr
