# D8.0 staged roadmap and release acceptance baseline

## Status and release-wide baseline

This is a forward roadmap, not implementation authorization. D8.1--D8.7 are
independently qualifiable future stages: passing an earlier stage neither
starts, approves, nor relaxes a later stage. **D8.1 is future work only**; this
document does not propose or approve it.

Retain the released artifact version and digest, fixture identity, transcripts,
reviewed tracked policy, human confirmation/handoff records, and recovery
results for each applicable gate. Source-tree execution, a target-project
`scripts/ralph.py`, source imports, and local Ralph compatibility fallbacks
are never installed-command evidence.

No candidate releases until applicable gates pass in isolated fresh
environments and isolated new/unborn, clean, and dirty Git fixtures. The dirty
fixture contains staged, unstaged, renamed, deleted, and untracked material.
Its operator-owned baseline is independently restored and compared for status,
content, paths, types, modes, digests, and required empty directories; a path
list is not recovery proof.

Installed commands must resolve the versioned `stygnox` executable outside
the adopted worktree, with no source-tree or Ralph fallback. Tracked
configuration/policy is reviewable project material. Ignored runtime is
controller-owned, agent-immutable, and excluded from native-delta
qualification; it cannot substitute for tracked policy. Preview, explicit
confirmation, authority handoff, abort, interruption, rollback, restoration,
and retained evidence are required lifecycle semantics.

## D8.1 — installed product identity and command resolution (future)

**Predecessors:** D8.0 baseline only. This stage is intentionally not proposed
or approved here.

**Bounded outcome:** A versioned installable Stygnox product has an installed,
neutral `stygnox` CLI. Normal resolution is independent of the adopting
project and legacy Ralph entrypoints; any alias is quarantined compatibility.

**Observable evidence:** Fresh-environment package metadata, artifact digest,
install transcript, executable path, version/help output, import/invocation
audit, and a negative decoy fixture with `scripts/ralph.py` and source path.

**Release gate:** Install the immutable artifact in a fresh environment and
invoke version/help from new, clean, and dirty fixtures. The executable is
outside each fixture; normal paths have no source-tree or Ralph fallback.

**No-go:** Missing versioned artifact; executable in the fixture; decoy,
source import, or Ralph fallback passes; or neutral identity merely wraps the
legacy normal path.

**Future characterization tests:** Command resolution, decoy rejection,
version/help identity, and temporary compatibility diagnostics.

## D8.2 — bootstrap and tracked-policy/ignored-runtime boundary

**Predecessors:** D8.1 installed-command gate.

**Bounded outcome:** Installed bootstrap/admission supplies no-change preview,
explicit confirmation, recorded handoff, reviewed tracked policy/configuration,
and ignored controller-owned, agent-immutable runtime.

**Observable evidence:** New, clean, and dirty fixture transcripts show
command resolution, preview, confirmation, handoff, runtime location, tracked
policy review, delta comparison, and a refused/prevented agent runtime write.

**Release gate:** Installed artifact completes admission and no-change abort
for every fixture before authority. Tracked policy appears for review; runtime
writes are ignored/excluded; changed policy or baseline invalidates confirmation.

**No-go:** Project mutation before handoff; implicit confirmation; tracked or
agent-writable runtime; policy hidden in runtime; or no renewed preview after a
policy/baseline change.

**Future characterization tests:** Preview-before-handoff, explicit
confirmation, tracked/runtime attribution, runtime write protection, and
confirmation invalidation.

## D8.3 — clean/dirty transactions and baseline recovery

**Predecessors:** D8.2 boundary gate.

**Bounded outcome:** Transactional authority, safe-boundary stop,
abort/interruption handling, and operator-approved recovery work for clean and
dirty projects. Dirty handoff requires an operator-owned, independently
verified restorable capture.

**Observable evidence:** Clean evidence includes HEAD/tree/status,
baseline-change rejection, interruption/abort, and recovery comparison. Dirty
evidence includes independent index/staged and worktree/unstaged snapshots;
rename/deletion metadata/content; complete untracked archive/manifest;
restoration rehearsal; and post-restore status/digest/mode/type comparison.

**Release gate:** Isolated clean and dirty fixtures prove handoff, abort,
pre-handoff interruption, post-handoff safe stop, and operator-approved
restoration. Dirty recovery reproduces every pre-authority category, including
untracked material, without controller ownership or attribution.

**No-go:** A path list substitutes for content; a dirty category is absent;
controller/agent is sole custodian; recovery silently discards work; changed
baseline lacks renewed confirmation; or restoration cannot be rehearsed.

**Future characterization tests:** Clean revalidation, transactional
interruption, safe stop, staged/unstaged separation, rename/delete recovery,
untracked manifests, and failed-recovery handoff refusal.

## D8.4 — migration, extraction, upgrade, and uninstall

**Predecessors:** D8.1 through D8.3 gates.

