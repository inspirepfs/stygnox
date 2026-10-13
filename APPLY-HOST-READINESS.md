# Apply R3D.2 read-only custody readiness overlay (source only)

**Status: BLOCKED / NO CUTOVER.** This overlay contains a trusted-data
inspection gate and design/acceptance document. It **does not** implement the
host-wide kernel-enforced predecessor exclusion or commission an executable
successor. It may not be used to release the provider, restart a plan, or modify
the live workspace.

Base commit **exactly** `527dd68e0976e8f3831a7a4168d16a07d48e03fe`
(branch `fix/r3d1-reviewed-direct-interruption`). Apply only to the clean
source checkout, **never** the deployed protected successor or original
R3D.2 workspace.

## Integration

Place the attached overlay archive in `$HOME`, then from the host:

```bash
(
cd "$HOME/stygnox-r3d1-direct-interruption-fix" || exit 1

printf 'Commit: '; git rev-parse HEAD
printf 'Worktree state:\n'; git status --short

# STOP unless HEAD is exactly 527dd68e0976e8f3831a7a4168d16a07d48e03fe
# and the tree is clean. The three recovery source files must not be replaced.

ARCHIVE="$HOME/stygnox-r3d2-host-readiness-527dd68.tar.gz"
sha256sum "$ARCHIVE"
tar -tzf "$ARCHIVE"

# Verify SHA-256 against the accompanying transfer manifest before extraction.
tar -xzf "$ARCHIVE" -C . || exit 1

PYTHONPATH=src:tests python3 -m pytest -q \
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
  src/stygnox/direct_interruption_host_readiness.py \
  scripts/stygnox_recovery_host_readiness.py

git diff --check
)
```

Review tests and changes in the worktree. Source integration and commit are
separate from any privileged host cutover. Run `git status` and review new
files before staging. Do not push to a guessed upstream (none was configured
at the handover). Do not run `sudo python3` against the mutable source checkout.

## Host inspection

Read `docs/recovery-r3d2-exclusive-custody-gate.md`. It includes non-mutating
operator host commands. The new executable refuses a root invocation from a
mutable checkout before importing repository modules. If eventually deployed
as a qualified root-owned source artifact, its only live operation is
`--audit-existing-root-custody`, which **always** exits `75`. Its successful
read-only inspection phase is `EXCLUSIVE_CUSTODY_NOT_PROVED`.

The **next** source implementation must be one integrated, host-enforced
exclusion + immutable successor commission milestone. No `stygnox top` work
is permitted before the explicit architecture review and operator approval.
