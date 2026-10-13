# Apply R3D.2 integrated denied-authority cutover source

**Target:** `fix/r3d1-reviewed-direct-interruption` at HEAD `2769e6e` only.
**Pre-existing untracked document:** `docs/recovery-r3d2-exclusive-custody-decision.md` is expected from the prior operator step, and must be preserved, not replaced.

**This overlay is source/test/documentation only.** Neither applying it nor running these tests commissions production systemd services, retires `/home/pfsykes/stygnox-r3d2-astra`, mutates `/var/lib/stygnox`, reads Codex credentials, replays eight continuations or releases providers.

## Operator apply and source tests

From the development checkout, check HEAD and verify there are no modified or staged tracked files. Confirm the downloaded tar SHA-256 against the value supplied alongside the download. List members and verify the archive has exactly the expected 13 files, and that none escapes the repository. Archive extraction overwrites four committed source/governance members intentionally; do not apply if your tracked working tree is dirty or the Git HEAD differs.

```bash
cd "$HOME/stygnox-r3d1-direct-interruption-fix" || exit 1

PYTHONPATH=src:tests python3 -m pytest -q -rs \
  tests/test_stygnox_direct_interruption_authority_cutover.py \
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
  src/stygnox/direct_interruption_authority_cutover.py \
  src/stygnox/direct_interruption_successor_broker.py \
  scripts/stygnox_recovery_integrated_cutover.py \
  scripts/stygnox_recovery_denied_broker.py \
  scripts/stygnox_recovery_denied_worker.py

git diff --check
git status --short
```

No `sudo` commands are authorised here. Do **not** set `STYGNOX_DISPOSABLE_LINUX_ROOT_TESTS` on the live host: the real UID isolation and Linux systemd tests belong to a disposable VM.

## Cutover authority and approval still withheld

The new protocol exposes a privileged *preview* and explicitly approved root phase writers, but these are **not** commands to run on the production host yet. They must first be promoted from the exact new committed artifact into a root-controlled installation, with root-only evidence and a verified worker service/cgroup. Operator approval is required for each host-mutating phase. The root-only `/var/lib/stygnox` reservation slot may not yet exist, and the existing root custody/staged slots must never be re-published.

New phases are `PREPARED_EXECUTION_DENIED`, `LEGACY_UNTRUSTED_EXECUTION_DENIED`, and `SUCCESSOR_ATTESTED_EXECUTION_DENIED`. These do not grant execution authority. Root broker startup requires the new trust boundary and separately verified installed bytes; the worker has no provider actions or credentials. A crash, reboot or competing claimant must remain denied.

**Gap still requiring disposition:** UID 1000 remains capable of launching old/copied code and modifying historical files. New broker will not admit those records or PIDs, but no Linux policy here globally bans legacy process execution or revokes a pre-opened old FD. Complete disposable-host hostile verification and the R3D.1/R3D.2 installed controller binding are mandatory before any continuation approval.

No `stygnox top` development before the formal architecture review and explicit approval.
