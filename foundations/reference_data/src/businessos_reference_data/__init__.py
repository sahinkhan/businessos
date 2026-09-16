"""Reference data and number sequence foundation module."""

from .contracts import (
    GeneratedNumberRecord,
    NumberSequenceRecord,
    ReferenceSetRecord,
    ReferenceValueRecord,
)
from .models import NUMBER_SEQUENCES, REFERENCE_SETS, REFERENCE_VALUES, metadata
from .module import (
    ConfigureNumberSequence,
    CreateReferenceValue,
    GenerateNextNumber,
    GetReferenceSet,
    GetReferenceValue,
    ListReferenceSets,
    ListReferenceValues,
    ReferenceDataModule,
    ReferenceSetRegistered,
    ReferenceValueChanged,
    RegisterReferenceSet,
    ResolveReferenceValueByExternalId,
)

__all__ = [
    "NUMBER_SEQUENCES",
    "REFERENCE_SETS",
    "REFERENCE_VALUES",
    "ConfigureNumberSequence",
    "CreateReferenceValue",
    "GenerateNextNumber",
    "GeneratedNumberRecord",
    "GetReferenceSet",
    "GetReferenceValue",
    "ListReferenceSets",
    "ListReferenceValues",
    "NumberSequenceRecord",
    "ReferenceDataModule",
    "ReferenceSetRecord",
    "ReferenceSetRegistered",
    "ReferenceValueChanged",
    "ReferenceValueRecord",
    "RegisterReferenceSet",
    "ResolveReferenceValueByExternalId",
    "metadata",
]
