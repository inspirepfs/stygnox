# R3D.2 — Atomic successor epoch reservation (source only)

**Baseline:** exact clean `89a0fb6` checkout on `fix/r3d1-reviewed-direct-interruption`.

**Change:** `src/stygnox/direct_interruption_epoch_reservation.py`, its hostile regression tests, and programme reconciliation. This is a concrete, durable, one-winner root-private epoch *reservation* primitive; **it is not execution admission, a live predecessor-exclusion mechanism, or controller commissioning**.

### How to apply the verified overlay

Put `stygnox-r3d2-epoch-reservation-89a0fb6.tar.gz` in `/home/pfsykes/`.

```bash
(
  cd "$HOME/stygnox-r3d1-direct-interruption-fix" || exit 1
  ARCHIVE="$HOME/stygnox-r3d2-epoch-reservation-89a0fb6.tar.gz"

  test "$(git rev-parse --short=7 HEAD)" = '89a0fb6' || exit 1
  test -z "$(git status --porcelain)" || exit 1

  # Check the independently supplied archive digest before extraction.
  echo 'PASTE_VERIFIED_SHA256_HERE  '"$ARCHIVE" | sha256sum -c - || exit 1

  echo '=== MEMBERS ==='
  tar -tzf "$ARCHIVE" || exit 1

  echo '=== VERIFY GOVERNANCE BASELINE ==='
  printf '%s  %s\n' \
    '981662b75922a23b29f80865d73ad70a0c15db51ed5b466d02edefe61aee1f7c' 'docs/programme/ISSUES.md' \
    'a1364507db30fd64d2ccd394b428ca9b9589fa6ee217ad3621d8d06d4050b861' 'docs/programme/PROGRESS.md' \
    'a0b77b080911b9a8b9de583038a2555e64f058b2ea8ffb8c92fd3195370d38d0' 'docs/programme/STYGNOX-ROADMAP.md' | sha256sum -c - || exit 1

  echo '=== APPLY ==='
  tar -xzf "$ARCHIVE" -C . || exit 1

  echo '=== SOURCE TESTS ==='
  PYTHONPATH=src:tests python3 -m pytest -q -rs \
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
    tests/test_stygnox_direct_interruption_publication.py || exit 1

  python3 -m compileall -q src/stygnox/direct_interruption_epoch_reservation.py || exit 1
  git diff --check || exit 1
  git status --short
)
```

Replace `PASTE_VERIFIED_SHA256_HERE` with the digest supplied alongside this archive. **Do not run this placeholder command unchanged**.

### Host safety and permissions

- Do not run this repository's tests with `sudo` on `k3s-tanix85`. The real unprivileged-UID test is an **opt-in, disposable-root-host-only** test using `STYGNOX_DISPOSABLE_LINUX_ROOT_TESTS=YES_I_AM_DISPOSABLE`.
- Do not import the new module into the old controller. Do not execute `prepare_live_reservation` on the production host. It is not exposed by the production CLI; it requires independent protected source promotion, an explicitly pinned exact new archive, a distinct service account, and separate approval before a one-shot publication.
- The existing blocked custody and isolated workspace slots are authoritative evidence and **must not be overwritten**.
- Never change the old workspace or execute providers during this milestone.
- Root only can hold the new reservation. Even a valid reservation still explicitly has `predecessor_execution_excluded=false` and `successor_execution_authorised=false`.

### Verified scope vs. unproved scope

Verified in disposable source tests: immutable identity-bound record shape, atomic `mkdir` one-winner publication, durable `.pending` on an interrupted write, rejection of stale/tampered/extra/hardlinked/symlinked records, checks for a different epoch/UID/artifact, and an opt-in unprivileged UID denial test.

Not established: policy preventing copied/relaunched legacy code accessing the original home checkout; revocation of old open FDs; original-workspace retirement; installed successor controller or service commissioning; proof across reboot; provider release.

The next substantive engineering milestone **must address this OS boundary and controller admission together**, with disposable-host validation and explicit operator approval before altering the original checkout. Do not implement `stygnox top` until its separate formal architecture gate is approved.
