"""Validate active Phase 0 architecture and technology declarations.

Historical ADRs and audit/migration evidence are deliberately outside the active-source
inventory. New files under active architecture/governance directories are discovered.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

CANONICAL = Path("docs/architecture/KERNEL-RESPONSIBILITIES.md")
DERIVED = (
    Path("AGENTS.md"),
    Path("docs/architecture/ARCHITECTURE.md"),
    Path("docs/architecture/MODULE-CATALOG.md"),
    Path("docs/codex/MASTER-BUILD-INSTRUCTIONS.md"),
    Path("docs/roadmap/FULL-SYSTEM.md"),
)
REQUIRED = (
    "bootstrap/runtime",
    "RequestContext / TenantContext",
    "configuration",
    "module discovery / registry / lifecycle",
    "ASGI routing / middleware",
    "dependency injection",
    "contract registry",
    "command/query dispatch",
    "Unit of Work / framework-owned transaction boundary",
    "authorization enforcement boundary",
    "event / transactional-outbox runtime",
    "provider registry",
    "feature flags",
    "metadata / permission registration primitives",
    "migration runtime",
    "compatibility runtime",
    "module SDK / upgrade coordination",
    "diagnostics / health / version",
)
ACTIVE_REQUIRED = (
    *DERIVED,
    CANONICAL,
    Path("docs/adr/ADR-008-python-asgi-technology-baseline.md"),
    Path("docs/architecture/DEVELOPMENT.md"),
    Path("docs/governance/ADR-GOVERNANCE.md"),
    Path("docs/governance/RELEASES.md"),
    Path("docs/governance/MAINTAINERS.md"),
    Path("README.md"),
    Path("pyproject.toml"),
    Path("Dockerfile"),
    Path("compose.yaml"),
    Path(".github/workflows/ci.yml"),
)
ACTIVE_DIRS = ("docs/architecture", "docs/governance", "docs/codex")
RULES = (
    (
        "go-primary",
        re.compile(
            r"\b(?:Go(?:/Gin)?\s+(?:as|is|remains)\s+(?:the\s+)?primary\s+(?:backend|worker)|"
            r"(?:primary|default)\s+(?:backend|worker)(?:\s+language)?\s*[:=-]\s*Go\b)",
            re.I,
        ),
    ),
    (
        "gin-primary",
        re.compile(
            r"\bGin\s+(?:as|is|remains)\s+(?:the\s+)?(?:primary|default)\s+"
            r"(?:HTTP\s+)?(?:framework|adapter|server)\b|"
            r"\bGin\s+as\s+HTTP\s+transport\s+adapter\b",
            re.I,
        ),
    ),
    (
        "obsolete-backend",
        re.compile(
            r"\b(?:FastAPI|Django|Flask)\s+(?:as|is)\s+(?:the\s+)?"
            r"(?:primary|default)\s+(?:backend|framework)\b",
            re.I,
        ),
    ),
    (
        "old-python-primary",
        re.compile(
            r"\bPython\s+3\.(?:[0-9]|10|11|12)(?!\d)(?:\+|\s+or\s+newer)?"
            r"\s+(?:as|is)\s+(?:the\s+)?primary\s+(?:backend|runtime|worker)\b|"
            r"\b(?:primary|default)\s+(?:Python\s+)?(?:backend|runtime|worker)"
            r"\s*[:=-]\s*Python\s+3\.(?:[0-9]|10|11|12)(?!\d)",
            re.I,
        ),
    ),
    (
        "old-python-requirement",
        re.compile(
            r"^\s*requires-python\s*=\s*['\"]>=?3\.(?:[0-9]|10|11|12)"
            r"(?!\d)[^'\"]*['\"]",
            re.I,
        ),
    ),
    (
        "old-python-image",
        re.compile(r"^\s*FROM\s+python:3\.(?:[0-9]|10|11|12)(?!\d)(?:[-@\s]|$)", re.I),
    ),
    (
        "legacy-runtime-path",
        re.compile(r"(?:^|[\s`'\"])(?:cmd/server|backend/go)(?:/|\\)[\w./\\-]*"),
    ),
)


@dataclass(frozen=True, order=True)
class Violation:
    path: str
    line: int
    rule: str
    detail: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.rule}: {self.detail}"


def active_files(root: Path) -> tuple[set[Path], list[Violation]]:
    files = set(ACTIVE_REQUIRED)
    for directory in ACTIVE_DIRS:
        files.update(path.relative_to(root) for path in (root / directory).glob("*.md"))
    for extension in ("*.yml", "*.yaml"):
        files.update(
            path.relative_to(root) for path in (root / ".github/workflows").glob(extension)
        )
    for pattern in ("**/pyproject.toml", "**/Dockerfile*", "**/AGENTS.md"):
        files.update(path.relative_to(root) for path in root.glob(pattern))
    missing = [
        Violation(path.as_posix(), 0, "missing-active-source", "required active source absent")
        for path in ACTIVE_REQUIRED
        if not (root / path).is_file()
    ]
    return files, missing


def check(root: Path) -> list[Violation]:
    files, violations = active_files(root)
    contents: dict[Path, str] = {}
    for path in sorted(files):
        target = root / path
        if not target.is_file():
            continue
        try:
            content = target.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            violations.append(Violation(path.as_posix(), 0, "unreadable-active-source", str(exc)))
            continue
        contents[path] = content
        for number, line in enumerate(content.splitlines(), 1):
            for name, pattern in RULES:
                if pattern.search(line):
                    violations.append(Violation(path.as_posix(), number, name, line.strip()))

    canonical = contents.get(CANONICAL)
    if canonical is not None:
        entries = re.findall(r"^- (.+)$", canonical, re.M)
        for item in REQUIRED:
            if entries.count(item) != 1:
                violations.append(
                    Violation(
                        CANONICAL.as_posix(),
                        0,
                        "kernel-map",
                        f"expected exactly one responsibility: {item}",
                    )
                )
        for item in sorted(set(entries) - set(REQUIRED)):
            violations.append(
                Violation(
                    CANONICAL.as_posix(), 0, "kernel-map", f"unclassified responsibility: {item}"
                )
            )
    for path in DERIVED:
        derived_content = contents.get(path)
        if derived_content is not None and "KERNEL-RESPONSIBILITIES.md" not in derived_content:
            violations.append(
                Violation(
                    path.as_posix(),
                    0,
                    "kernel-map-reference",
                    "active derived source must link to canonical map",
                )
            )
        if derived_content is not None and "feature flags" not in derived_content.lower():
            violations.append(
                Violation(
                    path.as_posix(),
                    0,
                    "feature-flags",
                    "active derived source must classify feature flags",
                )
            )
    for legacy in (root / "go.mod", root / "cmd/server", root / "backend/go"):
        if legacy.exists():
            violations.append(
                Violation(
                    legacy.relative_to(root).as_posix(),
                    0,
                    "legacy-runtime-path",
                    "active legacy runtime path exists",
                )
            )
    return sorted(violations)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    violations = check(args.root.resolve())
    for violation in violations:
        print(violation, file=sys.stderr)
    if violations:
        print(
            f"Phase 0 architecture governance gate: FAIL ({len(violations)} violation(s))",
            file=sys.stderr,
        )
        return 1
    print("Phase 0 architecture governance gate: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
