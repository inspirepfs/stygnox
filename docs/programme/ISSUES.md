# Stygnox Programme Issues and Findings

**Status:** AUTHORITATIVE FINDINGS REGISTER  
**Last reconciled:** 2026-10-05

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

**Status:** OPEN  
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

---

## STYX-006 — Bootstrap Configuration Requires Separate Provenance

**Status:** OPEN  
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

