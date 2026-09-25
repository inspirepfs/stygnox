# Stygnox

Stygnox is a standalone autonomous development-loop controller being hardened
for independent installation and adoption across Git projects.

## Current status

The repository has completed the extraction/standalone foundation through D8.0
and the D8.0.1 Python-bytecode containment closure. D8.1 introduced the first versioned installable Stygnox distribution and a
neutral installed `stygnox` command. D8.2 adds the installed read-only
bootstrap/admission preview, explicit confirmed handoff, reviewed tracked
policy/configuration, and ignored controller-owned runtime boundary. D8.3 adds
transaction authority binding, explicit safe stop, and operator-approved exact
baseline restoration for new/unborn, clean, and dirty projects. D8.4 adds
reversible extraction of supported idle legacy RALPH runtime into neutral
Stygnox retained evidence, explicit upgrade compatibility, and non-destructive
uninstall preparation. D8.5 adds the neutral installed profile, atomic
execution policy, reviewed provider/model/effort overrides, and an installed
controller activation/run path bound to D8.3 transaction authority. D8.6A adds
the installed branded Web/operator surface; D8.6B completes the operator UX
with the installed TUI, authoritative terminal identity, and cross-surface
semantic parity. D8.7 closes release packaging and documentation around one
build-once immutable wheel, a deterministic source-review archive, explicit
post-extraction quarantine reporting, and exact-artifact requalification of
the D8.1-D8.6B installed gates.

The D8.1 installed command is intentionally a narrow product-identity boundary:
it provides neutral `--help` and `--version` behaviour from an installed wheel
without importing or delegating to legacy `ralph`/`ralph_*` controller modules,
a target-project `scripts/ralph.py`, or a Stygnox source checkout.

D8.2 installs the bounded `stygnox adopt` / `stygnox bootstrap` admission
surface. D8.3 adds `stygnox transaction` / `stygnox recover` for exact handoff
binding, safe-stop authority revocation, stale recovery-preview refusal, and
baseline restoration. D8.4 adds `stygnox migrate`, `stygnox support`, `stygnox upgrade`, and
`stygnox uninstall`. D8.5 adds `stygnox profile`, `stygnox execution-policy`,
and the installed `stygnox controller` authority surface. Adoption handoff still
starts with controller execution disabled; a separate D8.5 activation gate binds
controller authority to an ACTIVE D8.3 transaction and the exact reviewed
execution policy. Current source-tree controller entrypoints remain
compatibility/development surfaces and are not installed fallbacks.

## Installable product development

Build a wheel from a clean checkout with the local build toolchain:

```bash
python3 -m pip wheel \
  --disable-pip-version-check \
  --no-deps \
  --no-build-isolation \
  --wheel-dir dist \
  .
```

Install the resulting wheel into an isolated environment and use the installed
command:

```bash
python3 -m venv /tmp/stygnox-venv
/tmp/stygnox-venv/bin/python -m pip install --no-deps dist/stygnox-*.whl
/tmp/stygnox-venv/bin/stygnox --version
/tmp/stygnox-venv/bin/stygnox --help
```

For the D8.1 artifact gate, run:

```bash
python3 scripts/qualify_d8_1_installed.py
```

The qualifier builds one wheel, records its SHA-256, installs that exact
artifact into a fresh virtual environment, and checks command resolution and
Ralph-decoy isolation from new, clean, and dirty Git fixtures.

See `docs/d8-1-installed-product.md` for the exact D8.1 boundary and evidence.

For the D8.2 bootstrap boundary, run:

```bash
python3 scripts/qualify_d8_2_bootstrap.py
```

See `docs/d8-2-bootstrap-boundary.md` for preview, confirmation, tracked policy,
ignored runtime, dirty external-evidence, and stage-boundary semantics.

For the D8.3 transaction/recovery gate, run:

```bash
python3 scripts/qualify_d8_3_transactions.py
```

See `docs/d8-3-transaction-recovery.md` for transaction binding, safe-stop,
dirty external-manifest requirements, exact restoration, and retained runtime
evidence semantics.

For the D8.4 migration/upgrade/uninstall gate, run:

```bash
python3 scripts/qualify_d8_4_lifecycle.py
```

