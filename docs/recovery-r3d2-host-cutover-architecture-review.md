# R3D.2 — Host cutover architecture decision and qualification gate

**Source baseline:** `a04f001` (13 October 2026)

**Decision status:** **NOT APPROVED FOR LIVE CUTOVER**. This is the host-specific
engineering assessment, not the later mandatory R3D.3 / `stygnox top` formal
architecture review. Neither the new code nor this document creates authority.

## Existing verified facts

- Root-owned blocked custody is published; its `root-custody.json` is `0400`.
- Root-owned isolated workspace is published and verified in **execution-denied** state.
- The original `TX-a6379f065ce68138` approved plan remains at step 2 of 4;
  one step result and eight accepted continuations must not be replayed.
- The original checkout `/home/pfsykes/stygnox-r3d2-astra` is owned by UID 1000,
  mode `0775`, beneath the predecessor-controlled home directory.
- Host: Ubuntu 6.8/ext4, systemd 255, AppArmor active, two unrelated Codex
  processes were observed on 13 October, no named Stygnox/Ralph process.
- The existing C3f retirement primitive deliberately requires **root-controlled
  ancestors**; it cannot safely retire this original checkout as currently
  located. Relaxing this check is not an acceptable fix.
- The protected `a04f001` source archive has SHA-256:
  `d1a97f8e6263339c6a360c5097cb471469bbe78cd5eee3372c212a1e446ed991`.

## Authority is not the same as the ability to invoke Codex

The old UID may run a copied Stygnox executable and even invoke Codex using
its existing user credentials. It cannot, however, become authoritative for
newly root-protected custody simply by writing a user-owned replica. The
protected controller/broker must *never* accept an old controller's records,
locks, approvals or result deltas as new-epoch transaction authority.

**A blanket assertion that UID 1000 cannot run Stygnox or Codex is not
achievable while preserving that user's general ability to execute tools.**
The enforceable requirement is: the original transaction's **authoritative
state**, process identity, plan and accepted deltas can be consumed only by the
new trusted runtime, and stale legacy work can never be adopted. We must also
prevent the old live workspace being accidentally used as a parallel active
R3D.2 runtime, not merely declare it deprecated in a JSON flag.

AppArmor being enabled is not a blanket path-deny policy for arbitrary
unconfined executables. A profile attached to the known old binary can be
bypassed using a copied binary or alternative interpreter path. Cooperative
locks, chmod on the original project, process-name checks, and `lsof` snapshots
are also insufficient. A preopened writable FD remains capable of modifying
its original inode after renaming or chmod. New source files in root custody
use independent inodes, but that does not retire the old program.

## Recommended integrated cutover design (one reviewed milestone)

1. **Freeze the authority contract, not unrelated sessions.** Bind the existing
   transaction, plan, scope, original inode/dev, current checkpoint, eight
   continuations, and source archive SHA to a root-owned cutover proposal.
   Verify the entire existing isolated workspace before any mutation.
2. **Create a dedicated root-controlled broker boundary.** A small privileged
   supervisor alone holds custody read/write permission. Run the successor
   provider/controller worker as an independent unprivileged UID, with no
   inherited Codex OAuth files or broad home access. Any worker credential
   should be separately provisioned only at a later approved release.
3. **Withdraw the old workspace through a reviewed Linux host protocol.**
   Because its parent is user-owned, the C3f primitive cannot simply be
   reused. The cutover implementation needs an independently tested mechanism
   with exclusive source identity and process handling, restart protection,
   and crash reconciliation. Merely renaming the original path and placing a
   file there leaves path-recreation and preopened-FD concerns unresolved.
   The original data must remain independently preserved in a root vault.
4. **Bind the successor service and epoch.** Require immutable installed
   artifact, service/user identity, project identity and runtime epoch;
   atomically admit one claimant; keep `execution_authority=NONE` at all
   transition steps. Never import historical unguarded source as the worker.
5. **Persist denial across boot and crash.** Ensure unit start paths deny any
   provider call unless a root-authoritative release record is present. A
   half-written journal, corrupt record, duplicate claim, PID reuse, or
   service restart must fail closed and require manual reconciliation.
6. **Qualify on a disposable Linux host.** Exercise competing claims, old and
   copied binaries, inherited/open FDs, cwd and mount aliases, restart/reboot,
   credentials, tampered source, cross-project admission and interruption
   boundaries. Preserve existing Codex sessions during production transition.
7. **Separate controlled release.** Only after a written hostile qualification,
   new executable/epoch binding, and explicit human sign-off may a single
   continuation be admitted. Accepted historical continuations must not rerun.

**Irreversible host mutation is explicitly OUT OF SCOPE of this package.**
The previous source handover instructed us not to mutate the live old workspace
without a reviewed and explicitly authorised cutover. That approval is still
required.

## This source overlay: hostile read-only gate

The new `direct_interruption_cutover_gate` module:

- verifies exact bytes of the existing `a04f001` root-owned installed archive
  and its installed file inventory, rejecting hardlinks, writable files,
  substituted directories, symlinks, unexpected files and incorrect content;
- verifies published root custody and every member of the isolated worktree;
- pins the original workspace device/inode, without opening its transaction;
- scans all visible Linux user processes, not just names, for old workspace
  cwd/root/exe/fd/map and mountinfo references; unreadable processes are not
  silently interpreted as quiescent;
- **always** returns exit 75, with `successor_execution_authorised=false`.

A scan without holders is a time-bounded observation, not a kernel-enforced
relaunch barrier or a claim that existing FDs are revoked. The CLI has **no**
flags to retire, publish, commission, approve, or execute. It is deliberately
useful as part of a future integrated cutover's hostile preconditions, while
remaining unable to perform a premature live transition.

## Exit criteria still missing

- Durable OS exclusion of the original recovered transaction from the legacy
  interpreter/binary and copies, with a strategy for path recreation;
- preopened FD handling and no unknown process holders at the cutover boundary;
- dedicated successor user/service and isolation proven against real UID 1000;
- atomic new controller/epoch admission and installed source identity;
- reboot/restart/crash/duplicate hostile host trials;
- operator-approved release of exactly one remaining Step 2 continuation;
- R3D.1 installed-product rebind and original bootstrap attribution assessment.

**Do not call this R3D.2 complete. Do not start `stygnox top`.**

## Denied-only independent process identity fixture

The accompanying `stygnox_recovery_successor_denied_probe.py` and
`recovery-r3d2-denied-successor.service.in` are **disposable-host qualification
fixtures**, not deployable controller units. They demonstrate how an independent
DynamicUser service can start without home/provider access and return a
controlled denial. The fixed probe never reads custody, never executes Codex,
and always exits 75. Unit hardening flags are inspectable intentions until a
separate, actual systemd-on-Linux hostile test proves them. Do not enable the
unit on `k3s-tanix85` or mistake an isolated UID probe for authority transfer.
