# D8.6A — Installed Web operator UX — retired

## Historical status

D8.6A originally moved a Python-served Web operator console into the installed
Stygnox package. 13D-R2 explicitly retires that presentation surface after
operator use showed that it was not a viable foundation for the intended Web
experience.

The historical D8.6A work remains useful because it established the
presentation-neutral operator boundary later shared by the TUI. The retired
frontend itself is no longer a supported product surface.

## 13D-R2 disposition

The following installed Web material is retired:

- `stygnox web` and `stygnox serve`;
- `stygnox web-auth`;
- the installed Python HTTP/HTML console;
- package-local Web CSS/JavaScript/image copies;
- the D8.6A installed-Web qualifier; and
- Web tests whose purpose was to preserve the retired presentation or its
  browser/login implementation.

The following material is explicitly preserved:

- `stygnox.operator.operator_snapshot()`;
- `stygnox.operator.dispatch_action()`;
- the `stygnox operator snapshot` and `stygnox operator action` process
  boundary;
- canonical lifecycle/action schemas and controller-owned authority rules;
- TUI consumption of the same operator surface; and
- all authoritative branding sources under `branding/`.

The detailed replacement contract is documented in
`docs/web-ui-retirement.md`.

## Why this is an explicit retirement rather than a repair

The replacement Web UI is expected to be a ground-up implementation. It may be
an independent frontend application so long as it consumes the canonical
operator/controller boundary and does not create a competing authority model.
Retaining the old frontend would make obsolete rendering, controls, polling,
and browser tests an accidental compatibility contract.

Historical Ralph Web material remains source-only compatibility/evidence in
13D-R2 and is not an installed Stygnox path.

## Qualification after retirement

The Web-specific D8.6A runtime qualifier is removed. The surviving boundary is
qualified through:

- presentation-neutral operator regression tests;
- TUI/operator parity qualification;
- installed-package checks proving Web runtime/assets are absent; and
- 13D-R2 presentation-boundary tests proving retired commands fail closed,
  authoritative branding remains present, and the successor operator contract
  remains usable.
