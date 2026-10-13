# R3D.2 — Apply isolated successor workspace source overlay

**Operator checkpoint:** 13 October 2026; committed baseline `527dd68e0976e8f3831a7a4168d16a07d48e03fe`.

**Scope:** an integrated data-only successor-worktree staging mechanism. This is NOT host-exclusion closure, successor executable commissioning, a controller-admission receipt, permission to resume Step 2, or permission to execute Codex.

## Safety contract

- No code or file access in `/home/pfsykes/stygnox-r3d2-astra`.
- No recreation of already published `/var/lib/stygnox/recovery-r3d2-root-custody-blocked-v1`.
- Creates a **new** slot only after separate approved root deployment and operator decision: `/var/lib/stygnox/recovery-r3d2-isolated-workspace-denied-v1`.
- Source reconstructed from the original protected manifest is **data**, not installed executable code.
- New replica is root-only; contents are copied into distinct regular-file inodes. Approved plan/controller/transaction records are replaced with the already verified quarantined projection, and the quarantine marker is installed. Historic Step 1 and all 8 continuation evidence remains preserved without replay.
- Every exit from the CLI is `75`; a successful data-only stage is indicated exclusively by the phase `ISOLATED_WORKSPACE_STAGED_EXECUTION_DENIED`.
- The old UID may still execute its old binary against the original user-owned tree and may still have valid Codex OAuth. **Legacy exclusion is NOT claimed**.
- Failures after `.pending` is created require manual reconciliation, not deletion or automatic retry.

## Step A — apply and test in the unprivileged development checkout

Archive name: `stygnox-r3d2-isolated-workspace-527dd68.tar.gz` (verify its published SHA-256).

The archive contains four new source files. No existing source files are overwritten.

```bash
(
  cd "$HOME/stygnox-r3d1-direct-interruption-fix" || exit 1
  test "$(git rev-parse HEAD)" = '527dd68e0976e8f3831a7a4168d16a07d48e03fe' || { echo 'STOP: wrong Git HEAD'; exit 1; }
  test -z "$(git status --porcelain --untracked-files=no)" || { echo 'STOP: tracked working tree modified'; exit 1; }
  for f in APPLY-HOST-READINESS.md docs/recovery-r3d2-exclusive-custody-gate.md scripts/stygnox_recovery_host_readiness.py src/stygnox/direct_interruption_host_readiness.py tests/test_stygnox_direct_interruption_host_readiness.py; do
    test -f "$f" || { echo "STOP: prior readiness overlay missing: $f"; exit 1; }
  done
  ARCHIVE="$HOME/stygnox-r3d2-isolated-workspace-527dd68.tar.gz"
  test -f "$ARCHIVE" || { echo "STOP: missing $ARCHIVE"; exit 1; }
  sha256sum "$ARCHIVE"
  tar -tzf "$ARCHIVE" || exit 1
  for f in APPLY-ISOLATED-WORKSPACE.md scripts/stygnox_recovery_isolated_workspace.py src/stygnox/direct_interruption_isolated_workspace.py tests/test_stygnox_direct_interruption_isolated_workspace.py; do
    test ! -e "$f" || { echo "STOP: target exists $f"; exit 1; }
  done
  tar -xzf "$ARCHIVE" -C . || exit 1
  git status --short
)
```

Source-only qualification (does not need sudo):

```bash
(
  cd "$HOME/stygnox-r3d1-direct-interruption-fix" || exit 1
  PYTHONPATH=src:tests python3 -m pytest -q \
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
  python3 -m compileall -q \
    src/stygnox/direct_interruption_isolated_workspace.py \
    scripts/stygnox_recovery_isolated_workspace.py || exit 1
  git diff --check || exit 1
  echo 'SOURCE-ONLY GATES PASS'
)
```

If the root-specific UID test skips on your unprivileged run, it is **not** evidence of an actual UID boundary pass. It must run independently during protected host qualification.

## Step B — HOST CUTOVER IS NOT AUTHORISED BY THIS PATCH

Do **not** invoke the privileged `--prepare-data-only` option from the mutable Git checkout. The script has an early root-source-protection guard, but that guard is not a substitute for a reviewed, content-pinned root deployment.

A future explicit operator review must approve:

1. A verified new source commit and committed provenance of these changes.
2. Repeatable, exact artifact digest and root-owned read-only installation of the **new** source (not the old `527dd68` installation).
3. Fresh read-only validation of root custody, candidate manifest, old workspace inode identity and host holder snapshot.
4. A reviewed command, executed only from the new protected installation, that performs a **single** `--prepare-data-only` publication into the new isolated slot. Verify output phase and actual files; do not retry if `.pending` exists.
5. Hostile tests with an actual UID 1000 process, copied legacy binary, open historic FD, aliases, mount namespace, reboot and crash states.
6. Only after independent predecessor exclusion is demonstrated: separate service commissioning with exact package/executable identity, dedicated UID, epoch and transaction admission; then a separately approved human release gate for one continuation.

**Nothing in this overlay starts providers, installs a systemd service, revokes other Codex activity, retires the original checkout, authorises an epoch, or bypasses R3D.2 Step 2.**

## Host-side source review observations

Ubuntu kernel 6.8, ext4, AppArmor active, systemd 255. Two UID-1000 `codex` processes were observed but no Stygnox/Ralph process or FD into the original workspace was reported. These are observations, not forward-looking exclusion guarantees. Avoid killing unrelated processes or revoking shared OAuth.

This staging milestone produces a **separate inode and DAC boundary** for a future successor; it does not produce **exclusive transaction authority** while the independently runnable legacy remains able to act on the original workspace. This distinction must remain explicit in all commit messages, tests and programme records.

## Deferred programme gates

R3D.1 upgrade/rebind and R3D.2 full runtime seam remain unqualified. R3D.3 then requires full concurrency/recovery. A **formal written architecture review plus explicit operator approval** is mandatory before starting `stygnox top`. No Web UI restoration or operator feature work belongs in this patch.
