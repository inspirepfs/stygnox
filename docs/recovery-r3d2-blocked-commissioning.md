# R3D.2: blocked custody commissioning (source after `426572f`)

This change **does not authorise a successor**. It bridges the root-private
`recovery-r3d2-custody-8030ff3/custody-intake.json` receipt to a second,
**data-only**, root-private worktree projection. The live transaction at
`/home/pfsykes/stygnox-r3d2-astra` remains untouched. No credential access,
provider execution, source import from the historical reconstruction, process
termination, namespace retirement or provider release occurs.

## Input contract

- Pinned transaction `TX-a6379f065ce68138`, approved plan
  `efe4acfaff25edc8fce015ec5c5f0e250a5f58e1a6a39ed569db71c5304cde03`
  and source baseline `1072451db2c85b340e4c78a7b895190ef1b3f5cd`.
- The custody-intake record must already exist in **root-controlled** storage.
  It must be canonically sealed and exactly match a new full, 609-file
  `audit_protected_intake()` reconciliation. Nothing is inferred from an
  untrusted user file or from a human-transcribed success message.
- The original preserved `plan.json`, `controller.json`, `transaction.json`
  must be self-hash valid, refer to the same transaction, and match their
  original recorded controller/transaction hashes. No restart, rebase,
  replay or re-plan is allowed.
- The privileged CLI must be deployed with both data-only modules under a
  **root-owned, no-user-write, separately verified deployment directory**.
  Never `sudo` a script from the user-owned Git checkout.

## Output (after a separate, explicitly approved host operation)

The only write would be a new
`/var/lib/stygnox/recovery-r3d2-blocked-commissioning-426572f` directory,
created via a `.pending` directory, fsync and atomic rename. Publication is
one-shot and interrupted attempts remain blocked pending manual reconciliation.

The new directory contains only `.stygnox/plan.json`, `.stygnox/controller.json`,
`.stygnox/transaction.json`, `.stygnox/direct-interruption-quarantined-binding.json`
and `blocked-commissioning.json`.

- Plan becomes `RECOVERY_QUARANTINED` and has
  `execution_authority_granted=false`.
- Controller has `enabled=false`, `controller_execution_enabled=false`,
  `provider_execution_ready=false`.
- Transaction becomes `RECOVERY_QUARANTINED`, with
  `authority.controller_execution=false`.
- Every record is separately canonical-hashed, and the quarantine marker is
  wired to the existing ordinary-runtime refusal guard.
- Historical Step 1 result and all eight continuation entries are preserved
  without mutation in the projected plan. Original hashes are recorded in the
  marker as **historical provenance**, not accepted successor execution authority.

This directory deliberately has **no executable source, provider credentials or
Git working tree**, and is not suitable as an active controller project.
The CLI always exits status **75** even when projection publication succeeds;
a service manager must not interpret successful reconciliation as startup
permission.

## What is not established

The original workspace has **not** been fenced or retired. The old installed
StygNox executable and potentially valid Codex OAuth for the original UID
remain possible execution paths. A privileged rename under a user-writable
home directory would not be a complete permanent exclusion: the same user
could recreate names, while already-open file descriptors would survive a
rename. The legacy UID must never be able to write the *authoritative* store;
external provider authority and unobserved old processes need their own
operator-reviewed controls.

**Next engineering boundary:** a root-controlled, restart-safe predecessor
exclusion / transaction custody cutover whose proofs are pinned to this
receipt, followed by independently commissioned isolated successor execution
and an explicit one-turn human release. Neither this projection nor its
passing tests authorise changing the original workspace.
