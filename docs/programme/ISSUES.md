# Stygnox Programme Issues and Findings

**Status:** AUTHORITATIVE FINDINGS REGISTER  
**Last reconciled:** 2026-10-08 (TOP-00 requirement registration)

---

# Status Definitions

- **OPEN** — requires action in current or explicitly named stage.
- **RESOLVED** — corrective work completed and evidenced.
- **DEFERRED** — valid work intentionally assigned to a later stage.
- **WATCH** — no immediate correction required, but stage closure must re-evaluate it.
- **SUPERSEDED** — replaced by a newer finding/decision.

No material finding may disappear merely because implementation moved forward.

---

## STYX-001 — Approval Snapshot Rejects Historical `.ralph/policy.md`

**Status:** RESOLVED  
**Stage:** Pre-R3D bootstrap repair  
**Severity:** BLOCKING

### Finding

Native plan approval attempted to build a plan-owned rollback archive from the complete repository manifest.

The repository legitimately tracks:

```text
.ralph/policy.md
```

as historical evidence.

Retirement correctly refuses protected/runtime paths, resulting in an approval deadlock.

### Decision

The complete repository manifest remains fingerprint-bound.

Protected runtime/history paths:

```text
.git/
.stygnox/
.ralph/
```

must not become plan-owned rollback archive entries.

### Resolution

Implemented in:

```text
6427efa554d8350aae72b72b85512f5a7d9ba346
```

Regression coverage added.

Focused planning/retirement tests:

```text
18/18 PASS
```

### Disposition

CLOSED.

---

## STYX-002 — Native Human Operator Experience Regression

**Status:** OPEN  
**Target:** R3D.4  
**Severity:** HIGH

### Finding

R3C source convergence retained native authority but lost substantial proven operator ergonomics.

Current native planning/controller/scheduler surfaces often emit large JSON structures and long-running provider operations may provide no useful live feedback.

The native TUI remains visually strong but is currently principally a snapshot view.

### Required Resolution

Native Stygnox must restore:

- concise human defaults;
- explicit JSON modes;
- live planning heartbeat;
- live execution events;
- step/progress display;
- provider/model/effort visibility;
- usage/quota;
- RUN/CREATE/EDIT/DELETE/TEST;
- PASS/FAIL;
- summaries;
- recovery/gate/qualification banners;
- concise approve/run workflows.

CLI and TUI must consume canonical native state/events.

No Ralph execution code may be restored to solve the presentation problem.

---

## STYX-003 — Proposal Rejection Context Is Not First-Class Steering

**Status:** DEFERRED  
**Target:** Proposal Steering capability  
**Severity:** MEDIUM / COST

### Finding

Rejected proposal corrections currently require substantial manual prompt reconstruction.

This causes:

- repeated model reasoning;
- repeated rejected ideas;
- unnecessary context use;
- significant token cost;
- operator effort.

### Required Resolution

Create first-class rejection-linked proposal steering.

Replacement proposals should consume durable:

- rejection ID;
- rationale;
- accepted aspects;
- rejected aspects;
- correction requirements;
- evidence lineage.

### Constraint

Memory/steering remains advisory to planning.

It must not create execution authority.

---

## STYX-004 — Ralph Historical Material Still Exists Beside Native Runtime

**Status:** OPEN  
**Target:** R3E / R3F  
**Severity:** HIGH

### Finding

Historical `.ralph` material remains in the repository.

This is currently intentional.

### Risk

Future native code could accidentally interpret historical records as live state or fallback material.

### Required Resolution

R3E must create an explicit historical/provenance boundary.

R3F must hostile-test that Ralph can never supply live authority.

### Constraint

Do not delete historical evidence merely to make tests pass.

---

## STYX-005 — Installed Product Cannot Yet Perform Full Qualified Self-Rebind

**Status:** CLOSED — R3D.1 exact-artifact qualification 2026-10-07
**Target:** R3D.1
**Severity:** BLOCKING FOR LATER R3D

### Finding

Current native lifecycle supports compatibility acceptance around installed product versions but does not yet provide the complete self-development handoff required by R3D.

### Required Resolution

Implement:

