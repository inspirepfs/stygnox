# Stygnox Programme Roadmap

**Status:** AUTHORITATIVE  
**Programme:** Stygnox Autonomous Development-Loop Platform  
**Last major reconciliation:** 2026-10-08 (TOP-00 requirements alignment)
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

`stygnox tui` is a concise snapshot client; the committed R3D.4 requirement
adds a separate `stygnox top` full-screen live client over the **same** native
state/evidence authority. Neither terminal view owns execution authority.

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

**Status: CLOSED (2026-10-07)**

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

- `stygnox.toml`
- `stygnox.policy.md`

These are adoption/bootstrap material and must not be attributed to a provider
implementation step.

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

Qualification note (2026-10-07): the D8.7 build-once exact-wheel gate exercises
the pending installed-successor transition from a fresh virtual environment.
The successor must make its transaction/controller live and attest the same
wheel, installed identity, canonical worktree, plan lineage and runtime epoch;
source/PYTHONPATH/Ralph decoys, copied launchers, artifact substitution and
handoff failures retain predecessor authority.

Closure note (2026-10-07): R3D.1 closed after the fresh installed authority
exposed and the consolidated closure patch repaired a native `add-only`
continuation regression.  Test-policy presence is now measured against the
immutable plan-approval repository manifest rather than each provider-turn
baseline, preserving approval-time test immutability while permitting
approval-time-new tests to be refined across bounded same-step continuations.
The exact-wheel qualifier is composed into D8.7 and proves installed successor
identity/lineage, fresh-process rebind, runtime epoch transfer, failure-safe
predecessor retention and zero source/Ralph fallback.  Bootstrap config/policy
are operator adoption material with provider attribution explicitly excluded.

Post-R3D.1 programme checkpoint (TOP-00, 2026-10-08): the locked,
committed R3D.4 `stygnox top` amendment (source commit `4b4bafa`) is
reconciled into the R3D.2–R3D.5 dependency and acceptance contracts below.
This governance change establishes requirements **only**. R3D.2 remains the
next implementation stage; neither TOP code nor R3D.3/R3D.4 capability is
implemented by TOP-00. The programme-documents reconciliation must be
committed/pushed before a fresh R3D.2 transaction begins.

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

**TOP dependency / R3D.2 scope assessment (not a TOP implementation):**

- define a versioned canonical read-only state/snapshot contract and an
  integrity-checked native event/evidence envelope where supported by this
  stage's independently approved mutation scope;
- carry source, event identity/ordering or cursor, timestamp, canonical project,
  installed-product/controller identity, transaction and runtime epoch; include
  plan/step correlation only where authority supplies it;
- establish documented distinctions between evidence, authoritative state,
  unavailable telemetry and derived presentation; never infer state via TOP
  filesystem glob/mtime/PID guessing or `.ralph` fallback;
- define an explicit capability/gap inventory for provider progress, token
  receipts, quota windows, refresh/freshness, and replay/cursor semantics;
- test schema/integrity, wrong-root/epoch and authority-substitution refusals;
  do **not** claim R3D.2 supplies complete streaming/provider instrumentation.

A missing contract is a recorded upstream gap for the appropriate later stage,
not permission for a presentation-only workaround. STYX-007 and STYX-015/016
track this boundary.

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

**TOP lifecycle dependency / R3D.3 scope assessment:** canonical runtime
consumers need unambiguous RUNNING, WAITING, BLOCKED, HUMAN GATE, QUALIFYING,
RECOVERING, STOPPED, FAILED, COMPLETE, STALE and UNKNOWN semantics where
observable. Lease/recovery/rebind transitions must provide enough epoch and
identity evidence to **invalidate** a stale client and reconnect/replay safely
where supported, without implying that absence of events proves process death.
Record unresolved streaming/replay gaps for R3D.4 rather than widening R3D.3
into a terminal UI project.

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

CLI, concise snapshot `stygnox tui`, and full-screen `stygnox top`
consume the same canonical event/state authority. CLI defaults remain human
readable with a separate explicit machine/JSON mode.

### Locked TOP operator contract — TOP-00

Source of truth: `docs/programme/amendments/STYGNOX-R3D4-TOP-PROGRAMME-AMENDMENT.md`
(commit `4b4bafa`, 2026-10-07). The committed amendment is preserved **intact**;
this roadmap is the stage-level acceptance summary, not a replacement for its
exact wordmark/theme and detailed clauses 1–12.