**Bounded outcome:** A reviewed, reversible extraction from ZEN/RALPH-bound
state to neutral Stygnox state, plus supported upgrade/uninstall. Upgrade
preserves compatible evidence or stops with an operator-directed migration;
uninstall stops activity without changing project content and states evidence
ownership.

**Observable evidence:** Isolated legacy-state fixtures; before/after runtime
and artifact inventories; import/path audits; rollback, upgrade, and uninstall
transcripts; supported platform/install-media record; compatibility policy; and
retained-evidence inventory.

**Release gate:** Fresh, clean, and dirty fixtures complete the supported
migration/upgrade/uninstall path or receive a clear pre-change refusal. Results
have neutral runtime ownership, readable retained evidence, no source-tree
dependency, and a verified rollback route.

**No-go:** Legacy identity remains authoritative; migration loses, rewrites, or
misattributes evidence; compatibility/platform support is unspecified;
uninstall changes project content/leaves activity; or rollback is unrehearsed.

**Future characterization tests:** Legacy-state recognition, unsupported-state
refusal, reversible schema migration, upgrade compatibility, uninstall
idempotence, retained-evidence report, and rollback.

## D8.5 — neutral authority, profile, controller, and model-effort compatibility

**Predecessors:** D8.1, D8.2, and D8.4 gates.

**Bounded outcome:** Installed defaults are product-neutral for identity,
profile, controller command, runtime schema, artifacts, and presentation. A
host adapter is optional, never default. Model, provider, and effort are
neutral unless a reviewer approves a tracked override before handoff.

**Observable evidence:** Installed-artifact scans/import graphs,
profile/configuration transcripts, fixture outputs, and reviewed override
records show neutral identity and explicit reviewed overrides in preview.

**Release gate:** Across fresh, clean, and dirty fixtures, installed commands
emit selected Stygnox identity and invoke installed controllers. Neutral config
implies no model/provider/effort; an override is refused until reviewed and
reconfirmed.

**No-go:** ZEN/RALPH profile, `.ralph` runtime, `python3 scripts/ralph.py`,
or host artifact is default; adapter leaks identity; unreviewed model/effort
selection occurs; or override does not invalidate confirmation.

**Future characterization tests:** Neutral defaults, adapter isolation,
configuration precedence, controller rendering, artifact naming, and
model/effort override preview/approval.

## D8.6 — external Web/TUI, carry-forward/adoption, and operator UX

**Predecessors:** D8.2, D8.3, and D8.5 gates.

**Bounded outcome:** Neutral installed CLI, Web, and TUI have equivalent
admission, confirmation, handoff, abort, recovery, and evidence semantics.
Carry-forward/adoption and reconciliation visibly separate controller-native
work, operator baseline, runtime, external changes, and human decisions.

**Observable evidence:** Cross-surface transcripts or accessibility-visible
records for new, clean, and dirty fixtures; parity comparisons; unsupported
refusals; and reconciliation examples for native, foreign, runtime-only, and
unresolved changes. Web/TUI resolve from installed artifact without local Ralph.

**Release gate:** Each surface completes the same qualified journey or clearly
fails before authority. Carry-forward/reconciliation preserve operator baseline,
make attribution visible, and stop for named human decisions.

**No-go:** Web/TUI normally delegates to target-local/legacy controller;
surfaces differ on authority/recovery; carry-forward reattributes prior
material; runtime appears native; or unresolved decisions auto-proceed.

**Future characterization tests:** Cross-surface parity, accessible human-gate
wording, unsupported-route refusal, carry-forward classification,
reconciliation attribution, and interruption/recovery.

## D8.7 — release packaging, documentation, and fixture qualification

**Predecessors:** D8.1 through D8.6 gates.

**Bounded outcome:** Ship package and operator documentation for installation,
resolution, every journey, migration, recovery, upgrade/uninstall,
model/profile choices, Web/TUI policy, evidence retention, and support
boundaries. Qualify the exact artifact, not source alone.

**Observable evidence:** Artifact version/digest and contents; fresh install
records; documentation review against that version; installed command/import
scans; complete new/clean/dirty fixture logs including dirty restoration; and
negative fallback fixtures.

**Release gate:** Build once, install immutable artifact into isolated fresh
environments, and run applicable D8.1--D8.6 gates on fresh, clean, and dirty
fixtures. Independent review follows shipped docs and reproduces command
boundary, human gates, recovery, upgrade/uninstall, and surface-policy results.

**No-go:** Source-tree qualification substitutes for artifact qualification;
docs mismatch artifact; an installed command has source/target/Ralph fallback;
dirty recovery including untracked material is unproven; evidence is absent; or
any predecessor gate is incomplete.

**Future characterization tests:** Release packaging, command-boundary
negatives, documentation examples, all fixture journeys, dirty restoration
integrity, and supported upgrade/uninstall/surface combinations.

## Acceptance decision

D8.0 accepts only this staged baseline. A future stage may be considered for
approval only with predecessor evidence, a bounded plan, and the stated gate
and no-go criteria intact. No nested propose, approve, run, requalify,
finalize, commit, or push action follows from this document.
