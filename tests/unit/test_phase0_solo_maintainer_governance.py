"""Guard the temporary owner-attestation path across active Phase 0 policies."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
POLICIES = (
    "docs/governance/MAINTAINERS.md",
    "docs/governance/ADR-GOVERNANCE.md",
    "docs/governance/RELEASES.md",
    "docs/governance/PHASE-0-ACCEPTANCE.md",
    "docs/architecture/DEVELOPMENT.md",
)


@pytest.mark.parametrize("path", POLICIES)
def test_active_policies_distinguish_independent_review_from_owner_attestation(path: str) -> None:
    policy = (ROOT / path).read_text(encoding="utf-8").lower()
    assert "solo maintainer exception" in policy
    assert "independent human review" in policy
    assert "attestation" in policy
    assert "authorship" in policy
    assert "another eligible" in policy


def test_solo_acceptance_keeps_exact_head_audit_and_human_independence_boundary() -> None:
    maintainers = (ROOT / POLICIES[0]).read_text(encoding="utf-8")
    acceptance = (ROOT / POLICIES[3]).read_text(encoding="utf-8")
    for policy in (maintainers, acceptance):
        assert "Review model: SOLO MAINTAINER OWNER ATTESTATION" in policy
        assert "Independent human review: NOT PERFORMED" in policy
        assert "Independent technical audit: PERFORMED" in policy
        assert "Critical" in policy and "High" in policy
    assert "Authorship alone is not approval evidence" in maintainers
    assert "production-grade `1.0.0`" in maintainers