- `stygnox top` is a **true alternate-screen, continuously updating** terminal
  client, separate from the snapshot `stygnox tui`, with clean terminal/scrollback
  restoration, responsive wide/medium/narrow layout and full keyboard use.
- On suitable terminals show three substantial working areas: **approved plan
  and progress**, **actual recorded live actions/events**, and a **persistent
  model/capacity/usage pane**. Offer selected-event evidence/detail, search,
  filter, follow/pause, drill-down and a full-viewport `u` usage/history view.
- Keep controller/transaction/gate/recovery/installed artifact/epoch/source/
  Ralph-status authority visible across navigation; old epochs and rebinds
  must display **STALE**, not counterfeit continued liveness.
- Preserve the exact six-line Stygnox ASCII wordmark without clipping when it
  fits; use a deliberate compact label otherwise. Reuse the existing TUI's
  authoritative magenta/purple–blue/cyan semantic theme across CLI/TUI/TOP,
  with truecolour/256/ANSI/NO_COLOR readable fallbacks. Colour denotes state,
  not literal `NO`/`YES` strings.
- Display real RUN/STEP/TURN timers, model/effort/provider, phase/loop/limit,
  reserve and efficiency settings, real controller/provider actions, tool/test
  receipts, human-gate reason and permitted next action. Do not fabricate
  tool calls, model thoughts, progress percentages, or a heartbeat.
- Provide distinct **provider quota windows** (especially five-hour and weekly
  remaining percentages and reset times/countdowns **when reported**), with
  source/scope/observation age and UNKNOWN/UNAVAILABLE/STALE when absent.
  Provider/account quotas are **not** token-derived, and shared quota is not
  mislabeled as model-local.
- Provide per-turn/round, per-step, per-run and historical input/output/cached
  usage, reasoning tokens only if supplied; cached input must not be added to
  input again, and replay/retry must not double-count receipts. In-flight usage
  is explicitly provisional or AWAITING RECEIPT.
- Show live/snapshot distinction, event identity/cursor, gaps, timestamps,
  provenance and source freshness; a quiet provider is **not** automatically
  crashed. Render untrusted provider text safely and bound memory use.
- Initial TOP release is **read-only for authority-changing operations**;
  keyboard investigation cannot start/stop/recover/approve/retire/authorize.
  Quitting TOP cannot affect the controller or scheduler. Future mutations,
  if ever accepted, use the exact native preview/confirmation contracts.

**Delivery traceability / no premature stage expansion**

| Work package | Owner stage | Acceptance artifact |
|---|---|---|
| TOP-00 — governance lock | Post-R3D.1, before R3D.2 | committed amendment + ROADMAP/PROGRESS/ISSUES alignment; no runtime mutation |
| TOP-01 — native state/evidence dependency | R3D.2 | versioned canonical contract and gap register, integrity/identity tests |
| TOP-02 — lifecycle/epoch/rebind dependency | R3D.3 | authoritative transitions, invalidation, recovery/reconnect tests |
| TOP-03 — interface and instrumentation | R3D.4 | live full-screen TOP, shared theme, semantic UI, usage/quota investigation |
| TOP-04 — operational reliability | R3D.4 | real active/idle/blocked process testing, safety, gaps, bursts, resize and quotas |
| TOP-05 — hostile release qualification | R3D.5 | exact installed artifact, no-production-repair qualification and CLI/TUI/TOP parity |

Dependency contracts do not authorize bringing R3D.4 renderer, Web UI or
Controller API implementation forward into R3D.2/R3D.3. Gaps must be proven,
assigned to the correct stage, and protected with regressions. See STYX-002,
STYX-007, STYX-008, STYX-015 and STYX-016.

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
- CLI/TUI/TOP parity on canonical state and native installed product;
- independent active scheduler + TOP process, with terminal state restored;
- genuine running/stopped/blocked/gated/recovery/rebind observability;
- quota observation accuracy, freshness and unavailable-data honesty;
- token-receipt deduplication and cached-input accounting;
- event replay/gaps/duplication/bursts, stale-epoch and hostile untrusted text;
- TOP read-only non-interference and bounded resource use;
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
