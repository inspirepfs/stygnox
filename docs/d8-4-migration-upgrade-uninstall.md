# D8.4 — Migration, Upgrade, and Uninstall

D8.4 closes the lifecycle boundary between the neutral installed Stygnox
product and supported legacy RALPH project state.  It does **not** enable
autonomous controller execution; D8.5 owns neutral controller/authority
activation.

## Supported environment and install media

D8.4 qualifies this bounded support contract:

- Linux;
- CPython `>=3.11,<3.14`;
- Git available on `PATH`;
- a versioned Python wheel installed with `pip` into a user-managed or isolated
  Python environment;
- no Stygnox source checkout is required by the installed command.

`stygnox support` renders the machine-readable support and compatibility policy.
Unsupported platform/runtime combinations refuse lifecycle mutation before
project change.

## Legacy migration contract

The supported legacy source is deliberately narrow:

- runtime directory `.ralph/`;
- `.ralph/state.json` schema `zen_ralph_lite_state_v1`;
- legacy state `IDLE`;
- no active legacy `controller_runtime`;
- regular files/directories only: symlinks and special entries are refused;
- only the known `.ralph` ignore rules are automatically removed. Unknown
  legacy ignore semantics require an operator-directed migration.

Migration also requires an already-confirmed neutral Stygnox adoption handoff
and an **ACTIVE** D8.3 transaction owned by the same named operator.

### `stygnox migrate preview`

Read-only.  It binds the exact transaction, Git baseline, legacy runtime
inventory, file modes/digests, legacy Git index entries, supported `.gitignore`
changes, installed command identity, and planned retained-evidence location to
one preview SHA-256.

A fresh project with no `.ralph/` runtime receives a clear no-change refusal:
migration is not required.

### `stygnox migrate apply`

Requires the exact preview plus `--confirm MIGRATE`.

Before changing the live legacy runtime it creates controller-owned evidence
under:

```text
.stygnox/migrations/MIG-<preview-prefix>/
```

The evidence includes:

- an exact self-created `legacy-ralph.tar` archive;
- file/directory inventory with SHA-256 and modes;
- the legacy tracked Git index identities;
- exact pre-migration `.gitignore` bytes;
- the pre-migration Git baseline;
- the supported legacy state summary.

The archive is extracted into an isolated directory and compared to the source
inventory before mutation continues.  The live `.ralph/` runtime is then
removed, legacy tracked index entries are removed, and supported `.ralph`
ignore rules are removed from the worktree `.gitignore`.

Legacy schema content is retained only as evidence.  It is never promoted into
active Stygnox authority.  `.stygnox/` remains the active neutral runtime.

A mutation failure attempts immediate restoration from the already-created
capture and records `FAILED_ROLLED_BACK`; a failed automatic rollback is a hard
operator-recovery error.

## Migration rollback

Rollback is deliberately separate from D8.3 full baseline restoration.

The operator first performs a D8.3 safe stop.  Then:

```text
stygnox migrate rollback-preview ...
stygnox migrate rollback ... --confirm ROLLBACK
```

Rollback refuses unless:

- the transaction is `STOPPED`;
- the migration is `APPLIED`;
- `.ralph/` has not reappeared;
- the project is still at the exact post-migration Git baseline;
- the retained archive/metadata digests verify.

Rollback restores:

- exact legacy runtime content and modes;
- exact pre-migration `.gitignore` bytes;
- exact legacy stage-0 Git index identities;
- the pre-migration Git baseline.

Neutral migration evidence is retained under `.stygnox/` after rollback so the
operator has an auditable extraction/rollback trail.

## Upgrade compatibility

D8.4 does not silently rewrite historical authority/evidence schemas during an
upgrade.

```text
stygnox upgrade preview ...
stygnox upgrade accept ... --confirm UPGRADE
```

The preview inventories retained runtime evidence and validates the known
authority schemas.  Project-state upgrade is supported from the D8.2/D8.3
`0.1.0.devN` compatibility line through the current D8.4 version.  Unknown
authority schemas, versions outside the supported line, unresolved migration
states, or an **ACTIVE** transaction refuse before change.

Acceptance writes only ignored `.stygnox/upgrade.json`; tracked project content
and retained historical evidence are not rewritten.

## Uninstall contract

Uninstall is two distinct operations:

1. project-side preparation with the installed Stygnox command;
2. external package removal with the environment's `pip`.

```text
stygnox uninstall preview ...
stygnox uninstall prepare ... --confirm UNINSTALL
<environment-python> -m pip uninstall -y stygnox
```

Preparation refuses an ACTIVE transaction.  When admissible it records:

- activity disabled;
- controller execution disabled;
- zero tracked-project mutation;
- zero retained-evidence deletion;
- ownership of tracked Stygnox policy/config as project material;
- ownership of `.stygnox/` and migration archives as operator-retained evidence;
- external package removal as the only package-deletion step.

Preparation is idempotent for the same exact preview.  Package uninstall does
not remove project configuration, project content, or retained evidence.

## Qualification

Run:

```bash
python3 scripts/qualify_d8_4_lifecycle.py
```

The qualifier builds one wheel, installs that exact artifact into a fresh venv,
and exercises only the installed command.  It proves:

- support-policy resolution;
- fresh legacy-migration no-change refusal;
- clean legacy migration and exact rollback;
- dirty migration and exact rollback with staged, unstaged, renamed, deleted,
  untracked, and staged/unstaged legacy-policy state preserved;
- migration archive readability;
- D8.3 runtime compatibility acceptance into D8.4;
- ACTIVE-transaction upgrade refusal;
- uninstall after retained legacy migration;
- idempotent uninstall preparation;
- actual `pip uninstall`;
- no tracked project mutation during upgrade/uninstall;
- retained evidence remains readable after package removal;
- no legacy Ralph import/source-tree fallback.

## Explicit D8.4 non-goals

D8.4 does not:

- enable autonomous controller execution;
- make a legacy RALPH schema an active Stygnox schema;
- neutralise the remaining source-tree controller/profile/model-policy seams;
- redesign Web/TUI/CSS or branding;
- delete operator-retained evidence during uninstall.

Those boundaries keep D8.5 authority neutralisation and D8.6 operator UX
independent and reviewable.