Use `stygnox support` for the machine-readable supported platform/install-media
and project-state compatibility policy. See
`docs/d8-4-migration-upgrade-uninstall.md` for reversible legacy extraction,
upgrade refusal/acceptance, retained evidence, and uninstall ownership.

For the D8.5 neutral controller/execution-policy gate, run:

```bash
python3 scripts/qualify_d8_5_controller.py
```

Neutral defaults select no provider, model, or effort. Use
`stygnox execution-policy preview/set/reset` for reviewer-bound overrides and
`stygnox controller status/activate/run-preview/run` for installed controller
authority. See `docs/d8-5-neutral-controller.md` for the exact profile, policy,
activation, provider, and qualification boundary.


## D8.6A installed Web operator surface

The installed product now provides a neutral, branded local operator console:

```bash
stygnox web --project /path/to/project
```

D8.6A uses the approved `branding/` design tokens and selected logo assets,
projects only installed Stygnox state, and shares its action dispatcher with the
future TUI.  CLI/Web adoption preview digests are qualified for parity.  The
Web surface is deliberately loopback-only in D8.6A; non-loopback binding fails
closed before authority.  Carry-forward/reconciliation attribution is visible
as operator-baseline, Stygnox-native, runtime-only, external, or unresolved and
never auto-adopts or silently reattributes prior material.

Run:

```bash
python3 scripts/qualify_d8_6a_web.py
```

See `docs/d8-6a-web-operator-ux.md` for the exact boundary.

## D8.6B installed TUI and cross-surface parity

The installed product now provides the neutral terminal surface and canonical
presentation-neutral operator CLI:

```bash
stygnox operator snapshot --project /path/to/project
stygnox tui --project /path/to/project
```

At normal terminal widths the TUI uses the exact committed plain/ANSI Stygnox
ASCII identity. Narrow terminals use a compact identity; `NO_COLOR` disables
ANSI output. The TUI renders the same operator-baseline, Stygnox-native,
runtime-only, external and unresolved attribution model as Web and never
relies on colour alone for authority state.

Run:

```bash
python3 scripts/qualify_d8_6b_tui.py
```

The qualifier proves installed operator/Web/TUI snapshot parity, adoption
preview parity, exact branding assets, terminal fallback behaviour and refusal
of target-local legacy TUI fallbacks. See
`docs/d8-6b-tui-terminal-parity.md` for the exact boundary.

## D8.7 release packaging and exact-artifact qualification

D8.7 creates a bounded release set whose supported install medium is the wheel.
The release also carries a deterministic source-review archive, operator guide,
release-candidate closure map, post-extraction report, licence, manifest and
SHA-256 inventory.

Build a release set without qualifying it:

```bash
python3 scripts/build_d8_7_release.py --output-dir /tmp/stygnox-release
```

Run the release gate and retain its evidence:

```bash
python3 scripts/qualify_d8_7_release.py \
  --output-dir /tmp/stygnox-qualified-release
```

The D8.7 gate builds the release wheel once, records its SHA-256, and supplies
that exact immutable wheel to every established D8.1-D8.6B installed-artifact
qualifier through `STYGNOX_QUALIFICATION_WHEEL`. A second release set is built
only to prove reproducibility and is never substituted into predecessor
qualification. The normal standalone qualifier behaviour is unchanged when the
environment variable is unset.

See `docs/d8-7-operator-guide.md`, `docs/d8-7-release-candidate.md`, and
`docs/d8-7-post-extraction-report.md` for the release/operator boundary.

## Compatibility seams still intentionally retained

The following are not adopted as final Stygnox product identity and remain
later-stage obligations:

- persisted `zen_ralph_*` schemas;
- `.ralph` compatibility runtime/policy naming;
- source-tree `scripts/ralph.py` and legacy ZEN/RALPH compatibility surfaces;
- persisted legacy schemas retained only where compatibility/evidence requires them;
- source-tree `.ralph` and `scripts/ralph*.py` material is quarantined to migration, provenance, characterization, and source-review roles and is excluded from the installed wheel and normal operator path; and
- D8.6A/D8.6B Web/TUI surfaces are installed and neutral; Web remains loopback-only pending an explicit future remote-access security policy.

The staged roadmap and release acceptance baseline are documented in
`docs/d8-0-roadmap-and-release-acceptance.md`.
