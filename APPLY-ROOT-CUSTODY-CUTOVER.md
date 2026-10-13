# Source overlay application — integrated blocked R3D.2 root custody

Apply onto the clean post-blocked-commissioning source checkout. This is
**source integration only**; the root operation is NOT authorised here.

**New files:**

- `src/stygnox/direct_interruption_custody_cutover.py`
- `scripts/stygnox_recovery_root_custody.py`
- `tests/test_stygnox_direct_interruption_custody_cutover.py`
- `docs/recovery-r3d2-root-custody-cutover.md`
- `APPLY-ROOT-CUSTODY-CUTOVER.md`

Run test suite with:

```bash
cd "$HOME/stygnox-r3d1-direct-interruption-fix" || return 1
PYTHONPATH=src:tests python3 -m pytest -q \
  tests/test_stygnox_direct_interruption_custody_cutover.py \
  tests/test_stygnox_direct_interruption_blocked_commissioning.py \
  tests/test_stygnox_direct_interruption_custody_intake.py \
  tests/test_stygnox_recovery_release_provider_dispatch.py \
  tests/test_stygnox_recovery_release_script_dispatch.py \
  tests/test_stygnox_recovery_release_boot_interlock.py \
  tests/test_stygnox_recovery_release_provider_preflight.py \
  tests/test_stygnox_direct_interruption_transfer.py \
  tests/test_stygnox_direct_interruption_publication.py
```

Do not call the privileged CLI from the Git checkout. It is not a live
transaction cutover, and a passing test is not release authority.
