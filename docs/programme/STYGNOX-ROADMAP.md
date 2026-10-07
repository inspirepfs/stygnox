# Stygnox Programme Roadmap

**Status:** AUTHORITATIVE  
**Programme:** Stygnox Autonomous Development-Loop Platform  
**Last major reconciliation:** 2026-10-05  
**Current programme stage:** R3D — Runtime Convergence

---

# 1. Purpose

Stygnox is an autonomous engineering **control plane**.

It is not intended to become another general-purpose coding agent, another model wrapper, or a thin integration layer around external agent frameworks.

The core product thesis is:

> **Models provide intelligence. Skills provide expertise. Stygnox provides authority.**

Models, skills, tools, UIs and external services are replaceable participants.

Stygnox owns the execution contract.

---

# 2. North-Star Architecture

The desired end state is:

```text
                         STYGNOX

                ┌─────────────────────┐
                │ Native Controller   │
                │ .stygnox runtime    │
                └──────────┬──────────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
             CLI          TUI     Controller API v1
                                        │
                            ┌───────────┼───────────┐
                            │           │           │
                         Web UI      IDE/client   Automation
                         Node/TS
```

The controller and `.stygnox` runtime are authoritative.

Everything else is a client, provider, adapter or advisory capability.

---

# 3. Non-Negotiable Authority Principles

## 3.1 One live authority

`.stygnox` is the sole live runtime authority.

The independently installed `stygnox` product is the sole supported live execution identity.

There must be no dynamic selection between Stygnox and Ralph.

## 3.2 Ralph is historical only

Ralph is being completely retired as live infrastructure.

`.ralph` may survive only where required for:

- historical evidence;
- explicit migration;
- provenance;
- compatibility analysis.

It must never provide:

- controller authority;
- current plan state;
- execution authority;
- recovery authority;
- scheduler authority;
- provenance assignment;
- fallback execution.

The programme is not complete until hostile qualification proves this.

## 3.3 Execution is contract-bound

A material Stygnox execution is bound to, at minimum:

```text
canonical project
runtime epoch
installed controller identity
transaction
plan hash
step
repository mutation scope digest
baseline/checkpoint
provider
human grants
provenance
recovery lineage
qualification state
```

The worker consumes this contract.

The worker does not own or redefine it.

## 3.4 Mutation scope is a ceiling

`repository_mutation_scope` is an immutable **maximum permitted path ceiling**.

Actual provider mutation may be a strict subset.

Unused approved paths are valid.

No worker, skill, model, tool or presentation layer may expand the ceiling.

## 3.5 Attribution invariant

The following must remain exact:

```text
accepted provider attribution
        ==
qualified provider delta
        ==
finalized/committed provider delta
```

Pre-existing operator work, bootstrap material, external changes and provider-generated changes must never be silently conflated.

## 3.6 Fail closed

If Stygnox cannot prove authority, it refuses execution.

Examples include:

- wrong project;
- wrong runtime epoch;
- changed executable;
- wrong controller;
- changed plan;
- changed scope;
- corrupted records;
- copied runtime;
- stale/reused PID;
- interrupted work without valid recovery evidence;
- missing provenance;
- legacy runtime reappearance.

No silent takeover or best-effort authority reconstruction.

---

# 4. Product Layers

```text
                    STYGNOX AUTHORITY CORE
                           │
            contracts / state / evidence
            provenance / recovery
            qualification / finalization
                           │
       ┌───────────────────┼───────────────────┐
       │                   │                   │
   INTELLIGENCE         EXPERTISE           TOOLS
       │                   │                   │
 model providers       native skills      adapters
 Codex / future        platform            GitHub
 models                project skills      scanners
                       imported skills     testing
       │                   │                   │
       └───────────────────┼───────────────────┘
                           │
                         AGENTS
                           │
                 advisory memory/context
```

A smarter model or better skill must never implicitly create more authority.

---

# 5. Current Core Programme

## R3B — Controller Authority Foundation

**Status: COMPLETE**

Established core controller-owned authority semantics including:

- transactions;
- execution authority;
- immutable scope;
- provenance;
- human gates;
- qualification;
- recovery;
- self-development controls;
- finalization semantics.

---

## R3C — Native Source Convergence

**Status: COMPLETE**

Closed at original R3C baseline:

`1e3fa0270c9bf26ec2b47b039680af07a8ad772f`

Outcomes:

- `src/stygnox/` became the native product;
- independently installable Stygnox wheel established;
- `scripts/stygnox_cli.py` retired as execution authority;
- native package does not depend on Ralph for normal execution;
- native controller/operator/TUI foundations established.

