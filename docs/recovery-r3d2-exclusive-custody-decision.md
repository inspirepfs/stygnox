# StygNox R3D.2 — Exclusive Custody Cutover Contract

**Decision draft — 13 October 2026**
**Source checkpoint:** `2769e6e` (operator-reported; no independent Git-object verification in this environment)
**Transaction:** `TX-a6379f065ce68138`
**Plan SHA-256:** `efe4acfaff25edc8fce015ec5c5f0e250a5f58e1a6a39ed569db71c5304cde03`
**Progress:** Step 2/4, one accepted step result, eight accepted continuations
**Disposition:** NO live cutover or provider execution authorised.

## Architectural decision

The required security property is **exclusive authority for the recovered transaction**. It is not a global prohibition on running arbitrary `stygnox`, Python, or Codex processes under the operator's UID. The latter is impossible to guarantee while UID 1000 retains unrestricted user-level code execution and existing OAuth credentials, without restricting unrelated sessions.

The original worktree `/home/pfsykes/stygnox-r3d2-astra` is UID-1000-owned, mode `0775`, beneath an untrusted-by-root home ancestor. A cooperative lock, AppArmor profile attached only to a known old binary, `chmod`, name/path rename, or negative `lsof` snapshot cannot guarantee that old/copy code cannot access the historical inode. In particular, chmod and rename **do not revoke pre-existing writable FDs**.

Therefore, the cutover must define the root broker as the sole recogniser of transaction authority. No old controller state, recovered state copied into a user-owned directory, or provider result produced outside the pinned successor execution contract may satisfy the new broker's admission, gate, attribution, or finalisation checks. The root broker must not import legacy controller approvals or infer grants from historic files.

The historical worktree must be **retired as a live authority source**, while evidence is preserved. An independently runnable old executable may remain runnable, but its actions must be unable to mutate or be accepted as the new authoritative transaction. The system must accurately report any remaining legacy-run possibility, not call it 'old binary execution impossible'.

## Pre-cutover preconditions

1. Re-verify the published root custody slot, isolated staged workspace and their complete inventories. Never re-publish the slots.
2. Establish the exact Git/source artifact from the `2769e6e` committed tree (not this document or the previous `a04f001` install) and verify SHA-256 plus member permissions at a root-controlled installation. Do not launch privileged code from the mutable Git tree.
3. Confirm no active process has an FD, cwd, root, mapping or mount reference to original **and** determine whether the legacy runtime can relaunch. The inventory is a snapshot, not enforcement.
4. Obtain explicit, recorded operator approval for *which exact host files will be changed*, before any retirement or service installation.
5. Test the complete operation on a disposable Linux VM with the same filesystem, systemd, AppArmor and UID layout. Root-only pytest on the production host is not a substitute.

## Integrated cutover protocol (one implementation, not separate micro-patches)

**Phase 0 — PREPARED_EXECUTION_DENIED.** Persist a sealed cutover intent in root-private storage. Bind the exact transaction, immutable approved plan and mutation-scope digest, 8/8 continuation hashes, last accepted Step-2 checkpoint, original dev/inode and tree evidence, isolated staged manifest, successor artifact digest, static successor UID/GID, project identity, and a fresh epoch. Reject unknown fields and unsealed records. Publish with O_EXCL and fsync; never silently repair `.pending`.

**Phase 1 — LEGACY_AUTHORITY_WITHDRAWN_EXECUTION_DENIED.** Withdraw trust from the old `.stygnox` root through a root-controlled, durable project registry/pointer. Legacy files MUST NOT be accepted as the authoritative recovered transaction after this point, even if UID 1000 recreates the original path or runs copied source. If the operator also authorises physical retirement, perform a separately reviewed, no-follow, same-filesystem, identity-checked preservation procedure for the original directory with an independently verified fallback. Do not pretend that path retirement revokes old open FDs. Treat any unreadable holder, inode substitution, or conflicting legacy write as DENIED and require manual reconciliation; never undo the pointer automatically.

**Phase 2 — SUCCESSOR_IDENTITY_COMMISSIONED_EXECUTION_DENIED.** Provision a dedicated static unprivileged UID and group. Run a separately root-owned supervisor/broker service with a UNIX socket owned by root and a dedicated group. `SO_PEERCRED` must match the pinned UID; reject root, UID 1000, unpinned executables, wrong epoch, wrong transaction, unexpected project, and wrong operation. No inherited operator home, general Codex OAuth, or parent environment. The broker owns authority records; the worker owns neither the authoritative record store nor any trust decision.

**Phase 3 — EPOCH_ADMITTED_EXECUTION_DENIED.** Atomically admit one exact service instance (boot ID, PID/start identity, executable digest, source artifact, project, epoch, transaction/plan/scope/checkpoint). Broker acknowledgement is not execution permission. Reject duplicate claims, PID reuse, stale boot, concurrent successor requests, altered installed source, corrupt records and partial commits. Persist durable denial on reboot and service crash. Any ambiguity leaves the transaction blocked.

**Phase 4 — RELEASE_ELIGIBLE_BUT_DENIED.** Hostile tests and an operator-reviewed report must show that old code can neither access the new authoritative files nor have any old work accepted by the broker, including pre-opened *old* FDs. Record any limitation preventing a literal prohibition on legacy Codex launches. Only then request a **separate** human approval for a single controlled Step-2 continuation. The release record must be single-use, scope-limited, and bound to the exact checkpoint and installed successor. Never replay continuations 1–8.

## Required hostile qualification

- Old binary and copied source run under UID 1000; neither gets broker authority or write access to the successor worktree.
- Old writable FD opened before cutover may still write historical inode; it must never write the new independent successor inode or produce accepted provider attribution.
- Path recreation, symlink/hardlink substitution, bind-mount aliases, untrusted home parent and service namespace escape must fail or prove isolation.
- One-winner atomic epoch admission, wrong transaction/plan/scope/artifact/boot/controller refusals.
- Crash at every durable phase boundary, `.pending` on restart, corrupted intent, checkpoint rollback, reboot without human release.
- Provider launch directly, from legacy scripts, and via successor before release must fail closed; the two unrelated Codex sessions must remain undisturbed.
- Systemd static UID, filesystem privileges, protected home/network, socket peer credentials and process identity verified against the **real unit**, not string assertions about unit contents.
- Full historical source suite and live installed-native fresh-process qualification, with every skip dispositioned.

## Decision and escalation

**Approved to implement/test offline:** this scoped authority model, with no live mutations and all providers denied.
**Not approved:** root retirement of the original user-owned checkout, installation/enablement of production services, root epoch publication, controlled continuation or `stygnox top`.

The root-only isolated workspace already exists and is verified as execution-denied. The epoch-reservation and denied broker source are committed, but no root epoch reservation or live broker commissioning is reported as complete. The root broker cannot simply be treated as a continuation controller; installed-product R3D.1 rebind and original bootstrap attribution still need formal qualification.

**Further architecture gate:** Before `stygnox top` development, the separate mandatory formal R3D.1–R3D.3 review requires explicit operator approval.
