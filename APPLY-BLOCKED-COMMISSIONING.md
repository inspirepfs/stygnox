# Apply blocked commissioning after commit `426572f`

This five-file overlay is **source integration only**. It must not be run as
root from the user-owned repository, deployed to the live R3D.2 transaction,
or used to launch Codex/Astra. It does not modify any existing source paths.

1. Verify repository HEAD equals the full commit ID produced by `git rev-parse
   426572f` and that `git status --porcelain --untracked-files=all` is clean.
   Also verify the downloaded overlay archive SHA-256 matches the separately
   supplied value.
2. List and review archive entries. They must be exactly the five filenames
   listed below, all regular files, no symlinks or links, and no existing target
   path. **Extract as the ordinary user**, not with `sudo`.
3. Run tests from the repository root:

   ```bash
   PYTHONPATH=src:tests python3 -m pytest -q \
     tests/test_stygnox_direct_interruption_blocked_commissioning.py \
     tests/test_stygnox_direct_interruption_custody_intake.py \
     tests/test_stygnox_recovery_release_provider_dispatch.py \
     tests/test_stygnox_recovery_release_script_dispatch.py \
     tests/test_stygnox_recovery_release_boot_interlock.py \
     tests/test_stygnox_recovery_release_provider_preflight.py \
     tests/test_stygnox_direct_interruption_transfer.py \
     tests/test_stygnox_direct_interruption_publication.py
   git diff --check
   git status --short --untracked-files=all
   ```

4. Review the source and documentation before a local commit. **Do not deploy
   or run the root-only `--seal-blocked` operation** until there is a separate
   reviewed, root-owned installation and host-specific cutover plan.

## Exact overlay paths

- `src/stygnox/direct_interruption_blocked_commissioning.py`
- `scripts/stygnox_recovery_blocked_commissioning.py`
- `tests/test_stygnox_direct_interruption_blocked_commissioning.py`
- `docs/recovery-r3d2-blocked-commissioning.md`
- `APPLY-BLOCKED-COMMISSIONING.md`

## Expected scope

The new test suite verifies disabled authority state, unchanged historical
continuations, tamper rejection, one-shot data publication, interrupted
publication refusal, file permissions and the existing ordinary-runtime
quarantine guard. Tests do not simulate or certify process exclusion, reboot
behaviour of a real host, or actual Codex credentials. Provider execution
remains unconditionally denied by the existing guard code.
