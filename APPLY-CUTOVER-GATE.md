# Apply R3D.2 Host Cutover Gate overlay (source-only)

This overlay is anchored to clean Git HEAD `a04f001` and the already published
root-private execution-denied custody. It changes **no** active transaction
state. Do not run the privileged CLI from the user-owned checkout.

## Apply on Linux as `pfsykes`

Put `stygnox-r3d2-cutover-gate-a04f001.tar.gz` in your home directory.
Use the SHA-256 supplied separately with the artifact before extracting.

```bash
cd "$HOME/stygnox-r3d1-direct-interruption-fix" || exit 1

test "$(git rev-parse --short=7 HEAD)" = "a04f001" || exit 1
test -z "$(git status --porcelain)" || exit 1

tar -tzf "$HOME/stygnox-r3d2-cutover-gate-a04f001.tar.gz" || exit 1

for p in \
  src/stygnox/direct_interruption_cutover_gate.py \
  scripts/stygnox_recovery_cutover_gate.py \
  tests/test_stygnox_direct_interruption_cutover_gate.py \
  docs/recovery-r3d2-host-cutover-architecture-review.md \
  APPLY-CUTOVER-GATE.md \
  scripts/stygnox_recovery_successor_denied_probe.py \
  docs/recovery-r3d2-denied-successor.service.in
do
  test ! -e "$p" || { echo "STOP: $p already exists"; exit 1; }
done

tar -xzf "$HOME/stygnox-r3d2-cutover-gate-a04f001.tar.gz" -C . || exit 1

PYTHONPATH=src:tests python3 -m pytest -q -rs \
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

python3 -m compileall -q \
  src/stygnox/direct_interruption_cutover_gate.py \
  scripts/stygnox_recovery_cutover_gate.py \
  scripts/stygnox_recovery_successor_denied_probe.py || exit 1

git status --short
git diff --check
```

## Privileged root audit, later (requires separate deployment and review)

Once the entire overlay has been committed, an exact `git archive` built and
promoted into a new independent root-owned read-only deployment, the CLI may
be considered for a root read-only audit. Do **not** use `sudo` against this
working tree. An installed-audit invocation is intentionally `--audit-read-only`
and always exits 75, even on successful inspection.

Do not replace the existing `a04f001` protected source/archive: it is a
verified reference input. No new publication, service, credential change,
original-workspace retirement or provider execution is authorised here.

Root-only and disposable Linux hostile tests may skip as `pfsykes`.
Capture `-rs` reasons. Do not run broad privileged suites against the live
host simply to turn skips green.