- deterministic artifact;
- artifact/package/RECORD identity;
- executable identity;
- quiescent transition;
- explicit confirmation;
- preserved plan/transaction/scope/provenance;
- new runtime epoch/controller identity;
- fresh-process proof;
- failure-safe old authority retention.

### Step 1 evidence

The native `stygnox rebind` preview/confirm/activate path now binds wheel and
installed RECORD identities, executable, canonical project, active-plan scope
and lineage before a fresh-process controller rebind.  The issue remains open
until the controlled installed-artifact qualification demonstrates the full
handoff and hostile cases.

### Step 1 exact-artifact qualification

The D8.7 build-once gate now invokes an R3D.1 installed-successor qualifier.
It installs the supplied wheel into a fresh virtual environment, binds the
pending handoff to exact wheel/RECORD/executable identities, and requires the
fresh successor receipt before later work opens.  Hostile refusals retain the
predecessor records; CAP-011 history is neither provider attribution nor
executable authority.

### Step 3 transition gate

An accepted R3D.1 step can now require an independently attested
post-qualification transition.  Source qualification alone leaves execution
closed; the successor must be live with the exact installed identity, artifact,
epoch, plan, transaction, controller and qualification bindings before the
next step can open.  This is a general plan/qualification contract, with the
installed-successor handoff as its current use.

### 2026-10-07 bootstrap-closure intervention

The stalled Step 1 runtime exposed a self-hosting deadlock rather than a reason
to relax authority.  The operator froze that runtime and performed one bounded
source-level closure that preserves its evidence but does not treat the stalled
transaction as successful execution.

### Final resolution

The D8.7 build-once gate now qualifies the exact release wheel through a fresh
installed successor.  The qualification binds wheel/package/RECORD/executable,
canonical worktree, plan/scope/provenance/checkpoint lineage, transaction,
controller and runtime epoch.  It proves a separately-started installed
successor becomes live before later work opens and proves hostile source-tree,
PYTHONPATH/Ralph-decoy, copied-launcher, substituted-artifact and failed-handoff
cases retain predecessor authority.  The success receipt explicitly records
`source_tree_fallback=false` and `ralph_fallback=false`.  STYX-005 is closed.

---

## STYX-006 — Bootstrap Configuration Requires Separate Provenance

**Status:** CLOSED — R3D.1 bootstrap disposition 2026-10-07
**Target:** R3D.1
**Severity:** HIGH

### Finding

The native adoption process created:

```text
stygnox.toml
stygnox.policy.md
```

before the R3D provider plan.

They remain legitimate project material but cannot be attributed to future provider implementation.

### Required Resolution

Create a separate auditable bootstrap disposition/commit and rebase provider authority afterward.

Maintain:

```text
accepted provider attribution
==
qualified provider delta
==
finalized provider delta
```

### Final resolution

The installed-successor qualification records `stygnox.toml` and
`stygnox.policy.md` as `OPERATOR_ADOPTION_MATERIAL`, with provider attribution
`EXCLUDED` and accepted/qualified/finalized provider-delta flags all false.
The rebind lineage preserves that disposition rather than absorbing bootstrap
material into provider implementation.  STYX-006 is closed.

---

## STYX-007 — Runtime State Access Is Distributed

**Status:** OPEN  
**Target:** R3D.2  
**Severity:** HIGH

### Finding

Multiple native modules independently interpret `.stygnox` state.

### Risk

Competing read/write semantics create ambiguity and undermine a future Controller API.

### Required Resolution

One validated native runtime seam becomes authoritative for all live runtime access.

---

## STYX-008 — Full Lease / Process Identity Semantics Incomplete

**Status:** OPEN  
**Target:** R3D.3  
**Severity:** HIGH

### Required Resolution

Bind live operations to exact:

- host boot;
- PID;
- process-start identity;
- installed artifact;
- executable;
- runtime epoch;
- transaction;
- plan;
- step;
- scope;
- checkpoint.

No automatic stale takeover.

---

## STYX-009 — Previous Web UI Retired

**Status:** DEFERRED  
**Target:** Web UI vNext after Controller API v1  
**Severity:** ARCHITECTURAL

### Finding

Previous Web UI was retired because its architecture and testing no longer justified repair.

