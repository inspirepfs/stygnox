# R3D.2 — Narrow 02N catalogue and read-only planning release

## Operator approval and scope

The operator has approved a bounded break-glass release, not blanket provider access. This source patch applies to a **new candidate worktree** from the clean `8d37a5c` baseline, not to the current active-transaction checkout. The original interrupted `TX-a6379f065ce68138` remains denied and is not eligible. The recent `TX-3e0019c7adea1266` has a different, fixed installed/source identity and **cannot consume this new source or wheel without a separately reviewed native rebind or fresh bootstrap**. Never mutate its installed venv or `.stygnox` authority in place.

## Included source changes

- `src/stygnox/provider_release.py`: native `stygnox provider-release preview/catalogue/release/status`, exact transaction, operator, handoff SHA, Git baseline, installed command, installed module bytes, reviewed policy and source checks. Reviewable digest required for both catalogue probe and release; no environment override. Catalogue probe does not persist a grant.
- `src/stygnox/provider_codex.py`: existing three subprocess launch sites remain 02N deny-by-default. An exact new-worktree runtime record admits model catalogue, quota and sandbox preflight only, and read-only Codex exec **only from a confirmed `planning.propose_plan` invocation**. Direct provider exec, write turns, reset credit consumption, legacy-script 02O launches, unknown launch modes, and original worktree remain denied.
- `src/stygnox/planning.py`: short-lived per-call read-only proposal context, scoped after exact confirmed proposal preview.
- `src/stygnox/execution_policy.py`: runtime catalogue binding can satisfy the model metadata condition without rewriting tracked post-transaction policy.
- `src/stygnox/controller.py`: planning-only release never advertises `provider_execution_ready`; direct controller turns are rejected. Plan proposals remain enabled with an activated controller.
- `src/stygnox/cli.py`: new installed CLI command route.
- `tests/test_stygnox_provider_planning_release.py`: behavioural and negative authority tests.

## Installation path

1. Create a **new** clean worktree from `8d37a5c` (separate from active transaction); verify exact base and archive SHA.
2. Apply `patches/provider-planning-release.patch` with `git apply --check && git apply`. Copy the new module and test; inspect exact diff. Run the regression suite, compile and check the patch. Commit only after review.
3. Build a **new** canonical installed wheel from the committed candidate. Do not upgrade the old `venv-8d37a5c` in place.
4. Before touching existing `TX-3e0019c7adea1266`, perform an installed-product upgrade/rebind **preview** and review its blockers. The native rebind may reject an ACTIVE transaction and/or insufficient host exclusive-custody evidence. Do not force an in-place rebind or assign it an invented approval.
5. If rebind is unavailable, do a single **new clean bootstrap/transaction** from the fixed release worktree, with exact existing-policy offline adoption. This is a new authority identity; the original and prior forward transaction histories remain preserved. Test that `provider-release preview` is admissible before performing any provider launch.
6. `stygnox provider-release preview --project PATH --operator pfsykes` returns a digest with no write. The next command `stygnox provider-release catalogue --project PATH --operator pfsykes --preview SHA --confirm PROBE` executes only the Codex metadata query and does not create a release. If the reviewed `gpt-5.6-terra` model/`high` effort is missing, **STOP**: policy must be reviewed and a clean authority process repeated; do not forge model metadata.
7. Only after a successful catalogue probe, run `stygnox provider-release release --project PATH --operator pfsykes --preview SHA --confirm RELEASE_PLANNING`; this rechecks the live catalogue and persists a root/worktree/transaction/executable/policy-bound planning-only release record. Then inspect `provider-release status`; activate controller through native approved gates, generate an R3D.2 proposal preview and explicitly confirm that preview.

## What remains blocked

This is **planning release only**. There is **no controller write release**, no approval for `stygnox top`, and no assertion that hostile same-UID host execution is globally fenced. `stygnox controller run` is explicitly blocked for this release even with a plan. A subsequent plan-approved execution release requires its own bounded qualification (including host exclusivity/disposable tests). The old 02N state without an exact release record remains untouched. Source-based tests do not establish host-side exclusive custody or installed-product runtime authority.

## Source qualification evidence

Reconstructed from the supplied source and previously accepted overlays. Offline tests run with inert catalogue fixtures and no live Codex calls; the user's host reapplication and installed wheel preflight are authoritative. No privileged root tests performed. The user should not interpret this source package as authorisation to mutate `/var/lib/stygnox` or restart historical processes.
