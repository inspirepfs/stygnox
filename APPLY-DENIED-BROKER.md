# R3D.2 denied-only successor broker — source-only qualification

**Base:** `804b7fa` (`fix/r3d1-reviewed-direct-interruption`). This overlay is a
source-development milestone, NOT a live systemd deployment or the approved
host-enforced predecessor retirement.

## Contents and authority limit

- `src/stygnox/direct_interruption_successor_broker.py` implements a Linux
  `SO_PEERCRED`-checked, exact transaction/plan/epoch/source-bound **denial-only**
  attestation protocol. It rejects UID 1000, root peers, wrong epochs, operations
  requesting execution, malformed messages, and socket-path reuse.
- `scripts/stygnox_recovery_denied_broker.py` is the guarded protected-source
  launcher. It validates artifact, root custody, staged lineage, reserved epoch,
  current boot and the dedicated UID before publishing any socket.
- `docs/recovery-r3d2-denied-broker.service.in` is a **disposable-host
  systemd rehearsal template**, not an enabled/live service.
- `tests/test_stygnox_direct_interruption_successor_broker.py` is the
  behavioural qualification, including an opt-in disposable-Linux root test
  using actual kernel credentials and a separate UID.

This code cannot retire the original workspace, revoke old FDs, implement
controller admission, approve release or execute Codex. The original transaction
must remain blocked. Never run the launcher as root from the checkout or
install/enable the service on `k3s-tanix85` at this stage.

## Apply and run source-only tests on the operator host

From `/home/pfsykes/stygnox-r3d1-direct-interruption-fix`:

```bash
# First verify the SHA-256 reported with the delivered archive.
# Confirm a clean baseline; the archive contains only five newly named files.
test "$(git rev-parse --short=7 HEAD)" = "804b7fa" || exit 1
test -z "$(git status --porcelain)" || exit 1

tar -tzf "$HOME/stygnox-r3d2-denied-broker-804b7fa.tar.gz"
# Only after validating the five expected members and SHA-256:
tar -xzf "$HOME/stygnox-r3d2-denied-broker-804b7fa.tar.gz" -C .

PYTHONPATH=src:tests python3 -m pytest -q -rs \
  tests/test_stygnox_direct_interruption_successor_broker.py \
  tests/test_stygnox_direct_interruption_epoch_reservation.py \
  tests/test_stygnox_direct_interruption_cutover_gate.py \
  tests/test_stygnox_direct_interruption_isolated_workspace.py \
  tests/test_stygnox_direct_interruption_host_readiness.py \
  tests/test_stygnox_direct_interruption_custody_cutover.py \
  tests/test_stygnox_direct_interruption_blocked_commissioning.py \
  tests/test_stygnox_direct_interruption_custody_intake.py \
  tests/test_stygnox_recovery_release_provider_dispatch.py \
  tests/test_stygnox_recovery_release_script_dispatch.py \
  tests/test_stygnox_recovery_release_boot_interlock.py \
  tests/test_stygnox_recovery_release_provider_preflight.py \
  tests/test_stygnox_direct_interruption_transfer.py \
  tests/test_stygnox_direct_interruption_publication.py

python3 -m compileall -q \
  src/stygnox/direct_interruption_successor_broker.py \
  scripts/stygnox_recovery_denied_broker.py

git diff --check
```

**DO NOT** set `STYGNOX_DISPOSABLE_LINUX_ROOT_TESTS` on the production host,
run a root pytest over the live checkout, publish an epoch reservation, or start
any service. The privileged UID/inode tests are intended for a disposable VM.

## Still required for actual cutover

1. Written operator-approved security contract: *legacy cannot exercise the
   new root-broker authority*, versus *legacy cannot execute any code*. The
   latter cannot be honestly guaranteed while UID 1000 retains unrestricted
   ability to launch tools and the original user-owned checkout remains present.
2. Host-reviewed retirement/invalidation of original **authority**, including
   pre-opened descriptors, aliases, processes and crash/reboot behaviour.
3. A real restricted successor controller worker, immutable installed artifact
   and transaction-bound **atomic admission**. This broker does NOT admit it.
4. Disposable-Linux systemd, UID, path, reboot and attack qualification.
5. Explicit operator cutover approval and a separate later provider release.

The hard formal architectural approval gate before `stygnox top` remains unchanged.