Problems included:

- dead/non-working actions;
- static/dynamic confusion;
- inappropriate options;
- missing analytics;
- missing live status/logs;
- poor test value.

### Decision

Do not resurrect it.

Preserve:

- branding;
- style assets;
- controller hooks where useful.

Replacement should be an independently developable Node/TypeScript application consuming Controller API v1.

---

## STYX-010 — Native Skills Platform Required

**Status:** DEFERRED  
**Target:** Post-core capability  
**Severity:** STRATEGIC

### Decision

Stygnox will not depend on ECC or another external skills runtime.

ECC and comparable ecosystems are references from which useful methods can be studied.

Stygnox will implement native semantics for:

- skill discovery;
- applicability;
- approval;
- pinning;
- integrity;
- licensing;
- provenance;
- contextual activation.

External skill repositories may be optional sources/adapters.

Loss of an external source must not impair core Stygnox execution.

### Invariant

```text
skill != authority
```

---

## STYX-011 — AgentMemory Must Be Native and Advisory

**Status:** DEFERRED  
**Target:** Post-core capability  
**Severity:** STRATEGIC

### Decision

Do not make an external memory framework a Stygnox runtime dependency.

Define native Stygnox memory semantics.

Potential consumers/providers may integrate through adapters.

### Invariant

Memory may inform a decision.

Memory cannot issue authority.

---

## STYX-012 — Documentation May Drift Behind Native Product

**Status:** OPEN / WATCH  
**Target:** Continuous; formal closure before Core Baseline Lock  
**Severity:** MEDIUM

### Finding

Ralph retirement, native CLI changes, runtime convergence and Web UI retirement make documentation drift particularly dangerous.

### Required Resolution

Every architectural stage evaluates documentation impact.

Before Core Baseline Lock, perform a full documentation qualification.

Normal operating documentation must describe the native Stygnox product.

Ralph may appear only in historical/migration contexts.

---

## STYX-013 — Token and Context Efficiency

**Status:** WATCH  
**Target:** Operating model / Proposal Steering  
**Severity:** COST / PRODUCTIVITY

### Finding

Repeated full planning passes, giant manually reconstructed prompts, duplicated reviews and unnecessary low-level command sequences consume substantial model tokens without corresponding engineering value.

### Operating Decision

- one substantial architectural stage at a time;
- architecture only re-opened for genuine blockers;
- implementation/evidence should use cost-effective capable models;
- expensive reasoning reserved for architecture/hostile review;
- delta reviews preferred after an authoritative baseline exists;
- rejection steering should eventually become first-class;
- repository evidence preferred over rediscovery through conversation.

Token efficiency is a legitimate engineering requirement.

---

## STYX-014 — `add-only` Continuation Used Per-Turn Instead of Approval Baseline

**Status:** CLOSED — consolidated R3D.1 closure patch 2026-10-07
**Target:** R3D.1
**Severity:** HIGH

### Finding

A fresh installed R3D.1 controller legally created an approval-time-new test
under `test_change_policy=add-only`, continued the same approved step, then
incorrectly treated refinement of that same test as modification of a
pre-existing test.  The worker prompt encoded the same per-turn rule.

### Root Cause

Native enforcement supplied repository paths from the beginning of each
provider turn to the test-policy evaluator.  This reset test presence across
continuation turns instead of preserving the immutable plan-approval baseline.

### Resolution

`add-only` presence is now evaluated against `approval_repository_manifest`.
Tests present at plan approval remain read-only; tests absent at plan approval
remain new-test paths across bounded continuation turns, subject to immutable
mutation scope and separate self-development authority.  Worker guidance
describes the same rule.

A behavioral regression creates an approval-time-new test on turn one, records
a same-step continuation, refines it on turn two, and proves no test-policy
gate opens.

---

## STYX-015 — TOP Must Be Truly Live and Preserve Native Authority

**Status:** OPEN — requirements locked, implementation pending
**Target:** R3D.2/R3D.3 dependencies; R3D.4 delivery; R3D.5 final qualification
**Severity:** HIGH / ARCHITECTURAL

### Finding

