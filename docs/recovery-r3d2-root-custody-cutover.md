# R3D.2 integrated blocked root-custody cutover

Source checkpoint: `426572f` plus the blocked commissioning source overlay.

## Purpose

Combines the full **609-file protected evidence audit**, continuation/controller provenance,
sealed intake and blocked commissioning into **one** root-controlled, one-shot
publication. The old workspace at `/home/pfsykes/stygnox-r3d2-astra` is NEVER
opened or modified. The protected unguarded historical source is treated as
**data only**. There is no subprocess, provider execution, credential access,
controller import, worktree checkout, or operator release.

### Concrete output

`/var/lib/stygnox/recovery-r3d2-root-custody-blocked-v1` (root:root, 0700),
with canonical SHA-256 sealed, mode 0400:

- `custody-intake.json` — verified reconstruction evidence receipt;
- `root-custody.json` — lineage, explicit deny states and hash commitments;
- `.stygnox/plan.json` — historical results/history intact, `RECOVERY_QUARANTINED`;
- `.stygnox/controller.json` — controller and provider disabled;
- `.stygnox/transaction.json` — transaction execution disabled;
- `.stygnox/direct-interruption-quarantined-binding.json` — ordinary-runtime refusal marker.

An atomic rename, fsync and no-overwrite operation publishes the directory.
A `.pending` directory after a crash causes **manual reconciliation**, not
an automatic retry or rollback. The CLI **always exits 75**, including after a
successful storage operation, so it cannot enable service startup.

Unlike the previous two stages, host-side evidence intake and commissioning
are computed **in memory in one privileged operation**; neither earlier staging
operation has to be run independently.

## Remaining execution blockers — non-negotiable

This provides exclusive DAC-enforced control of the **new root-owned store**.
It does **not** fence the old user-owned workspace, revoke independently valid
Codex OAuth, deny the legacy binary new launches, invalidate open FDs, prevent
legacy provider calls, prove boot service installation or provision a distinct
successor provider identity. A legacy process can still act on its old workspace.
Thus **transaction execution authority has NOT been transferred**.

There is no authorising execution-release path in this patch; the 02I boot
interlock and 02N/02O provider denial remain unchanged. A safe operational
continuation must commission a distinct protected successor worktree and provider
identity, keep this store inaccessible to the old UID, and separately address the
uncooperative legacy execution threat at the host/provider boundary.

## Operator boundary

Do **not** execute this code as root from a user-writable Git clone. It must first
be installed in an independently validated root-owned, non-user-writable source
deployment with custody-intake and blocked-commissioning dependency modules.
Run only after reviewing the installed files and root-owned preservation inputs.
No operation should be run against the original R3D.2 workspace as part of this
stage. The lack of any provider release here is intentional.
