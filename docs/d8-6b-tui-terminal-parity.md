# D8.6B — Installed TUI, terminal identity, and cross-surface parity

D8.6B completes the D8.6 operator-surface migration by adding an installed,
zero-dependency `stygnox tui` terminal surface and a presentation-neutral
`stygnox operator` CLI. Both surfaces consume the same installed
`stygnox.operator` snapshot and action dispatcher used by D8.6A Web.

## Product boundary

D8.6B installs these surfaces:

```text
stygnox operator snapshot
stygnox operator action
stygnox tui
stygnox tui snapshot
stygnox tui action
```

The installed TUI does not import or delegate to `scripts/ralph_tui.py`,
`scripts/ralph.py`, or any target-project source-tree controller. The legacy
RALPH TUI remains compatibility/evidence material only.

## Terminal identity authority

The authoritative terminal identities remain:

```text
branding/assets/ascii/stygnox-ascii.txt
branding/assets/ascii/stygnox-ascii-ansi.txt
```

Exact copies ship as package data under `stygnox.terminal_assets`. Tests and the
installed-artifact qualifier compare SHA-256 digests against the committed
branding sources.

At terminals of 72 columns or wider the TUI renders the exact approved plain or
ANSI asset. Narrow terminals receive a compact Stygnox identity rather than
clipped artwork. `NO_COLOR` always disables colour, including when `--color
always` is requested.

Status and authority are never colour-only: textual markers such as `ADOPTED`,
`DISABLED`, `[HUMAN]`, `NO`, and numeric attribution counts remain present.

## Shared operator semantics

`stygnox operator snapshot`, `stygnox tui --json`, and the D8.6A Web
`/api/snapshot` endpoint expose the same `stygnox_operator_surface_v1` semantic
snapshot. Process-local server PIDs are presentation metadata and are excluded
from semantic parity comparisons.

Non-mutating adoption preview is qualified across:

1. direct installed CLI (`stygnox adopt preview`);
2. presentation-neutral operator dispatch;
3. TUI action dispatch; and
4. the D8.6A Web surface (whose parity with the shared dispatcher was already
   established in D8.6A).

All action surfaces retain exact preview/confirmation semantics from the
installed product modules. There is no automatic carry-forward, automatic
reattribution, or legacy fallback.

## Reconciliation presentation

The TUI shows the same D8.6A attribution categories:

- operator baseline;
- Stygnox/controller-native;
- runtime-only;
- external/foreign; and
- unresolved overlap.

External or unresolved material produces an explicit `[HUMAN]` indication.
The terminal does not convert that material into Stygnox-owned work.

## Qualification

Run:

```bash
python3 scripts/qualify_d8_6b_tui.py
```

The qualifier builds the exact wheel, installs it into a fresh virtual
environment and proves:

- installed TUI invocation;
- exact plain ASCII authority;
- exact ANSI ASCII authority;
- narrow-terminal fallback;
- `NO_COLOR` behaviour;
- operator/Web/TUI snapshot parity for new/unborn, clean and dirty projects;
- CLI/operator/TUI adoption-preview parity;
- refusal to import a hostile target-local `ralph_tui.py`; and
- independence from a Stygnox source checkout.

D8.6B closes D8.6. The next stage is D8.7 release packaging, documentation,
and release-wide installed-artifact qualification.
