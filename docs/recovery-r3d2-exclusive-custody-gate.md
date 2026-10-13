# R3D.2 — Host-enforced exclusive custody: source review and deny-only readiness gate

**Basis:** uploaded `527dd68` committed source archive; 13 October 2026 operator handover.
**Disposition:** **BLOCKED; no host authority granted.** This is a source-only contribution, not a production cutover.

## Current exact state

`ROOT_CUSTODY_PUBLISHED_EXECUTION_DENIED` at
`/var/lib/stygnox/recovery-r3d2-root-custody-blocked-v1` is the latest confirmed
host result. The original workspace `/home/pfsykes/stygnox-r3d2-astra` still
contains transaction `TX-a6379f065ce68138`, approved plan digest
`efe4acfaff25edc8fce015ec5c5f0e250a5f58e1a6a39ed569db71c5304cde03`,
Step 2 of 4 and eight accepted continuations. Neither successor execution nor
predecessor exclusion is established. The prior publisher's exit `75` is an
intentional denial, not an error to work around.

No previous preservation, projection or root-custody publication is to be
repeated. Preserve the original workspace and all accepted continuation records.

## What inspection of source `527dd68` established

| Existing source | Proven behavior | Missing property |
|---|---|---|
| `direct_interruption_custody_cutover.py` | Root-private, digest-bound, deny-only custody publication | Revocation of independently running predecessor |
| `direct_interruption_retirement.py` | Rename from a **trusted root-owned parent** into root-private vault | Cannot operate directly on the user-owned home ancestor; cannot revoke open FDs |
| `direct_interruption_process.py` and batch/nonchild drain | Exact-process observation and pidfd handling | Host-wide quiescence and future relaunch exclusion |
| `direct_interruption_workspace.py` | DAC/tree structural inspection | Path alias and mount namespace proof |
| `direct_interruption_durable_exclusion.py` | Durable **blocked** journal | Kernel policy enforcement or authority transfer |
| `direct_interruption_credential_isolation.py` and provider identity/preflight | Disposable identity/credential isolation checks; block providers | Revocation of pre-existing legacy OAuth or admission to real successor |
| `direct_interruption_execution_guard.py` | Cooperative runtime quarantine tripwire | Independent old binary enforcement |
| `direct_interruption_supervisor.py` | Blocked namespace publication for restricted root-anchored layouts | Live authenticated one-owner handoff and exclusion of unknown holders |

A root-only clone is not, by itself, evidence that the independently runnable
old binary cannot continue work on the **original** writable workspace.
Changing a file's owner, renaming its path, writing a lock or scanning `/proc`
provides no global assurance against preopened FDs or unobserved mount aliases.
An unprivileged user with a still-valid provider token may also run a copied
controller. None of these are grounds to issue transaction authority.

## Added source-only inspection

`direct_interruption_host_readiness.py` and
`scripts/stygnox_recovery_host_readiness.py` verify the **existing** root slot:

- trusted root/private directory ancestry (live entry only);
- exact expected directory membership and inode type, owner, mode, hardlink count;
- no unexpected `.pending` for the two custody-related publishers;
- byte-canonical, digest-bound contents of all six published records;
- exact original transaction/plan lineage, Step 2 and eight continuations;
- quarantined plan/controller/transaction and all explicit false-authority flags.

The inspection never touches the live checkout, never reads actual OAuth
credentials, never opens a provider and never writes to root custody. It always
returns exit `75`, reporting `EXCLUSIVE_CUSTODY_NOT_PROVED` when root custody is
intact or `HOST_READINESS_REFUSED` if verification is incomplete. Neither output
is an authorisation receipt. Running this source as root from a mutable Git
checkout is **not** an authorised deployment process.

## Next **single integrated** implementation milestone (not yet delivered)

One reviewed, installed, root-controlled cutover command must integrate these
host-specific pieces before any live mutation:

1. **Preflight and topology evidence:** confirm actual kernel, filesystem, LSM,
   mount-namespace relationships, user/session processes and executable/source
   identity. Root-private, immutable evidence must be fresh. Refuse any unknown
   holders, unexpectedly running predecessor or inconsistent mount view.