A later bounded bootstrap fix moved the current baseline forward without changing R3C architecture.

---

## Bootstrap Approval-Snapshot Repair

**Status: COMPLETE**

Current baseline:

`6427efa554d8350aae72b72b85512f5a7d9ba346`

Resolved a native approval deadlock where tracked historical `.ralph/policy.md` was incorrectly treated as plan-owned rollback material.

Correct semantic:

- complete repository manifest remains fingerprint-bound;
- protected runtime/historical paths remain evidence;
- protected paths are excluded from plan-owned rollback archives.

This repair is a prerequisite correction, not a new programme stage.

---

# 6. R3D — Runtime Convergence

**Status: CURRENT**

R3D converts native Stygnox source convergence into complete native runtime convergence.

Exactly five architectural stages are intended.

## R3D.1 — Installed Product Identity and Upgrade/Rebind

Build the native self-development lifecycle.

Requirements include:

- deterministic accepted artifact;
- exact artifact digest;
- package identity;
- installed RECORD identity;
- executable identity;
- canonical project identity;
- quiescent handoff;
- explicit preview/confirmation;
- preservation of plan, transaction, scope, provenance and checkpoint lineage;
- runtime epoch/controller rebind;
- fresh-process proof;
- failure before transfer leaves previous authority intact;
- no source-tree fallback.

Also resolve the pre-plan provenance of:

Review note (2026-10-05): R3D.1 intent is unchanged; the installed-only
rebind implementation is being qualified against these requirements.

Review note (2026-10-06): where an accepted step requires the installed
successor handoff, its source qualification does not advance execution.  The
next step opens only after the separately attested, identity-valid successor
transition is complete.

Review note (2026-10-07): the Step 1 self-hosting bootstrap loop is closed by an
explicit operator source intervention, not by widening controller authority.
The stalled runtime remains historical evidence; after the closure commit a
fresh installed authority epoch must re-prove the native rebase, provenance and
installed-successor semantics before R3D.1 can close.

- `stygnox.toml`
- `stygnox.policy.md`

These are adoption/bootstrap material and must not be attributed to a provider implementation step.

## R3D.2 — Canonical `.stygnox` Runtime Seam

Introduce one native runtime abstraction.

Remove competing interpretations caused by independent readers, writers, glob scans and mtime selection.

The runtime layer owns:

- project identity;
- runtime epoch;
- installed controller identity;
- schemas;
- integrity;
- lineage;
- atomic records;
- append-only evidence;
- checkpoints;
- locks;
- leases;
- passive snapshots.

## R3D.3 — Concurrency, Interruption and Recovery

Introduce exact process/lease semantics.

Bind operations to:

- host boot;
- PID;
- process start identity;
- controller;
- executable;
- runtime epoch;
- transaction;
- plan;
- step;
- scope;
- checkpoint.

Duplicate or stale authority fails closed.

Scheduler recovery and pending-provenance recovery remain distinct.

`.ralph` becomes explicitly isolated from live runtime interpretation.

## R3D.4 — Native Operator Experience Parity

Restore the proven human operator experience natively.

The existing branded TUI is retained and enhanced rather than redesigned.

Required native experience includes:

- human-readable default output;
- explicit JSON/machine mode;
- live planning heartbeat;
- live execution events;
- current plan and step;
- model and effort;
- phase/repair loop;
- transaction/recovery state;
- quota/usage;
- progress;
- commands;
- edits;
- tests;
- PASS/FAIL;
- summaries;
- human-readable gates;
- recovery banners;
- qualification status.

Representative event classes:

```text
PLAN
CHECKPOINT
AUTHORITY
SANDBOX
CODEX/provider
RUN
CREATE
EDIT
DELETE
TEST
PASS
FAIL
USAGE
SUMMARY
RECOVERY
GATE
QUALIFICATION
```

CLI and TUI consume the same canonical event/state model.

Presentation owns no authority.

Normal operation should converge towards simple workflows equivalent to:

```text
stygnox plan ...
stygnox approve <plan>
stygnox run ...
```

Low-level primitives remain available for debugging, automation, hostile testing and recovery.

## R3D.5 — Hostile Runtime Qualification

Final R3D stage is qualification-only.

It must prove the finished behaviour through the exact upgraded installed command.

It must hostile-test:

- installed artifact identity;
- runtime epoch;
- canonical root;
- copied runtime;
- wrong executable;
- duplicate controller;
- duplicate scheduler;
- stale/dead/reused PID;
- interruption;
- malformed/corrupted state;
- symlink substitution;
- legacy runtime reappearance;
- operator/TUI parity;
- attribution invariants;
- scope invariants;
- human controls;
- self-development;
- qualification/finalization.

