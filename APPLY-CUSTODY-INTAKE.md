# Apply: R3D.2 blocked custody intake

**Source basis:** `8030ff382aa9fec9401ecb31ef4bb469665c3cf3`

**Purpose:** integrate the verified 609-file offline reconstruction and eight recorded continuations into a *durable, root-private, deny-only evidence receipt*. This is **not** an executable handoff or provider release. The historical original remains untouched, and 02N/02O provider dispatch remains unconditionally blocked.

This overlay adds only four paths: a custody-intake Python module, a dedicated `-I`-compatible CLI, behavior tests, and a focused operator/architecture note. Existing Stygnox binaries, imports, provider adapters and controller logic are unchanged. The script requires operator-reviewed root-owned staging before any host use. **Do not run it with `sudo` out of your Git checkout or Downloads folder.**

## Safe source integration (no provider execution)

Run the following verification in a subshell (or as a separate script, so `exit` will not terminate your interactive shell). On the Stygnox development host, download this tarball and set its location. The path below is illustrative; change it to the actual saved file:

```bash
REPO="$HOME/stygnox-r3d1-direct-interruption-fix"
BUNDLE="$HOME/Downloads/stygnox-r3d2-custody-intake-overlay.tar.gz"
EXPECTED_HEAD="8030ff382aa9fec9401ecb31ef4bb469665c3cf3"

echo '=== VERIFY SOURCE ==='
if [ "$(git -C "$REPO" rev-parse HEAD)" != "$EXPECTED_HEAD" ]; then
  echo 'STOP: source commit differs; do not extract'
  exit 1
fi
if [ -n "$(git -C "$REPO" status --porcelain --untracked-files=all)" ]; then
  echo 'STOP: source is dirty; inspect first'
  exit 1
fi

echo '=== REVIEW ARCHIVE ==='
tar -tzf "$BUNDLE"
```

After visually reviewing the expected five entries, run `tar -xzf "$BUNDLE" -C "$REPO"` (the archive must not be extracted as root). Then run:

```bash
cd "$HOME/stygnox-r3d1-direct-interruption-fix" || exit 1
PYTHONPATH=src:tests python3 -m pytest -q tests/test_stygnox_direct_interruption_custody_intake.py
PYTHONPATH=src:tests python3 -m pytest -q tests/test_stygnox_recovery_release_provider_dispatch.py tests/test_stygnox_recovery_release_script_dispatch.py tests/test_stygnox_recovery_release_boot_interlock.py tests/test_stygnox_recovery_release_provider_preflight.py tests/test_stygnox_direct_interruption_transfer.py tests/test_stygnox_direct_interruption_publication.py
git diff --check
git status --short
```

Review the implementation and documentation under `docs/recovery-r3d2-custody-intake.md`. Do **not** deploy, seal or run on the protected host just because the source tests pass. Explicit host deployment approval and independent root-owned source verification are separate steps.

## Verification performed in the source archive sandbox

- Uploaded source archive SHA-256: `d1ca6ec0c87e7630791d50fda31f3ff5affe1bae14bf27d3a1abb40083032c49` verified.
- Focused custody tests: 14 passed on the development sandbox (one root fixture test may skip when run as nonroot).
- Broader high-value provider/recovery tests: 77 passed, 2 skipped, 24 subtests before the final added root fixture. Full legacy suite not qualified in the archive environment: initial run failed collection due to missing `tests` in `PYTHONPATH`; an attempt with corrected path exceeded the execution window; an isolated initial failure was due to a Git-test expectation absent from an extracted tar before a local fixture Git repository was created.
- Real protected host evidence has **not** been transferred to the development sandbox. All verification against that evidence remains to be performed by an operator-approved host-side audit.
