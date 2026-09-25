# D8.7 operator guide — installed Stygnox release candidate

## Purpose

D8.7 is the release-packaging and installed-artifact closure for the standalone
Stygnox product. The supported install medium is a Python wheel. The release
set also contains deterministic source-review material, this operator guide,
the release-candidate closure map, the post-extraction report, the AGPLv3
license, a release manifest, and SHA-256 checksums.

D8.7 does not weaken any D8.1–D8.6 authority rule. A source checkout is not a
substitute for the installed command boundary.

## Supported environment

`stygnox support` is authoritative. At D8.7 the bounded support policy is:

- Linux;
- Python `>=3.11,<3.14`;
- Git available on `PATH`;
- installation from the release wheel with `pip` into an isolated or
  user-managed Python environment; and
- no supported system-package-manager install path.

The Web surface defaults to loopback. Explicit non-loopback binding is supported
when a Stygnox Web username/password has been configured for the project. Plain
HTTP is intended only for trusted lab/LAN use; TLS can be added separately when
transport confidentiality is required.

## Release-set verification and installation

Verify the release directory before installation:

```bash
sha256sum -c SHA256SUMS
```

Install the exact wheel named by `release-manifest.json`:

```bash
python3 -m venv /opt/stygnox/venv
/opt/stygnox/venv/bin/python -m pip install --no-deps ./stygnox-<version>-py3-none-any.whl
/opt/stygnox/venv/bin/stygnox --version
/opt/stygnox/venv/bin/stygnox --help
```

For adoption, `command -v stygnox` must resolve to the installed environment,
not inside the project being adopted. Target-local `scripts/ralph.py`,
`ralph_*` modules, Stygnox source checkouts, and other compatibility scripts are
not valid installed-command substitutes.

## Adoption journeys

All adoption journeys begin with a read-only preview bound to a named operator:

```bash
stygnox adopt preview --project /path/to/project --operator "Operator Name"
```

The preview digest authorizes only the exact reviewed baseline, tracked
`stygnox.toml` / `stygnox.policy.md` material, installed-command identity, and
reviewed execution-policy selection. Any relevant change requires a fresh
preview.

### New / unborn repository

After reviewing an admissible preview:

```bash
stygnox adopt handoff \
  --project /path/to/project \
  --operator "Operator Name" \
  --preview <sha256> \
  --confirm HANDOFF
```

A controller-owned pre-authority recovery checkpoint is created under the
ignored `.stygnox/` runtime only after explicit handoff.

### Existing clean repository

The clean journey uses the same preview/handoff flow. The current Git baseline
is revalidated before authority. If it changes, the old preview is stale and
handoff refuses.

### Existing dirty repository

Dirty adoption is deliberately stricter. Stygnox does not become sole
custodian of pre-authority dirty material. The operator must first create and
rehearse an independently restorable external recovery package covering staged,
unstaged, renamed, deleted, untracked material, modes, content and empty
directories. The resulting attestation is supplied to preview and handoff:

```bash
stygnox adopt preview \
  --project /path/to/project \
  --operator "Operator Name" \
  --dirty-recovery-evidence /external/path/attestation.json
```

If the external capture, manifest, attestation, or baseline changes, authority
is refused.

## Transaction authority, safe stop, and exact recovery

After handoff, transaction authority remains separate from controller
activation:

```bash
stygnox transaction begin \
  --project /path/to/project \
  --operator "Operator Name" \
  --confirm BEGIN
```

At a safe boundary revoke authority explicitly:

```bash
stygnox transaction stop \
  --project /path/to/project \
  --operator "Operator Name" \
  --reason operator-abort \
  --confirm STOP
```

Exact baseline restoration is two-step and digest-bound:

```bash
stygnox transaction recover-preview \
  --project /path/to/project \
  --operator "Operator Name" \
  --post-handoff-disposition discard

stygnox transaction restore \
  --project /path/to/project \
  --operator "Operator Name" \
  --preview <sha256> \
  --confirm RESTORE \
  --post-handoff-disposition discard
```