No production repair belongs in R3D.5.

---

# 7. R3E — Historical and Provenance Boundary

**Status: PLANNED**

R3E defines the permanent boundary between historical Ralph material and live Stygnox state.

Goals include:

- identify remaining `.ralph` evidence;
- classify historical versus migration-required material;
- eliminate accidental runtime interpretation;
- ensure historical data remains auditable;
- preserve provenance where required;
- ensure compatibility code is explicit and bounded;
- remove unnecessary legacy coupling without deleting evidence merely to make tests pass.

R3E must not recreate Ralph compatibility as live authority.

---

# 8. R3F — Hostile Zero-Ralph Qualification

**Status: PLANNED**

R3F is the programme gate proving Ralph is dead as runtime infrastructure.

The system will be attacked for any remaining:

- Ralph imports;
- Ralph execution paths;
- `.ralph` runtime reads;
- source wrapper fallback;
- dynamic native/Ralph selection;
- recovery fallback;
- controller fallback;
- scheduler fallback;
- authority inference from historical state.

The core statement after R3F should be:

> Ralph is historical evidence. Stygnox is the product.

---

# 9. Controller API v1

**Status: PLANNED AFTER R3F**

Expose stable controller semantics through an API.

The API must project controller state rather than create competing authority.

Likely areas include:

- operator snapshot;
- plans;
- plan progress;
- execution;
- live events;
- human gates;
- recovery;
- qualification;
- usage;
- provider state;
- project/runtime identity;
- lifecycle;
- diagnostics.

API v1 should have an explicit compatibility contract.

Breaking semantic changes should require a future major API version.

---

# 10. Core Baseline Lock

**Status: PLANNED**

After R3F and Controller API qualification, create a formal core baseline.

The locked core should include:

- authority model;
- runtime model;
- installed-product lifecycle;
- controller;
- scheduler;
- recovery;
- qualification;
- finalization;
- CLI;
- TUI;
- Controller API;
- provenance;
- human gates;
- self-development;
- operator documentation.

Major new capabilities should build on this baseline rather than alter its fundamental authority semantics casually.

---

# 11. Web UI vNext

**Status: DEFERRED UNTIL CONTROLLER API**

The previous Web UI has been intentionally retired because it was structurally unreliable.

Problems included:

- non-working controls;
- static data pretending to be dynamic;
- inappropriate options always visible;
- incomplete analytics;
- missing live logs/status;
- meaningless or insufficient tests.

Existing branding assets, tokens and authoritative style material are preserved.

Replacement architecture:

```text
Node/TypeScript Web UI
        │
        ▼
Controller API v1
        │
        ▼
Stygnox Controller
```

The Web UI should be independently developable and testable.

It must not access `.stygnox` directly or become an authority implementation.

---

# 12. Native Stygnox Skills Platform

**Status: POST-CORE CAPABILITY**

Stygnox must not depend on ECC, skills.sh or another external skill runtime.

Instead:

> Study proven patterns, define a Stygnox contract, implement the capability natively.

ECC and other ecosystems are design/reference sources and optional skill sources.

They are not runtime dependencies.

The native platform should support:

- skill schema/manifest;
- repository discovery;
- technology detection;
- current-work awareness;
- applicability assessment;
- operator approval;
- built-in skills;
- project skills;
- imported skills;
- exact version/content pinning;
- origin/provenance;
- licensing;
- licence obligations;
- integrity verification;
- enable/disable/supersede;
- reassessment;
- plan/step-specific selection;
- evidence showing which skills influenced a run.

Expected operator entry points may include:

```text
stygnox init
stygnox doctor
stygnox skills assess
```

Exact commands are not yet locked.

Core invariant:

> **Skill != authority.**

A skill may improve how work is performed.

It cannot expand mutation scope, grant execution, approve a plan, satisfy a gate, alter provenance or override qualification.

---

# 13. External Ecosystem Policy

Stygnox should study useful mechanisms from:

- ECC;
- OpenHands;
- LangGraph;
- GitHub agent workflows;
- Codex;
- Claude ecosystems;
- other emerging agent systems.

The preferred process is:

```text
study mechanism
      ↓
identify useful semantic
      ↓
define native Stygnox contract
      ↓
implement natively
      ↓
hostile qualify
```

Not:

```text
make external framework part of Stygnox's authority core
```

Where external functionality is genuinely desirable, use replaceable adapters.

Examples:

```text
provider adapters
tool adapters
skill-source adapters
SCM adapters
notification adapters
```

Loss of an adapter must not invalidate the Stygnox authority model.

---

