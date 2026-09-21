"""Validate active Phase 0 architecture and technology declarations.

Roadmaps and ADRs are discovered recursively. ADR status determines whether its
decision is authoritative; superseded/rejected/withdrawn records remain historical.
Historical audit/migration evidence outside active source directories is not scanned.
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
ACTIVE_DIRS = ("docs/architecture", "docs/governance", "docs/codex", "docs/roadmap")
ADR_DIR = Path("docs/adr")
ADR_STATUSES = frozenset({"ACCEPTED", "SUPERSEDED", "REJECTED", "WITHDRAWN", "DRAFT", "PROPOSED"})
ADR_STATUS_LINE = re.compile(r"^Status:\s*\*{0,2}([A-Za-z]+)\b", re.I | re.M)
PREMATURE_AUTHORITY = re.compile(
    r"\b(?:this\s+(?:ADR|proposal|decision)|the\s+decision)\s+"
    r"(?:is|has\s+been)\s+(?:already\s+)?(?:accepted|authoritative|current|in\s+force)\b",
    re.I,
)
RULES = (
    (
        "go-primary",
        re.compile(
            r"\b(?:Go(?:/Gin)?\s+(?:as|is|remains)\s+(?:the\s+)?primary\s+"
            r"(?:BusinessOS\s+)?(?:backend|runtime|worker)|"
            r"(?:primary|default)\s+(?:BusinessOS\s+)?(?:backend|runtime|worker)"
            r"(?:\s+language)?\s*[:=-]\s*Go\b|"
            r"core\s+BusinessOS\s+runtime\s+is\s+implemented\s+in\s+Go\b)",
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
            r"\s+(?:as|is)\s+(?:the\s+|approved\s+)?primary\s+"
            r"(?:backend|runtime|worker)\b|"
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
        files.update(path.relative_to(root) for path in (root / directory).rglob("*.md"))
    files.update(path.relative_to(root) for path in (root / ADR_DIR).rglob("*.md"))
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
        if path.is_relative_to(ADR_DIR):
            matches = list(ADR_STATUS_LINE.finditer(content))
            if len(matches) != 1 or matches[0].group(1).upper() not in ADR_STATUSES:
                violations.append(
                    Violation(path.as_posix(), 0, "adr-status", "one known ADR Status is required")
                )
                continue
            status = matches[0].group(1).upper()
            if (
                path == Path("docs/adr/ADR-008-python-asgi-technology-baseline.md")
                and status != "ACCEPTED"
            ):
                violations.append(
                    Violation(path.as_posix(), 0, "baseline-adr-status", "ADR-008 must be ACCEPTED")
                )
            if status in {"SUPERSEDED", "REJECTED", "WITHDRAWN"}:
                continue
            if status in {"DRAFT", "PROPOSED"}:
                for number, line in enumerate(content.splitlines(), 1):
                    if PREMATURE_AUTHORITY.search(line):
                        violations.append(
                            Violation(
                                path.as_posix(), number, "premature-adr-authority", line.strip()
                            )
                        )
                continue
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
