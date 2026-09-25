# D8.7 post-extraction identity and runtime report

## Scope

This is the D9-G-16 post-extraction report for the D8.7 release candidate. It
separates installed-product authority from source-only migration,
characterization and historical compatibility material.

## Installed identity

| Concern | Installed D8.7 authority |
| --- | --- |
| Product identity | `Stygnox` |
| Console command | `stygnox` |
| Runtime directory | `.stygnox/` |
| Default profile | `stygnox-default` |
| Controller | installed `stygnox controller` |
| Execution policy | installed `stygnox execution-policy` |
| Web | installed `stygnox web`, loopback-only |
| TUI | installed `stygnox tui` |
| Operator model | installed `stygnox operator` |
| Supported install media | pip-installed wheel |

The wheel contains `stygnox.*` modules and approved Web/terminal assets. It does
not contain `scripts/ralph.py`, `scripts/ralph_web.py`, `scripts/ralph_tui.py`,
`ralph_profile.py`, target-project scripts, tests, or source wrappers.

AST import scanning of installed Python modules refuses imports whose module is
`ralph`, begins `ralph_`, or is below `ralph.*`. Hostile target/local decoy
fixtures are exercised by predecessor installed-artifact qualifiers.

## Runtime and tracked-policy boundary

Adopted projects use tracked `stygnox.toml` and `stygnox.policy.md` for reviewed
configuration/policy. Controller-owned state/evidence is written beneath
ignored `.stygnox/`. Runtime files do not substitute for tracked policy and are
not treated as native project delta.

The Stygnox development repository still has a tracked `.ralph/policy.md` and
`.ralph` ignore rules. Those belong to the historical extraction/source
compatibility environment and are not copied into an adopted project by the
installed product.

## Legacy `.ralph` and `zen_ralph_*` references

Legacy names remain intentionally in `stygnox.migration` and migration
documentation so supported old state can be identified, inventoried, retained,
rolled back and refused safely when unknown. In particular:

- `.ralph/` is a **legacy migration input**, never the installed default
  runtime;
- `zen_ralph_lite_state_v1` is a **recognized legacy input schema**, not the
  installed authority schema; and
- `legacy-ralph.tar` is retained migration evidence, not active controller
  runtime.

This is an explicit compatibility quarantine rather than an identity leak.
Unknown legacy state fails before migration mutation.

## Source-only compatibility controller

`scripts/ralph.py`, `scripts/ralph_web.py`, `scripts/ralph_tui.py` and related
source modules remain in the development/source-review archive because they are
needed for historical characterization, extraction evidence and retained
regression coverage. They are excluded from the installed wheel and cannot
satisfy installed-command resolution for adoption.

Operator-facing D8.7 instructions invoke the installed `stygnox` command. A
normal D8.7 workflow never instructs the operator to execute
`python3 scripts/ralph.py`.

## Import graph disposition

The installed package uses only relative `stygnox` imports plus Python standard
library modules. The D8.7 release qualifier scans wheel Python modules with the
AST and fails if a legacy Ralph import appears. String references to legacy
schemas/paths inside the migration module are permitted only because they are
data identifiers for the bounded migration path; they do not create an import
or execution dependency.

## Reconciliation and authority disposition

The installed operator model classifies current material as operator baseline,
controller-native, runtime-only, external/foreign, or unresolved overlap.
External/unresolved material raises a human-decision requirement and cannot be
automatically adopted or reattributed.

The retained legacy controller's carry-forward/self-hosting behavior remains
covered by source regression tests. It does not become an installed fallback.

## Release decision

D9-G-16 is satisfied only when `scripts/qualify_d8_7_release.py` reports:

- exact-wheel predecessor gates D8.1 through D8.6B all PASS with one wheel
  digest;
- wheel import scan PASS;
- target/source Ralph fallback isolation PASS;
- deterministic release rebuild PASS; and
- required operator/release/post-extraction documentation present in the
  release set and source-review archive.