2. **Kernel predecessor barrier:** prove that **every** legacy UID entry path to
   this transaction is denied, including independent old binaries, copied
   scripts, alternative aliases and already-open handles. A cooperative lock,
   `chmod`, scoped process list or unshared mount alone is insufficient. Choose
   a mechanism genuinely supported by the host (e.g. a suitably configured LSM
   plus immutable root/private custody and controlled namespace transition),
   then test it **from the legacy UID and previously existing processes**.
   Verify persistence across reboot; do not broadly disable unrelated Codex.
3. **Quiescent transfer:** atomically exclude old writers/readers of the live
   transaction and transfer a verified, immutable snapshot to a root-controlled
   canonical successor worktree. Record original inode/path and epoch lineage.
   Refuse unverified changes; do not replay accepted continuations.
4. **Commission service:** bind a distinct, unprivileged successor runtime
   identity to the exact installed source artifact, project, transaction, plan,
   scope, eight continuations, checkpoint, epoch and root custody; give it no
   inherited user home/provider credentials. Root owns admission records; one
   atomic claim is permitted. An inability to establish these bindings leaves
   the provider dispatcher blocked.
5. **Hostile end-to-end qualification:** exercise an active and a stale old
   controller, simultaneous successors, copied old entrypoints, open writable
   FDs, nested mount views, wrong transaction/plan/epoch, corrupt and pending
   journals, kernel policy failure, crash at each transfer boundary, fresh
   process, reboot/no-release and credential escapes. Observe actual system
   behavior, not mock-only assertions.
6. **Human release gate:** **separate** root-only qualification receipt and
   explicit operator approval must precede any *single* controlled continuation.
   Do not use this new custody scan as an approval. Fail closed on every crash.

**Decision point:** The actual Linux host's enforcement capabilities, preopened
FDs, source install identity, and service configuration are not included in the
`527dd68` tarball. It would be unsafe to invent them or claim the cutover is
host-enforced solely from local fixture tests. Consequently, real cutover and
execution remain denied until a host-qualified implementation is reviewed.

## Read-only operator checks (existing host, no cutover)

These inspect the already-published custody and host topology; they **do not**
recreate any preservation or touch the original transaction. They do not print
provider credentials.

```bash
# On k3s-tanix85; operate from an interactive login, not Stygnox itself.
sudo stat -c '%U:%G %a %F %n' \
  /var/lib/stygnox \
  /var/lib/stygnox/recovery-r3d2-root-custody-blocked-v1 \
  /var/lib/stygnox/recovery-r3d2-root-custody-blocked-v1/root-custody.json
sudo find /var/lib/stygnox -maxdepth 1 -name '*pending*' -print
stat -c '%U:%G %a %d:%i %F %n' \
  /home/pfsykes/stygnox-r3d2-astra \
  /home/pfsykes/.local/share/stygnox/r3d1-83561511978582c75af43f31/bin/stygnox
sha256sum /home/pfsykes/.local/share/stygnox/r3d1-83561511978582c75af43f31/bin/stygnox
findmnt -T /home/pfsykes/stygnox-r3d2-astra -o TARGET,SOURCE,FSTYPE,OPTIONS
cat /sys/kernel/security/lsm 2>/dev/null || true
systemctl is-active apparmor 2>/dev/null || true
```

Only **after** an exact source commit, repeatable tested build and reviewed
promotion to a **new** root-owned protected source deployment may its audit
entry be used as a read-only root inspection. Do not execute arbitrary Git
checkout scripts with `sudo` for this purpose. Exit `75` remains expected.

## Programme disposition

R3D.2: **not complete**. R3D.1 upgrade/rebind must also be separately
qualified. R3D.3, formal architecture review, R3D.4 (`stygnox top`), R3D.5,
R3E/R3F, Controller API and core lock remain in programme order. In
particular, **no `stygnox top` implementation is permitted before the formal
architecture review and explicit operator approval**.
