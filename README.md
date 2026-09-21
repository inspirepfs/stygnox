# Stygnox

Stygnox is being physically extracted from the D6-frozen RALPH-Lite controller.

This repository seed is the **D7.1 extraction baseline**, not a public release.
It deliberately preserves the frozen controller and tests byte-for-byte so the
subsequent extraction stages can change structure behind behavioral-equivalence
checks rather than reimplementing behavior from memory.

## Current status

- D6 source/controller contract: frozen and provenance-bound.
- D5 behavioral-equivalence reference: included as extraction provenance.
- Controller implementation/tests: copied from the frozen source without edits.
- Product/package/API rename: not performed yet.
- Persisted `zen_ralph_*` schemas: retained as compatibility obligations.
- `.ralph` runtime/policy naming and `ZEN_PROFILE`: retained temporarily as
  known compatibility seams, not adopted as Stygnox product identity.

The next stages introduce the standalone protocol/core/runtime boundaries and
then replace the temporary host adapter without silently migrating persisted
state.
