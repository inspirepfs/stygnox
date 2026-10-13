# R3D.2 integrated authority cutover — implementation and withheld live gate

**Source baseline:** operator-verified `2769e6e` (reconstructed here from `89a0fb6` source plus the two committed overlays; not an independently verified Git tree).
**Recovered transaction:** `TX-a6379f065ce68138`; approved plan `efe4acfaff25edc8fce015ec5c5f0e250a5f58e1a6a39ed569db71c5304cde03`.
**Stage:** Step 2/4; eight accepted continuations preserved. No continuation/replay/provider release.

## What the code does

`direct_interruption_authority_cutover` is the root-only, deny-by-default authority registry for the *new* transaction broker. It does not open or modify the original home workspace. Its exact three-phase journal is:

1. `PREPARED_EXECUTION_DENIED`: verifies and pins the approved transaction, original project dev/inode, canonical custody record, independent staged workspace manifest, pre-reserved epoch, exact source archive digest, dedicated UID and boot ID.
2. `LEGACY_UNTRUSTED_EXECUTION_DENIED`: makes the legacy workspace inadmissible to the **new root broker**. It is a trust decision in the new authority namespace, not a claim that a process running copied old code is impossible. No in-place chmod, rename, deletion, or false FD revocation.
3. `SUCCESSOR_ATTESTED_EXECUTION_DENIED`: the broker records precisely one dedicated unprivileged process's *kernel-authenticated* UID/PID and `/proc/<pid>/stat` start time. A different PID, reused PID, altered boot, wrong source, wrong transaction, or wrong epoch cannot claim this attestation. The same process can re-attest; crashed/restarted worker cannot automatically replace the record.

Each phase is root-private, sealed and hash-linked, written once via O_EXCL, fsync and rename. A pending/interrupted record permanently denies operation until reviewed manually. Registry readers demand exact, unmodified phase membership. Broker startup now requires an existing `LEGACY_UNTRUSTED` or `SUCCESSOR_ATTESTED` chain tied to the verified installed artifact and custody; no readiness claim from simply launching the broker. The socket still exposes **only** `attest-denial` and produces no execution capability.

The fixture worker is intentionally nonexecuting; it retains the admitted PID while running and exits without authorising work. Service templates are not to be installed or enabled on the live host yet.

## The unresolved host-enforcement distinction

This protocol *prevents UID 1000 and other unmatched peers from being admitted by the new broker*. It does **not** prevent the old user-owned Stygnox checkout from running standalone and writing its old files. Under the user's unrestricted UID and credentials, Linux cannot promise no old binary can be launched or that old writable FDs are revoked. This limitation must remain explicitly disclosed and fully dispositioned by the operator. New Stygnox must never import its outputs, approvals, or provenance.

There is also **no production CLI that publishes the new authority chain** in this overlay. Publication requires exact protected-host source verification, original-workspace quiescence, a disposable-Linux full rehearsal (including UID and socket test), a documented rollback/reconciliation plan, and separate explicit operator approval for the live root-side mutation. The library primitives alone do not justify operating the live state.

## Qualification needed before a live cutover

- Compare built artifact and file inventory with the **new committed** version, not old `a04f001` / `89a0fb6` constants. `gate.SOURCE_SHA256` and `gate.SOURCE` are pinned to the old protected install; the next source deployment needs revised bindings under an explicitly reviewed migration, not silent reuse.
- Verify real Linux systemd unit restrictions, exact dedicated UID/GID, socket ownership and `SO_PEERCRED` behavior. Check `systemd-analyze security` and actual cgroup process identities. No default DynamicUser substitute.
- Reconcile root custody and independent staged manifest **again** before phase-0 publication. Fail if either is missing, altered, or pending. Do not republish them.
- Recheck original workspace dev/inode and all process references, accounting for scan races; independently document the old-UID remaining access risk. Do not auto-chmod/rename a user-owned home path. No unrelated Codex termination.
- Hostile VM tests of crash-before/during/after phase publication, reboot, copied old code, pre-opened old FD, aliases, UID denial, different PID/start, corrupt/foreign manifest, untrusted path parents and service restarts. All ambiguity denies.
- Audit and qualify full R3D.1 installed-product rebind and pending adoption-config attribution before any execution release.
- Record **separate human approval** for host mutating cutover and for a later single, exactly bound Step-2 continuation. No release path exists in this overlay.

The formal R3D.1–R3D.3 review before any `stygnox top` implementation remains mandatory. Do not use this fixture as a way to start `stygnox top` development.