# 14. Native Agent Memory

**Status: POST-CORE / DESIGN AFTER AUTHORITY CONVERGENCE**

Memory must also be a native Stygnox semantic rather than a dependency on an external memory framework.

Potential records include:

- architectural decisions;
- rejected approaches;
- operator corrections;
- hostile-review findings;
- project conventions;
- known provider failure modes;
- qualification lessons;
- recurring constraints.

Memory is advisory.

It must not become authority.

Conceptually:

```text
memory → informs agent/controller decisions
authority → determines what may actually happen
```

---

# 15. Proposal Steering

Proposal Steering is a specific high-value memory/governance capability.

When a proposal is rejected, the next proposal must explicitly consume:

- rejection identity;
- rejection rationale;
- accepted portions;
- rejected portions;
- corrections;
- evidence;
- lineage.

The system must not rely on repeated manual prompt reproduction.

This is intended to reduce:

- repeated rejected designs;
- model token consumption;
- operator effort;
- context loss.

A first-class mechanism such as rejection-linked proposal lineage is preferred over implicit conversational memory.

---

# 16. Competitive Position

Stygnox should not attempt to win by having:

- the largest model catalogue;
- the largest skill catalogue;
- the most agent personalities;
- the fastest-growing plugin ecosystem.

Those ecosystems can evolve independently.

Stygnox's differentiation is the control contract around autonomous engineering.

Particularly strong characteristics include:

- immutable plan identity;
- immutable maximum mutation ceiling;
- exact project binding;
- installed artifact binding;
- runtime epoch binding;
- human authority grants;
- explicit provenance;
- accepted/qualified/finalized delta equality;
- controller-owned qualification;
- exact recovery;
- fail-closed ambiguity handling;
- hostile self-validation;
- controlled self-development;
- separation of workers from authority;
- separation of clients from authority;
- auditable historical lineage.

The north-star hostile question is:

> **Can the system be tricked into believing it possesses authority that was never issued?**

The intended answer is no.

---

# 17. Documentation Programme

Before Core Baseline Lock, documentation must be reconciled against the actual product.

Documentation should cover:

- installation;
- initialization/adoption;
- planning;
- approval;
- execution;
- TUI;
- controller;
- scheduler;
- human gates;
- recovery;
- self-development;
- qualification;
- finalization;
- runtime structure;
- authority contracts;
- provenance;
- upgrade/rebind;
- Controller API;
- skills;
- migration/history.

Normal operator documentation must not instruct users to execute Ralph.

Historical/migration material may reference Ralph only in that explicit context.

---

# 18. Programme Closure Contract

Every architectural block must perform programme reconciliation before being considered closed.

Required closure sequence:

```text
implementation/evidence complete
        ↓
qualification green
        ↓
update PROGRESS.md
        ↓
reconcile ISSUES.md
        ↓
review this ROADMAP
        ↓
record newly discovered work
        ↓
confirm deferred work still belongs later
        ↓
commit governance updates
        ↓
push qualified result
```

A stage is not considered fully closed merely because tests pass.

The programme record must also agree with reality.

---

# 19. Programme Sources of Truth

Priority order:

1. controller/runtime evidence;
2. committed repository implementation;
3. committed programme-control documentation;
4. committed tests and qualification evidence;
5. GitHub issues/projects where used;
6. conversational context.

Chat history is useful working context but is not programme authority.

GitHub issues may mirror programme work but must not silently replace the committed roadmap/progress/issues record.

---

# 20. Operating Discipline

For substantial Stygnox development:

- architecture/hostile review: use high-capability reasoning where genuinely required;
- implementation/evidence: use the most cost-effective capable worker;
- avoid repeated full reviews where delta review is sufficient;
- avoid micro-decomposition;
- one substantial architectural stage at a time;
- remain read-only until a real gap is demonstrated;
- every restored/replaced semantic gets regression coverage;
- backend/CLI before TUI;
- TUI before Web UI;
- do not interrupt core convergence with attractive deferred features.

Token efficiency is an engineering concern.

Repeated rejected proposals, repeated context reproduction and unnecessary architectural replanning are defects in the operating model, not unavoidable costs.

---

# 21. Current Direction

The immediate critical path is:

```text
R3D Runtime Convergence
        ↓
R3E Historical/Provenance Boundary
        ↓
R3F Hostile Zero-Ralph Qualification
        ↓
Controller API v1
        ↓
Core Baseline Lock
```

Then expand safely into:

- Web UI vNext;
- Native Skills Platform;
- AgentMemory;
- Proposal Steering;
- richer provider/tool adapters;
- additional operator intelligence.

The authority foundation comes first.