The existing `stygnox tui` is a concise snapshot, not a dependable full-screen
live operations console. A snapshot refreshed repeatedly, raw JSON dump, fake
heartbeat, guessed progress, file-scraped status or second authority model
would fail the locked R3D.4 `stygnox top` requirement.

### Decision and required resolution

TOP-01/02 shall use only the canonical native runtime/evidence and authoritative
lifecycle/epoch seams built within independently approved R3D.2/R3D.3 scope.
TOP-03/04 shall deliver a real alternate-screen, continuous, responsive,
keyboard-interactive dashboard with plan/step, true observable execution,
selected events/evidence, persistent CTRL/TX/EPOCH/GATE/REC/ART/SRC/RALPH,
exact authoritative wordmark/theme and correct active/blocked/stopped states.
The initial TOP is strictly **read-only** for authority-changing operations.
If live provider detail is not emitted, TOP must show the most recent authentic
record and its age and state the limitation, not simulate activity.

TOP-05 and R3D.4 regressions must exercise two independent installed processes
(real scheduler and TOP) while running and when gated, stopped, failed,
recovering or rebound, including replay/gaps, malicious output, resize,
Ctrl-C, bounded buffering and terminal restoration. Verify CLI/TUI/TOP state
parity, controller non-interference, and immediate stale-epoch invalidation.

### Source and disposition

Locked 664-line amendment:
`docs/programme/amendments/STYGNOX-R3D4-TOP-PROGRAMME-AMENDMENT.md`
(commit `4b4bafa`). **OPEN**, not discharged by a documentation commit.
Do not pull R3D.4 renderer or Web UI work into R3D.2.

---

## STYX-016 — Provider Quota and Usage Must Be Authoritative, Fresh and Deduplicated

**Status:** OPEN — requirements locked, provider capability inventory pending
**Target:** R3D.2 provider telemetry contract assessment; R3D.4 accounting/UI; R3D.5 qualification
**Severity:** HIGH / TRUST

### Finding

A displayed five-hour or weekly capacity bar is misleading unless backed by
provider-reported limit/window/scope, remaining percentage, reset time and
observation freshness. Token receipts may be delayed, replayed, duplicated or
provider-specific; cached input is usually a subset of input, not extra usage.
No uploaded programme source proves all providers currently expose those quota
windows, resets or real-time tool/token events.

### Decision and required resolution

TOP-01 inventories existing native provider receipts and authenticated quota
observations, defines schema and explicit unavailable/stale distinctions.
TOP-03 shows visible 5-hour and weekly % left/used, resets/countdowns **when
reported**, otherwise UNKNOWN/UNAVAILABLE/STALE (never a fabricated 0 or
estimated balance). Attribute account-shared quota to the correct scope.
Show per-turn/round, step, run and historical input/output/cached/reasoning
(where available), model/effort/timing/outcomes. Dedupe stable receipt IDs,
keep provisional versus final reports distinct, and avoid cached/retry double
counting; quota is never derived from token totals absent provider authority.
TOP-04/05 tests include provider-missing data, quota freshness/reset transitions,
replay/duplicate receipts, provider changes and idle/blocked final accounting.

### Source and disposition

Locked R3D.4 amendment §§9A, 9B, 9C and 10; commit `4b4bafa`.
**OPEN** pending source capability evidence, implementation and qualification.

---

# New Finding Template

Copy for each material discovery:

```markdown
## STYX-NNN — Title

**Status:** OPEN | RESOLVED | DEFERRED | WATCH | SUPERSEDED
**Target:** Stage/capability
**Severity:** BLOCKING | HIGH | MEDIUM | LOW | COST | STRATEGIC

### Finding

What was discovered?

### Evidence

What proves it?

### Risk

Why does it matter?

### Decision

What have we decided?

### Required Resolution

What must happen?

### Disposition

Current outcome and next gate.
```

---

# Reconciliation Rule

At every architectural block closure:

1. inspect every OPEN/WATCH issue relevant to the block;
2. close only findings supported by evidence;
3. create findings for newly discovered gaps;
4. explicitly retain deferred findings;
5. update `PROGRESS.md`;
6. review `STYGNOX-ROADMAP.md`;
7. commit the reconciled programme state.

A finding must never disappear because a chat ended or context was compacted.
