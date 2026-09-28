"""Deterministic in-memory conditional object storage for proof tests."""

from collections import defaultdict
from uuid import UUID


class InMemoryFencedStorage:
    def __init__(self) -> None:
        self.objects: dict[tuple[UUID, str], bytes] = {}
        self._versions: dict[tuple[UUID, str], str] = {}
        self._next_version: dict[tuple[UUID, str], int] = defaultdict(int)

    async def readiness(self) -> None:
        return None

    async def put(self, tenant_id: UUID, key: str, content: bytes) -> None:
        object_key = (tenant_id, key)
        self.objects[object_key] = content
        self._advance(object_key)

    async def get(self, tenant_id: UUID, key: str) -> bytes:
        return self.objects[(tenant_id, key)]

    async def delete(self, tenant_id: UUID, key: str) -> None:
        object_key = (tenant_id, key)
        self.objects.pop(object_key, None)
        self._advance(object_key)

    async def version(self, tenant_id: UUID, key: str) -> str | None:
        object_key = (tenant_id, key)
        if object_key in self.objects and object_key not in self._versions:
            self._advance(object_key)
        return self._versions.get(object_key)

    async def compare_and_reconcile(
        self, tenant_id: UUID, key: str, expected_version: str | None, content: bytes | None
    ) -> bool:
        object_key = (tenant_id, key)
        if await self.version(tenant_id, key) != expected_version:
            return False
        if content is None:
            self.objects.pop(object_key, None)
        else:
            self.objects[object_key] = content
        self._advance(object_key)
        return True

    def _advance(self, object_key: tuple[UUID, str]) -> None:
        self._next_version[object_key] += 1
        self._versions[object_key] = str(self._next_version[object_key])
