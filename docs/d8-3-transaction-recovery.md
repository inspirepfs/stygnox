# D8.3 — clean/dirty transaction and baseline recovery

## Status

D8.3 adds installed, product-neutral transaction and recovery semantics on top
of the D8.2 adoption handoff.  It does **not** enable autonomous controller
execution.  The installed package remains independent of legacy Ralph modules
and source-tree controller entrypoints.

Product version: `0.1.0.dev3`.

## Boundary

D8.3 owns:

- transaction authority bound to the exact D8.2 handoff baseline;
- refusal when the project changes between handoff and transaction start;
- explicit `BEGIN`, `STOP`, and `RESTORE` human confirmations;
- safe-boundary authority revocation before restoration;
- exact recovery preview binding and stale-preview refusal;
- controller-owned pre-authority checkpoints for new/unborn and clean journeys;
- operator-owned external recovery packages for dirty journeys;
- dirty recovery validation for staged, unstaged, renamed, deleted, untracked,
  mode, type, content, raw-index, and empty-directory evidence;
- exact post-restore Git/worktree comparison; and
- retained `.stygnox/` evidence without polluting the restored baseline.

D8.3 does **not** own:

- autonomous controller/agent execution;
- migration/extraction from legacy ZEN/RALPH state;
- upgrade or uninstall;
- neutral controller/profile/model-effort authority; or
- Web/TUI presentation.

Those remain D8.4-D8.6 work.

## Installed command surface

After an explicit D8.2 handoff:

```bash
stygnox transaction begin \
  --project /path/to/repo \
  --operator 'Named Operator' \
  --confirm BEGIN

stygnox transaction status --project /path/to/repo

stygnox transaction stop \
  --project /path/to/repo \
  --operator 'Named Operator' \
  --reason interrupted \
  --confirm STOP

stygnox transaction recover-preview \
  --project /path/to/repo \
  --operator 'Named Operator' \
  --post-handoff-disposition discard

stygnox transaction restore \
  --project /path/to/repo \
  --operator 'Named Operator' \
  --preview <exact-preview-sha256> \
  --confirm RESTORE \
  --post-handoff-disposition discard
```

`recover` is accepted as an alias for `transaction`.

The only D8.3 post-handoff disposition implemented by the installed command is
`discard`.  That choice must be explicit.  Operators who wish to preserve
post-handoff work must preserve it externally before requesting restoration.
Stygnox will not silently decide what operator work can be discarded.

## New/unborn and clean recovery custody

After the operator explicitly confirms the D8.2 handoff, Stygnox creates an
ignored controller-owned checkpoint under:

```text
.stygnox/recovery/
```

The checkpoint contains a worktree archive, Git index snapshot when present,
manifest, modes, digests, and the exact pre-authority baseline binding.  It is
created only after `HANDOFF` authorization and is not project-native delta.

At transaction start Stygnox revalidates that the project still matches the
post-handoff authority baseline.  A changed project refuses `BEGIN` rather
than broadening authority implicitly.

## Dirty recovery custody

Dirty recovery remains operator-owned and outside the adopted worktree.
D8.2's attestation is still required at handoff.  D8.3 additionally requires
that the attestation bind an external manifest:

```json
{
  "manifest_path": "/operator/evidence/manifest.json",
  "manifest_sha256": "<sha256>"
}
```

The manifest schema is:

```text
stygnox_operator_recovery_manifest_v1
```

It binds:

- the D8.2 baseline SHA-256;
- raw `.git/index` capture integrity;
- the complete worktree manifest;
- paths, types, modes and content digests;
- symlink targets;
- required empty directories; and
- the manifest digest itself through the external attestation.

Stygnox validates the archive and manifest against the recorded baseline before
transaction authority can become active.  A changed archive, manifest, staged
state, unstaged state, dirty category, mode, type, or content refuses the
transaction.

The controller does not create or copy the dirty recovery package into its
runtime and therefore does not become its sole custodian.

## Safe stop and restoration

Restoration is unavailable while a transaction is `ACTIVE`.  The operator must
first record a safe stop with `--confirm STOP`.  The recovery preview then
binds:

- the stopped transaction record;
- current project baseline;
- target pre-authority baseline;
- recovery source and digests; and
- explicit post-handoff disposition.

Any project or recovery-evidence change after preview makes the preview stale
and restoration fails before mutation.

Before restoring tracked project material, D8.3 records `/.stygnox/` in the
repository-local `.git/info/exclude`.  This allows the original `.gitignore`
to be restored exactly while retaining controller evidence without making the
restored project appear dirty.

The restore path never uses broad `git clean` or an unscoped destructive reset.
It restores the recorded index/worktree material and then requires the exact
pre-authority baseline digest to match before reporting success.

## Qualification

Run:

```bash
python3 scripts/qualify_d8_3_transactions.py
```

The installed-wheel qualification covers:

- new/unborn, clean, and fully dirty repositories;
- pre-handoff interruption revalidation;
- exact handoff-to-transaction binding;
- safe stop and authority revocation;
- stale recovery-preview refusal;
- operator-confirmed restoration;
- dirty manifest tamper refusal;
- staged/unstaged/renamed/deleted/untracked restoration;
- modes and empty directories;
- retained ignored runtime evidence; and
- Ralph-decoy isolation.

D8.1 and D8.2 installed-artifact qualifiers remain required compatibility
checks.  D8.4 is the next stage and owns migration, extraction, upgrade, and
uninstall.
