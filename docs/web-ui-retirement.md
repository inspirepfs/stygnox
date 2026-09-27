# Web UI retirement and replacement boundary

## Status

The installed Stygnox Web UI is explicitly retired by 13D-R2. The retired
surface is not a supported operator path and must not be incrementally repaired
or revived.

The retirement removes the installed HTML/CSS/JavaScript console, its packaged
Web assets, Web authentication command, Web server command, Web-specific
qualification gate, and tests that only preserve the retired presentation.

## Preserved authority boundary

Web retirement does not change controller authority. A replacement UI must
consume the presentation-neutral installed operator surface rather than
reimplementing lifecycle, policy, gate, recovery, reconciliation, qualification,
finalization, provider-usage, or execution authority.

The preserved Python boundary is:

```python
from stygnox.operator import operator_snapshot, dispatch_action
```

- `operator_snapshot(project)` returns the canonical
  `stygnox_operator_surface_v1` projection, including lifecycle blockers and
  authority-valid `next_actions`.
- `dispatch_action(project, action, payload)` dispatches one exact installed
  action and returns `stygnox_operator_action_v1`. It delegates to the same
  controller-owned preview/confirmation functions used by the CLI and TUI.

The preserved process boundary is:

```bash
stygnox operator snapshot --project /path/to/project
stygnox operator action \
  --project /path/to/project \
  --name <canonical-action> \
  --payload-json '<json-object>'
```

A future browser/Node/TypeScript application may place a transport layer in
front of this contract, but that transport must not manufacture actions,
weaken preview digests, duplicate controller state, or infer authority from
presentation state.

## State ownership for Web UI vNext

Controller/operator state is authoritative server state. A replacement frontend
may own transient presentation state such as open panels, form drafts, local
selection, and view preferences. It must not maintain an independent lifecycle,
plan, gate, reconciliation, qualification, finalization, or provider-authority
state machine.

Controls must be derived from canonical `next_actions`. An action that is not
present in the current operator snapshot is not a valid UI action merely because
a component knows how to render a button for it.

## Branding authority

Branding is deliberately outside the retired Web implementation and remains
protected for the replacement UI and future TUI alignment. The authoritative
sources remain under `branding/`, including:

- `branding/design-tokens.json`;
- `branding/css/design-tokens.css`;
- `branding/css/components.css`;
- `branding/assets/brand/`;
- `branding/assets/ascii/`;
- `branding/docs/STYLE_GUIDE.md`.

The retired package-local Web copies are not branding authority. Future Web UI
work must consume or derive from the committed `branding/` sources rather than
recreating a separate visual identity.

TUI branding changes are intentionally outside 13D-R2. They should be handled
as a later bounded branding round using the same authoritative Stygnox identity.

## Legacy source-tree Web material

`scripts/ralph_web.py` and its Ralph characterization tests remain quarantined
source-only compatibility/evidence material in 13D-R2. They are not installed,
are not a supported Stygnox operator surface, and must not be used as the basis
for the replacement UI. Removing historical Ralph evidence is a separate
cleanup decision so that Web retirement does not silently discard extraction
provenance.

## Replacement acceptance boundary

A future Web UI relaunch is a new implementation, not a repair of the retired
frontend. Before it is accepted it must prove, at minimum:

1. canonical snapshot consumption without duplicated authority state;
2. action availability derived from canonical `next_actions`;
3. exact preview and confirmation semantics through `dispatch_action` or a
   contract-equivalent transport;
4. live status/log behaviour against controller-owned evidence rather than
   hard-coded presentation state;
5. use of the authoritative Stygnox branding system;
6. meaningful browser behavioural tests rather than static markup assertions;
7. accessibility validation; and
8. fresh verification evidence before completion is claimed.
