"""Private, deterministic ADR-024 completeness capture for the approved writer.

The kernel retains the catalog admissions and supplies the locked database facts.
These values are never command arguments or a public proof-issuance contract.
SQL grants, rather than this value object or a digest, authenticate persistence.
"""

import re
from dataclasses import dataclass

from businessos.sdk import AdmittedMetadataDeclaration


@dataclass(frozen=True, slots=True)
class CompatibilityMember:
    module_id: str
    artifact_identity: str
    generation: int


def capture_members(
    sources: tuple[AdmittedMetadataDeclaration, ...],
    locked: tuple[CompatibilityMember, ...],
) -> tuple[CompatibilityMember, ...]:
    """Capture the complete source/direct-dependency union, with exact identities.

    Extra locked identities may belong to the previous active revision. They are
    needed for pointer/counter serialization but must not become new dependencies.
    Duplicate database identities are invalid even when their values agree.
    """
    generations: dict[str, int] = {}
    for source in sources:
        for admission in (source.generation, *source.dependency_generations):
            previous = generations.setdefault(admission.owner, admission.number)
            if previous != admission.number:
                raise ValueError("Conflicting admitted compatibility generations")
        if source.owner != source.generation.owner:
            raise ValueError("Source owner differs from admitted owner")
    if not 1 <= len(generations) <= 128:
        raise ValueError("Compatibility member budget exceeded")
    identities: dict[str, CompatibilityMember] = {}
    for member in locked:
        if (
            not re.fullmatch(r"[a-z][a-z0-9_.-]+", member.module_id)
            or len(member.module_id) > 120
            or not member.artifact_identity
            or len(member.artifact_identity.encode("utf-8")) > 800
            or type(member.generation) is not int
            or not 1 <= member.generation <= 2**63 - 1
            or member.module_id in identities
        ):
            raise ValueError("Invalid durable compatibility identity")
        identities[member.module_id] = member
    if not generations.keys() <= identities.keys():
        raise ValueError("Missing admitted compatibility identity")
    approved: dict[str, tuple[str, int | None]] = {}
    for source in sources:
        if tuple(item[0] for item in source.dependency_artifacts) != tuple(
            item.owner for item in source.dependency_generations
        ):
            raise ValueError("Missing approved dependency artifact provenance")
        for owner, artifact, generation in (
            (source.owner, source.artifact_identity, source.artifact_generation),
            *source.dependency_artifacts,
        ):
            prior = approved.setdefault(owner, (artifact, generation))
            if (
                not artifact
                or type(generation) is not int
                or not 1 <= generation <= 2**63 - 1
                or prior != (artifact, generation)
            ):
                raise ValueError("Missing or conflicting approved artifact provenance")
    if approved.keys() != generations.keys() or any(
        approved[owner] != (identities[owner].artifact_identity, identities[owner].generation)
        for owner in generations
    ):
        raise ValueError("Retained approved artifact differs from durable compatibility identity")
    return tuple(
        identities[key] for key in sorted(generations, key=lambda key: key.encode("utf-8"))
    )
