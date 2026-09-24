# D8.1 installed product identity and command resolution

## Stage outcome

D8.1 introduces the first versioned, installable Stygnox distribution and a
neutral installed `stygnox` console command. The installed command is a product
boundary: it is provided by the built wheel, resolves independently of an
adopting Git worktree, and does not import or delegate to `ralph`/`ralph_*`
controller modules or target-local/source-tree Ralph entrypoints.

The canonical product version is defined in `src/stygnox/_version.py` and is
used by both package metadata and the installed command.

## Deliberate boundary

D8.1 is not the installed-controller/adoption stage. The installed command
supports neutral `--help` and `--version` identity only and fails closed for
controller commands. Existing `scripts/stygnox_cli.py` and `scripts/ralph.py`
remain tracked development/compatibility surfaces for the current controller;
they are not packaged as the installed product path and are not valid evidence
for the D8.1 installed-command gate.

D8.2 owns bootstrap/admission and the tracked-policy/ignored-runtime boundary.
D8.3 owns clean/dirty transaction and recovery semantics. D8.4 owns migration,
upgrade, and uninstall. D8.5 owns controller/profile/runtime identity
neutralisation. Web/TUI operator UX and visual redesign remain later work and
are intentionally untouched here.

## Qualification

`python3 scripts/qualify_d8_1_installed.py` builds one immutable wheel with the
current interpreter, records its SHA-256 digest, installs that exact wheel into
a fresh virtual environment, and exercises installed help/version from new
(unborn), clean, and dirty Git fixtures.

Each fixture contains hostile legacy Ralph decoys and qualification supplies a
hostile source/decoy `PYTHONPATH`. Passing requires:

- the installed executable to resolve outside every fixture;
- exact neutral Stygnox version/help output;
- no import/execution of the decoy `scripts/ralph.py` or `ralph_profile.py`;
- no source-tree/Ralph normal-path fallback;
- no fixture mutation from help/version execution; and
- the installed package version to match the canonical version source.

This is D8.1 evidence only. It does not claim D8.2 adoption/bootstrap
qualification or D9 release readiness.
