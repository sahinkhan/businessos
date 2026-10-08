"""Fixed Metadata-owned writer selected only by trusted kernel composition.

This object is not registered in DI or returned to handlers. The ordinary handler
context has no SQL access. Only these enumerated owner operations use the private
transaction supplied once by the kernel executor.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from businessos.sdk import (
    AdmittedMetadataDeclaration,
    BusinessOSError,
    Command,
    HandlerInvocationKind,
    HandlingContext,
    TransactionalPersistence,
)

from .ui_contracts import UIConflict
from .ui_runtime import (
    PublishedUIRuntime,
    _guard,  # pyright: ignore[reportPrivateUsage] -- fixed private owner composition
)

if TYPE_CHECKING:
    from .module import MetadataModule


class PrivateUIWriter:
    def __init__(self, owner: MetadataModule, persistence: TransactionalPersistence) -> None:
        self._owner = owner
        self._persistence = persistence

    async def view(self, message: Command, context: HandlingContext) -> UUID:
        from .module import PublishUIOverlay, ReactivateUIOverlay, RetireUIOverlay

        if type(message) not in (PublishUIOverlay, ReactivateUIOverlay, RetireUIOverlay):
            raise PermissionError("Unsupported private publication intent")
        assert isinstance(message, (PublishUIOverlay, ReactivateUIOverlay, RetireUIOverlay))
        principal = await _guard(context, HandlerInvocationKind.COMMAND)
        runtime = PublishedUIRuntime(_private_persistence=self._persistence)
        row = await runtime._row(  # pyright: ignore[reportPrivateUsage] -- private owner adapter
            message.overlay_id, context, principal
        )
        view_id = row["view_id"]
        if type(view_id) is not UUID:
            raise PermissionError("Invalid stored publication view")
        return view_id

    async def execute(
        self,
        message: Command,
        context: HandlingContext,
        sources: tuple[AdmittedMetadataDeclaration, ...],
    ) -> object:
        from .module import PublishUIOverlay, ReactivateUIOverlay, RetireUIOverlay

        if type(message) not in (PublishUIOverlay, ReactivateUIOverlay, RetireUIOverlay):
            raise PermissionError("Unsupported private publication intent")
        assert isinstance(message, (PublishUIOverlay, ReactivateUIOverlay, RetireUIOverlay))
        runtime = PublishedUIRuntime(
            _private_persistence=self._persistence,
            _private_sources=sources,
        )
        try:
            result = await runtime.mutate(
                message.overlay_id,
                message.expected_draft_generation,
                message.expected_active_generation,
                context,
                revision_id=message.revision_id
                if isinstance(message, ReactivateUIOverlay)
                else None,
                retire=isinstance(message, RetireUIOverlay),
            )
        except UIConflict as error:
            raise BusinessOSError(
                "ui_" + error.code.value, "UI overlay rejected", status_code=409
            ) from None
        action = (
            "reactivate"
            if isinstance(message, ReactivateUIOverlay)
            else "retire"
            if isinstance(message, RetireUIOverlay)
            else "publish"
        )
        # Remains an owner-private operation, not a new public publication API.
        await self._owner._ui_evidence(  # pyright: ignore[reportPrivateUsage]
            result, action, context
        )
        return result