A stale preview refuses. Dirty restoration consumes the operator-owned external
package; clean/new restoration consumes the bound internal checkpoint.
Controller evidence remains retained under ignored `.stygnox/` runtime.

## Profile, execution policy, and controller

The installed default profile is neutral:

```bash
stygnox profile show
stygnox execution-policy show --project /path/to/project
stygnox controller status --project /path/to/project
```

Provider/model/effort overrides require an explicit reviewed policy preview and
confirmation. Neutral defaults select no provider/model/effort and refuse
provider execution. Controller activation is a separate explicit gate bound to
an ACTIVE transaction and the reviewed policy.

The built-in installed provider adapter is `codex`. D8.7 does not grant
unreviewed provider selection or more than the currently qualified one-loop
execution contract.

## Web, TUI, and operator surfaces

The installed presentation-neutral operator model is available through:

```bash
stygnox operator snapshot --project /path/to/project
stygnox tui --project /path/to/project
stygnox web --project /path/to/project --host 127.0.0.1 --port 8765

# Optional direct LAN/mobile access
stygnox web-auth set --username operator --project /path/to/project
stygnox web --project /path/to/project --host 0.0.0.0 --port 8765
```

CLI/Web/TUI share installed Stygnox semantics. Reconciliation presentation
separates operator baseline, Stygnox-native, runtime-only, external/foreign,
and unresolved overlap. External/unresolved material requires a human decision;
it is not automatically adopted or reattributed.

Web mutations require the exact CSRF token. Non-loopback binding additionally requires configured Web authentication.
The TUI uses the committed Stygnox plain/ANSI identity, switches to a compact
identity on narrow terminals, and honours `NO_COLOR`.

## Migration from supported legacy RALPH state

Legacy `.ralph` and `zen_ralph_*` references are supported only by the bounded
migration compatibility path. They do not define installed Stygnox identity.
Use the preview/apply/rollback workflow documented in
`docs/d8-4-migration-upgrade-uninstall.md`. Unknown legacy state or unsupported
schemas refuse before destructive mutation. Migrated evidence is retained
under neutral `.stygnox/` custody and rollback remains qualified.

## Upgrade and uninstall

Before package upgrade:

```bash
stygnox support
stygnox upgrade preview --project /path/to/project --operator "Operator Name"
```

An ACTIVE transaction, unresolved migration state, unknown authority schema, or
unsupported runtime version blocks upgrade. Accepted package-only upgrade does
not rewrite tracked project content or retained evidence.

Before removing the package:

```bash
stygnox uninstall preview --project /path/to/project --operator "Operator Name"
stygnox uninstall prepare \
  --project /path/to/project \
  --operator "Operator Name" \
  --preview <sha256> \
  --confirm UNINSTALL
```

Preparation disables project activity and is idempotent. Package removal is a
separate `pip uninstall stygnox` operation. Project content and retained
`.stygnox/` evidence are not deleted by uninstall preparation or pip removal.

## Evidence retention and ownership

Tracked project configuration/policy remains reviewable Git material.
Controller runtime/evidence remains under ignored `.stygnox/`. Pre-adoption
dirty material remains operator-owned unless a later explicit authority rule
says otherwise. Runtime evidence never substitutes for tracked policy and never
becomes native product delta merely because it exists.

Legacy source/controller files retained in the Stygnox development repository
are source-only compatibility/evidence surfaces. The release wheel contains no
legacy Ralph module or target-local controller fallback.

## Release qualification

Build the deterministic release set:

```bash
python3 scripts/build_d8_7_release.py --output-dir /tmp/stygnox-release
```

Run the exact-artifact release gate:

```bash
python3 scripts/qualify_d8_7_release.py --output-dir /tmp/stygnox-qualified-release
```

The D8.7 qualifier builds one release wheel once, records its digest, and forces
D8.1 through D8.6B to qualify that same immutable wheel via
`STYGNOX_QUALIFICATION_WHEEL`. It also checks deterministic rebuilds, release
contents, documentation presence, installed import isolation, and post-
extraction legacy quarantine.

See the detailed stage documents under `docs/` for the normative boundaries of
each predecessor gate.
