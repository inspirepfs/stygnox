# Stygnox

Stygnox is a standalone autonomous development-loop controller being hardened
for independent installation and adoption across Git projects.

## Current status

The repository has completed the extraction/standalone foundation through D8.0
and the D8.0.1 Python-bytecode containment closure. D8.1 introduces the first
versioned installable Stygnox distribution and a neutral installed `stygnox`
command.

The D8.1 installed command is intentionally a narrow product-identity boundary:
it provides neutral `--help` and `--version` behaviour from an installed wheel
without importing or delegating to legacy `ralph`/`ralph_*` controller modules,
a target-project `scripts/ralph.py`, or a Stygnox source checkout.

Controller/adoption commands are **not** claimed as installed-product capability
at D8.1. The current source-tree controller entrypoints remain tracked
compatibility/development surfaces until the later staged controller,
admission, runtime, and migration closures qualify their replacements.

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

## Compatibility seams still intentionally retained

The following are not adopted as final Stygnox product identity and remain
later-stage obligations:

- persisted `zen_ralph_*` schemas;
- `.ralph` compatibility runtime/policy naming;
- the active ZEN host profile and `chore(zen):` commit identity;
- source-tree `scripts/ralph.py` controller compatibility;
- external Web/TUI parity and presentation; and
- migration, upgrade, uninstall, and release-wide installed-artifact gates.

The staged roadmap and release acceptance baseline are documented in
`docs/d8-0-roadmap-and-release-acceptance.md`.
