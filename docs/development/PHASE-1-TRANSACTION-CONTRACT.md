# Phase 1 handler transaction boundary

The framework owns the transaction around each command, query, and durable event subscriber. A
handler's `HandlingContext.unit_of_work` or `EventHandlingContext.unit_of_work` is now a
`HandlerTransaction` capability: `persistence.execute`, `persistence.flush`, and `add_outbox` are
available, but `commit`, `rollback`, session creation/closure, and transaction context-manager
operations are not. The dispatcher/consumer commits only after successful handler completion;
otherwise the framework rolls back the state, outbox, and inbox claim together.
The handler persistence adapter also rejects explicit transaction-control SQL statements such as
`COMMIT` and `ROLLBACK` passed through its textual SQL execution path.

This corrects the prior public handler contract, which typed `unit_of_work` as the full
`UnitOfWork` and handed the handler the same mutable object that the framework would later
complete. An existing handler using `context.unit_of_work.persistence` or `add_outbox` needs no
change. A handler that called `commit()` or `rollback()` directly must remove those calls and
return success or raise an error so the framework decides the outcome. There is no safe
deprecation period for direct handler completion: retaining it allows a failed handler to leave
committed business state without its outbox/inbox outcome. The standalone `UnitOfWork` and
`UnitOfWorkFactory` SDK exports remain available for framework-owned integrations; they are not
the object passed into handlers.

Current consumers were inspected across the platform, first-party foundations, and external
proof module. The proof module and foundations use the retained persistence capability; no
Phase 2 source or contract change is needed. The correction introduces no schema or migration.
Code outside these reviewed consumers that explicitly depends on handler-level transaction
completion must migrate as described above before using this SDK revision. This is an
intentional safety correction to the framework-owned boundary in ADR-008 and ADR-005, not a
new transaction architecture.
