# Phase 3 UoM precision and conversion safety

UoM `precision` means **decimal places in the converted result**, not total
significant digits. The Phase 3 public command and record support scales from
0 through 100 inclusive. `uom_0002` preflights existing units above 100 and
refuses the upgrade with recovery guidance; its database check enforces the
same maximum. The historical `uom_0001` revision is unchanged.

Conversion uses a fresh, bounded local Decimal context sized from operand
magnitude, operand fractional scale, conversion multiplication and division,
and the requested output scale. Its capacity is capped at 512 significant
digits. Unsupported arithmetic receives the typed
`uom_conversion_out_of_range` error (HTTP 422); the process-wide Decimal
context is untouched. All six declared rounding modes retain their exact
mapping, and unknown modes remain invalid.

The explicit 100-place output bound limits per-call work and result size while
retaining the previously accepted 29-place value. Consumers with units above
that bound must review and normalize them before `uom_0002` is applied.
