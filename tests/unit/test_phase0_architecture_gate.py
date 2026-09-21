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


def assert_violation(root: Path, path: str, rule: str) -> None:
    assert any(item.path == path and item.rule == rule for item in check(root))


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


def test_full_system_roadmap_rejects_primary_go_gin(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    path = "docs/roadmap/FULL-SYSTEM.md"
    target = root / path
    target.write_text(
        target.read_text(encoding="utf-8") + "\nGo/Gin is the primary BusinessOS backend.\n",
        encoding="utf-8",
    )
    assert_violation(root, path, "go-primary")


def test_other_active_roadmap_rejects_primary_go(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    path = "docs/roadmap/PHASE-1.md"
    target = root / path
    target.write_text("# Phase 1\nGo as primary backend\n", encoding="utf-8")
    assert_violation(root, path, "go-primary")


def test_new_nested_roadmap_is_discovered_without_validator_edit(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    path = "docs/roadmap/new/ADDITIONAL.md"
    target = root / path
    target.parent.mkdir(parents=True)
    target.write_text("Core BusinessOS runtime is implemented in Go.\n", encoding="utf-8")
    assert_violation(root, path, "go-primary")


def test_existing_accepted_adr_rejects_primary_go(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    path = "docs/adr/ADR-008-python-asgi-technology-baseline.md"
    target = root / path
    target.write_text(
        target.read_text(encoding="utf-8") + "\nGo/Gin is the primary BusinessOS backend.\n",
        encoding="utf-8",
    )
    assert_violation(root, path, "go-primary")


def test_new_accepted_adr_is_discovered(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    path = "docs/adr/ADR-999-new-baseline.md"
    (root / path).write_text(
        "# New ADR\nStatus: ACCEPTED\nDecision: Go/Gin is the primary BusinessOS backend.\n",
        encoding="utf-8",
    )
    assert_violation(root, path, "go-primary")


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


def test_approved_python_39_primary_runtime_is_rejected(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    path = "docs/roadmap/NEW.md"
    (root / path).write_text("Python 3.9 is approved primary runtime.\n", encoding="utf-8")
    assert_violation(root, path, "old-python-primary")


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


def test_rejected_and_withdrawn_adrs_preserve_history(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    for status in ("REJECTED", "WITHDRAWN"):
        (root / f"docs/adr/ADR-{status}.md").write_text(
            f"Status: {status}\nPrevious proposal: Go as primary backend\n", encoding="utf-8"
        )
    assert check(root) == []


def test_draft_and_proposed_are_non_authoritative_but_cannot_claim_acceptance(
    tmp_path: Path,
) -> None:
    root = baseline(tmp_path)
    for status in ("DRAFT", "PROPOSED"):
        path = f"docs/adr/ADR-{status}.md"
        target = root / path
        target.write_text(
            f"Status: {status}\nAlternative: Go as primary backend.\n", encoding="utf-8"
        )
        assert check(root) == []
        target.write_text(
            target.read_text(encoding="utf-8") + "This ADR is already accepted.\n", encoding="utf-8"
        )
        assert_violation(root, path, "premature-adr-authority")
        target.write_text(f"Status: {status}\nAlternative only.\n", encoding="utf-8")


def test_missing_or_unknown_adr_status_fails_closed(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    path = "docs/adr/ADR-999-unknown.md"
    target = root / path
    target.write_text("# Decision\nGo as primary backend\n", encoding="utf-8")
    assert_violation(root, path, "adr-status")
    target.write_text("Status: INDETERMINATE\n", encoding="utf-8")
    assert_violation(root, path, "adr-status")


def test_current_python_asgi_adr_cannot_be_silently_demoted(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    path = "docs/adr/ADR-008-python-asgi-technology-baseline.md"
    target = root / path
    target.write_text(
        target.read_text(encoding="utf-8").replace("Status: Accepted", "Status: Proposed"),
        encoding="utf-8",
    )
    assert_violation(root, path, "baseline-adr-status")


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


def test_nested_active_architecture_source_cannot_be_excluded(tmp_path: Path) -> None:
    root = baseline(tmp_path)
    path = "docs/architecture/new/BOUNDARY.md"
    target = root / path
    target.parent.mkdir(parents=True)
    target.write_text("Go/Gin is the primary BusinessOS backend.\n", encoding="utf-8")
    assert_violation(root, path, "go-primary")


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


def test_independent_audit_bypass_probes_through_cli(tmp_path: Path) -> None:
    for name, path, content, exit_code, rule in (
        (
            "A",
            "docs/roadmap/PHASE-1.md",
            "# Active roadmap\nGo as primary backend\n",
            1,
            "go-primary",
        ),
        (
            "B",
            "docs/adr/ADR-999-new.md",
            "Status: ACCEPTED\nDecision: Go/Gin is the primary BusinessOS backend.\n",
            1,
            "go-primary",
        ),
        (
            "C",
            "docs/adr/ADR-999-historical.md",
            "Status: SUPERSEDED\nPrevious decision: Go/Gin is the primary BusinessOS backend.\n",
            0,
            "",
        ),
    ):
        root = baseline(tmp_path / name)
        (root / path).write_text(content, encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(root)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == exit_code, (name, result.stderr)
        if rule:
            assert path in result.stderr and rule in result.stderr
