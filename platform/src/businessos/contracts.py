"""Public application contract registry."""

from typing import Protocol

from businessos.registry import OwnedRegistry


class PublicContract(Protocol):
    @property
    def version(self) -> str: ...


class ContractRegistry(OwnedRegistry[PublicContract]):
    def __init__(self) -> None:
        super().__init__("contract")
