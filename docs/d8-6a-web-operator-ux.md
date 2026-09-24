# D8.6A — Installed Web operator UX and reconciliation projection

## Outcome

D8.6A moves the Web operator surface across the installed-product boundary.
`stygnox web` is served by the wheel itself and never delegates to
`scripts/ralph_web.py`, a target-local controller, or any ZEN/RALPH host
adapter.

This is the first half of D8.6. D8.6B owns the installed TUI, ANSI/plain terminal
identity, final CLI/Web/TUI transcript parity, and the complete D8.6 release
gate.

## Branding authority

The runtime Web assets are derived from and byte-checked against the approved
brand source under `branding/`:

- `branding/css/design-tokens.css`;
- `branding/css/components.css`;
- `branding/assets/brand/stygnox-icon-128.png`;
- `branding/assets/brand/stygnox-logo-800x300.png`.

Operator-specific CSS follows the same dark-first, evidence-led rules. Purple
is used for focus/brand energy rather than as a page fill. Critical authority
or destructive state is always communicated with text in addition to colour.

## Installed Web command

```bash
stygnox web --project /path/to/project --host 127.0.0.1 --port 8765
```

D8.6A deliberately supports loopback only. Any non-loopback bind is refused
before the server starts and before authority can be changed. A future wider
binding policy, if retained, must be separately qualified at or after the full
D8.6 cross-surface gate.

Every POST mutation requires the exact server CSRF token. Arbitrary Web routes
and arbitrary action names fail closed.

## Shared operator semantics

`stygnox.operator` is presentation-neutral. Web uses it now and D8.6B TUI will
use the same adapter. Supported Web actions map directly onto installed product
functions for:

- adoption preview / abort / handoff;
- transaction begin / safe stop;
- recovery preview / exact restore;
- execution-policy preview / set / reset;
- controller activate / deactivate;
- controller run-preview / confirmed run.

No Web implementation is permitted to calculate weaker authority or bypass a
preview digest / explicit confirmation already required by the installed CLI.

## Carry-forward / reconciliation attribution

D8.6A exposes five visible classes:

1. **Operator baseline** — material already dirty before Stygnox authority.
2. **Stygnox native** — tracked bootstrap material or newly appearing paths
   attributed to a recorded write turn.
3. **Runtime only** — controller-owned `.stygnox/` evidence; never native Git
   product delta.
4. **External / foreign** — current project changes not attributable to the
   operator baseline or recorded Stygnox work.
5. **Unresolved overlap** — pre-existing dirty material that overlaps a write
   turn or otherwise cannot be safely attributed.

The classifier is intentionally conservative. A path already dirty before a
write turn is never silently reattributed to Stygnox. External and unresolved
material set `requires_human_decision=true`. The model records
`auto_adopt=false` and `auto_reattribute=false`.

D8.6A only makes attribution visible. Any future carry-forward disposition that
changes ownership remains a named human decision and is part of the final D8.6
cross-surface work.

## Controller receipt extension

Write-turn receipts now carry a bounded `change_attribution` record containing:

- newly appearing controller-native paths;
- pre-existing operator-baseline paths;
- unresolved overlapping paths; and
- pre-existing paths removed during the turn.

This is evidence, not automatic ownership. Read-only turns record an empty
attribution set.

## Qualification

`python3 scripts/qualify_d8_6a_web.py` builds the exact wheel, installs it into a
fresh virtual environment, and checks:

- new/unborn CLI/Web adoption-preview parity;
- clean CLI/Web adoption-preview parity;
- dirty admission refusal before external recovery evidence;
- Web handoff / transaction begin / neutral controller activation;
- neutral provider execution refusal;
- CSRF refusal for mutations;
- non-loopback refusal before authority;
- packaged branding;
- external/dirty attribution visibility; and
- refusal to import a hostile repository-local `ralph_web.py`.

D8.1 through D8.5 installed qualifiers and the full regression population must
remain green before D8.6A is committed.

## Explicitly outside D8.6A

- installed TUI and ASCII terminal branding;
- final CLI/Web/TUI parity on full dirty recovery journeys;
- any non-loopback Web authentication policy;
- visual polish that is not required for semantic/accessibility parity;
- D8.7 release packaging and final operator documentation.
