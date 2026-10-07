# Stygnox Programme Amendment — R3D.4 Full-Screen `stygnox top`

**Status:** LOCKED FOR PROGRAMME RECONCILIATION
**Target:** R3D.4 — Native Operator Experience Parity
**Created:** 2026-10-06
**Reason:** Preserve the agreed full-screen live operations-console requirements outside transient chat context.

---

## 1. Decision

R3D.4 SHALL implement a first-class native command:

```text
stygnox top
```

`stygnox top` is a **true full-screen continuously updating terminal application**, comparable in interaction model to tools such as `btop`, `htop`, `k9s`, or `lazygit`.

It is not a snapshot command and is not merely `stygnox tui` refreshed in a loop.

`stygnox tui` remains the concise point-in-time operator snapshot.

`stygnox top` becomes the live autonomous-development operations console.

---

## 2. Authority Boundary

`stygnox top` is a presentation client over canonical native Stygnox state and events.

It SHALL NOT:

- create a separate source of authority;
- independently infer controller truth from arbitrary file scans;
- bypass preview/confirmation contracts;
- introduce a hidden mutation path;
- interpret `.ralph` as live state;
- become the canonical runtime implementation.

The intended path is:

```text
provider / controller / scheduler
             |
             v
      canonical native events
             |
             v
       .stygnox runtime
             |
      +------+------+
      |             |
     CLI           TUI
                    |
               stygnox top
```

Later, the same canonical state/event model will feed Controller API v1 and the independent Web UI.

---

## 3. Exact Terminal Wordmark

The following six-line Stygnox terminal wordmark is **authoritative** for the full-screen header and must not be truncated, re-generated, approximated, reflowed, or replaced by another ASCII rendering:

```text
 ____  _               _   _
/ ___|| |_ _   _  __ _| \ | | _____  __
\___ \| __| | | |/ _` |  \| |/ _ \ \/ /
 ___) | |_| |_| | (_| | |\  | (_) >  <
|____/ \__|\__, |\__, |_| \_|\___/_/\_\
           |___/ |___/
```

It is followed by:

```text
AUTONOMOUS DEVELOPMENT-LOOP PLATFORM
 PLAN - EXECUTE - EVIDENCE - EVOLVE
```

The exact wordmark text is part of the Stygnox terminal branding contract.

---

## 4. Existing Terminal Palette Is Authoritative

The current `stygnox tui` terminal appearance is the visual reference baseline for `stygnox top`.

R3D.4 SHALL preserve the existing Stygnox terminal colour language rather than invent a new theme.

Required semantic presentation classes include at least:

```text
BRAND
INFO
HEALTHY
ACTIVE
SUCCESS
WARNING
ATTENTION
BLOCKED
ERROR
INACTIVE
MUTED
```

Colour SHALL be driven by semantic state, not by matching literal strings.

For example:

```text
Controller ENABLED        -> healthy/green
Transaction ACTIVE        -> active/green
Recovery CLEAR            -> healthy/green
Attention NO              -> healthy/green
Source-tree fallback NO   -> healthy/green
Legacy delegate NO        -> healthy/green

WAITING                    -> warning/attention
HUMAN GATE                 -> warning/attention
BLOCKED                    -> error/red
FAILED                     -> error/red
invalid authority          -> error/red
fallback detected          -> error/red
```

A literal `NO` is not inherently red.

The existing purple/magenta and blue/cyan Stygnox branding, green healthy states, yellow attention states, red failure/authority-risk states, subdued separators, and high-contrast terminal text SHALL be retained.

The theme should be centralized and shared by:

- human CLI output;
- `stygnox tui`;
- `stygnox top`.

Terminal capability handling should support:

```text
truecolour terminal  -> full Stygnox palette
256-colour terminal  -> nearest semantic palette
basic ANSI terminal  -> semantic fallback colours
NO_COLOR/--no-color  -> readable monochrome
```

---

## 5. Full-Screen Behaviour

`stygnox top` SHALL:

- enter the terminal alternate screen;
- own the terminal until exit;
- restore the previous terminal cleanly on quit/error;
- react to terminal resize (`SIGWINCH` or equivalent);
- refresh continuously without scrolling the shell;
- avoid corrupting shell scrollback;
- provide keyboard navigation;
- remain useful while the scheduler/provider is running;
- show safe terminal state even when Stygnox is blocked, qualifying, recovering, or stopped.

Initial release is read-only for authority-changing actions.

Navigation/filter/search are allowed.

Any future approve/gate/resume/stop action exposed through `stygnox top` must call the same canonical controller preview/confirmation contracts as the CLI.

No TUI-only authority path is permitted.

---

## 6. Dashboard Layout

The full-screen console SHALL include four logical areas.

### 6.1 Header / top status bar

Always-visible high-value operating information should include, where supported:

- exact Stygnox product version;
- RUNNING / WAITING / BLOCKED / HUMAN GATE / QUALIFYING / RECOVERING / FAILED / COMPLETE;
- current programme stage;
- plan step / total;
- current execution phase;
- provider;
- model;
- effort;
- current loop / max loops;
- run elapsed timer;
- stage/step elapsed timer;
- current-turn elapsed timer;
- provider quota/usage remaining percentage when authoritative;
- next quota reset when authoritative;
- efficiency mode;
- reserve percentage;
- controller status;
- transaction status;
- recovery status;
- active gate/attention indicator.

Quota percentages or reset values MUST NOT be invented.

If authoritative provider quota data is unavailable, render an explicit unavailable/unknown state.

### 6.2 Plan / progress pane

Render the exact approved plan and controller state, for example:

```text
R3D Runtime Convergence

✓ 1 Installed product identity / rebind
▶ 2 Canonical .stygnox runtime seam
· 3 Concurrency / recovery / legacy isolation
· 4 Native operator experience parity
· 5 Hostile qualification
```

Also show as available:

- current step;
- controller phase;
- loop;
- checkpoint;
- qualification state;
- attention;
- gate;
- truthful progress.

Do not invent completion percentages where the controller lacks a real progress measure.

### 6.3 Live event stream pane

Consume the canonical R3D.4 native event model and render concise operator-facing lines.

Representative events include:

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

Example rendering:

```text
07:41:02  CODEX    turn started
07:41:04  RUN      inspect runtime readers
07:41:08  EDIT     src/stygnox/runtime.py
07:41:18  TEST     runtime regression
07:41:24  PASS     37 tests
07:41:25  USAGE    +18.4k input / +2.1k output
07:43:11  GATE     self-development authority required
```

Structured JSON is evidence, not the primary human interface.

### 6.4 Selected event / structured detail pane

Selecting an event exposes human-readable structured detail and optionally pretty-printed canonical JSON/evidence.

The detailed data remains exact and machine-derived.

The presentation layer must not reinterpret authority.

---

## 7. Permanent Authority/Health Visibility

The dashboard must keep controller health and authority visible rather than hiding it behind another screen.

At minimum show equivalents of:

```text
CTRL  ENABLED
TX    ACTIVE
GATE  CLEAR
REC   CLEAR
ATTR  CLEAN
SRC   NATIVE
RALPH NO
```

Important authority transitions must be visually prominent.

Examples:

```text
GATE HG-0002-01
BLOCKED HUMAN
RECOVERY REQUIRED
SOURCE FALLBACK DETECTED
LEGACY DELEGATE DETECTED
```

Stygnox's authority model is a central product differentiator and should be visible in normal operation.

---

## 8. Timers and Activity

Useful timers should include:

```text
RUN
STEP
TURN
```

When authoritative provider reset data exists, also:

```text
RESET
```

A last-event/activity age is desirable to distinguish active work from a potentially stuck provider:

```text
LAST EVENT
```

Status indicators should distinguish:

```text
ACTIVE
WAITING
ATTENTION
BLOCKED
QUALIFYING
RECOVERING
COMPLETE
```

without using fabricated progress.

---

## 9. Responsive Full-Screen Layout

`stygnox top` remains full-screen at supported terminal sizes.

Layout adapts rather than falling back to the existing snapshot:

```text
wide terminal
  -> header + two-column plan/events + authority/detail

medium terminal
  -> header + plan/events split + stacked authority/detail

narrow terminal
  -> full-screen stacked panes

very narrow terminal
  -> full-screen minimal operational view
```

The exact Stygnox wordmark may collapse only under a documented terminal-width threshold where rendering it intact is impossible.

It must never be truncated into a malformed logo.

At narrow widths, replace the full wordmark with a deliberate compact branded label such as `StygNox`, rather than clipping characters from the authoritative wordmark.

---

## 9A. Model Capacity and Token Accounting

Model capacity, quota windows, token consumption and efficiency are first-class
operational telemetry in `stygnox top`, not incidental header counters.

### 9A.1 Persistent capacity panel

At suitable terminal widths, the dashboard SHALL display a persistent,
dedicated model/capacity pane alongside the plan and execution-event panes.

It SHALL show:

- active provider, model, effort and execution mode;
- efficiency mode, reserve percentage, current loop and maximum loops;
- five-hour allowance remaining percentage, used percentage and reset time;
- weekly allowance remaining percentage, used percentage and reset time;
- reset countdowns when authoritative reset timestamps are available;
- telemetry observation age and freshness status;
- current turn input, output, cached-input and total tokens;
- current step and run token aggregates;
- most recent provider-usage receipt and its status.

Quota windows must be labelled by their actual provider-defined duration and
scope. Five-hour and weekly windows are required presentation capabilities
where offered by the provider, not assumptions that every provider has them.

Percentage bars SHALL represent remaining capacity. Colour SHALL reflect
remaining capacity and freshness, not the literal percentage alone.

For unavailable provider telemetry, render `UNKNOWN`, `UNAVAILABLE` or
`STALE` as appropriate. Never render an invented zero, reset time, allowance,
percentage or extrapolated quota balance.

Capacity telemetry SHALL retain provider identity, scope, source, observed
timestamp and freshness. Shared provider/account limits must not be falsely
attributed to an individual model.

### 9A.2 Exact token accounting

The interface SHALL provide these accounting scopes:

| Scope | Required presentation |
|---|---|
| Current turn/round | Input, output, cached input, reasoning if reported, total, duration, model, effort, outcome |
| Current step | Accumulated usage, turn count, elapsed time and recorded outcomes |
| Current run | Accumulated usage, successful/failed/retried turns, duration |
| Historical turns | Searchable per-turn receipts, model, timing and recorded evidence |
| Provider capacity | Independent quota windows, remaining percentage, reset and freshness |

Cached input is a subset of input tokens where reported that way; it must not
be added to input again when computing totals. Reasoning tokens must similarly
follow the provider's reported accounting semantics.

Usage aggregation SHALL deduplicate authoritative receipts by stable identity,
not simply sum every observed event. Retries, replay and reconnection must not
double-count consumption.

In-progress estimates, if available, must be labelled provisional and replaced
by final provider receipts. When only final receipts exist, display
`AWAITING RECEIPT` while a turn is active, rather than presenting zero as fact.

Quota balances must not be calculated from token consumption unless the
provider supplies an authoritative conversion and limit contract.

### 9A.3 Expandable usage investigation

Pressing `u` SHALL open a full-viewport usage investigation mode containing:

- per-turn input/output/cached/reasoning statistics where reported;
- model and effort per turn;
- provider execution duration and turn outcome;
- step and run totals;
- quota-window observations and reset history;
- retry and efficiency statistics derived from authoritative records;
- selectable usage receipts and linked evidence.

The user SHALL be able to navigate between turn, step, run and history views
without interrupting execution. Returning to the main dashboard must preserve
event selection and follow/pause state where feasible.

Token counters and quota observations must remain distinct data types.

## 9B. Dependable Live Execution Observability

### 9B.1 Activity fidelity

TOP SHALL expose actual recorded scheduler/provider/controller activity as
it becomes available, including:

- current phase, active provider, model and effort;
- recorded tool/command activity and output where observable;
- file operations and associated evidence;
- test invocations, progress and completed outcomes where observable;
- human gates, blockers, recovery and permitted next actions;
- qualification progress and evidence references;
- usage receipts and authority/transaction/runtime transitions.

TOP must not invent a command, test, tool event, provider thought, heartbeat
or progress percentage to make an otherwise quiet execution appear active.

Where incremental provider output is unavailable, it SHALL display the latest
authoritative milestone, its age and the explicit observability limitation.
Private model reasoning is not an event stream.

### 9B.2 Canonical event integrity

The R3D.2/R3D.3 native runtime work SHALL account for the dependencies TOP
needs, subject to their separately approved stage scopes:

- versioned canonical state snapshots and native event records;
- event identity, sequence/cursor, timestamp and source attribution;
- transaction, plan, step, controller and runtime-epoch association;
- restart/reconnect replay and gap detection;
- distinction between live, historical, provisional and final observations;
- explicit stale-authority and installed-successor rebind semantics;
- safe handling of bursty, delayed, duplicated and malformed observations;
- bounded in-memory event buffering with durable evidence references.

TOP SHALL consume these authoritative contracts without owning or replacing
their authority. Missing capabilities must be recorded as upstream gaps before
R3D.4 implementation, never supplied by a parallel TOP-only authority model.

### 9B.3 Operational lifecycle and freshness

TOP SHALL remain functional in RUNNING, WAITING, BLOCKED, HUMAN GATE,
QUALIFYING, RECOVERING, STOPPED, FAILED, COMPLETE, STALE and UNKNOWN
conditions.

It SHALL distinguish last observed activity from proven liveness.
Absence of events alone does not prove a provider has crashed.

A runtime-epoch or installed-successor change SHALL invalidate stale views
until the new authoritative source is established.

Paused-follow mode pauses display navigation only; it must never pause the
actual controller or scheduler.

Closing TOP, terminal disconnection or rendering failure must never stop or
mutate the development run.

### 9B.4 Full-screen information density

A sufficiently wide terminal SHALL use three substantial working columns:

- left: complete plan, current step, phase, checkpoint and qualification;
- centre: live execution/event stream and activity;
- right: model capacity, five-hour/weekly quotas and token statistics.

An always-visible authority strip SHALL include controller, transaction,
runtime epoch, gate, recovery, installed-product identity, source attribution
and legacy status.

Available vertical space SHALL support an event-detail pane, selected
evidence and keyboard help. Extra width and height must reveal useful
information instead of merely enlarging whitespace.

Responsive layouts SHALL preserve access to all panels through focus,
navigation and full-viewport detail modes. Exact wordmark constraints and
existing Stygnox semantic colours remain authoritative.

### 9B.5 Interactive, read-only operator controls

At minimum TOP SHALL support:

- keyboard focus and pane navigation;
- follow/pause, scrolling and event selection;
- searchable/filterable events and history;
- expanded event/usage/plan/authority details;
- evidence reference inspection and safe copying/export;
- visible key help and clean exit;
- terminal resize without losing important selection state.

Initial TOP release remains read-only for authority-changing operations.
No approval, retirement, recovery, grant or mutation may bypass native
controller preview/confirmation contracts.

Provider output and untrusted event text must be safely rendered without
terminal-control injection or exposing secrets from diagnostic data.

## 9C. Required Reliability Qualification

Qualification SHALL include real independent TOP and scheduler processes
against an installed Stygnox artifact, not only mocked presentation objects.

Hostile and lifecycle coverage SHALL prove:

- live events appear during a genuinely active provider/controller run;
- stopped, blocked and human-gate states remain inspectable;
- authoritative quota percentages and reset times are displayed accurately;
- absent or stale quota data is unmistakably labelled;
- cached input and retries cannot be double-counted;
- event replay, duplication, gaps and out-of-order delivery are handled;
- event bursts and long output do not exhaust terminal memory;
- malformed/untrusted output cannot corrupt the terminal;
- a controller rebind makes old authority visibly stale;
- reconnect/resume uses canonical event identity and epoch semantics;
- read-only operation performs no controller/transaction mutation;
- terminal resize, Ctrl-C, errors and normal quit restore terminal state;
- CLI, snapshot TUI and TOP agree on the same authoritative state.

The acceptance suite SHALL validate behavior while the scheduler is actively
running, after it stops normally, and when it is blocked awaiting an operator.

## 10. R3D.4 Acceptance Criteria Amendment

The existing R3D.4 acceptance criteria are extended as follows:

> Implement `stygnox top` as a native full-screen, continuously updating terminal operations console over the canonical Stygnox state/event model, providing plan/stage progress, live execution events, structured event detail, permanently visible authority/recovery health, timers, model/effort/provider information, and truthful usage/quota data, with no presentation-owned authority.

> `stygnox top`, `stygnox tui`, and human-oriented CLI output SHALL share a central Stygnox terminal theme and semantic colour model. The current Stygnox terminal palette and status meanings are authoritative.

> The exact six-line Stygnox terminal wordmark recorded in this programme amendment SHALL be used intact when terminal width permits. The renderer SHALL NOT truncate or approximate the wordmark.

> Full-screen `stygnox top` SHALL be read-only for authority-changing actions in its initial qualified release. Future interactive controller actions must use the same preview/confirmation contracts as native CLI operations.

> R3D.4 must prove CLI/TUI/top presentation parity over the same canonical state/event semantics and prove that presentation owns no authority.

> Model-capacity visibility SHALL include independently authoritative
five-hour and weekly remaining percentages, reset times and observation age
when supported, with explicit unavailable/stale states otherwise.

> Token accounting SHALL provide per-turn, per-step, per-run and historical
input/output/cached usage without double-counting receipts or cached tokens.

> The full-screen console SHALL make operationally meaningful use of available
terminal space, including persistent model/capacity statistics alongside
plan progress and live execution on suitable terminals.

> Hostile qualification SHALL prove real live execution, blocked/stopped
observability, event integrity, stale-authority handling, terminal safety
and non-interference with controller execution.


---

## 11. Programme Reconciliation Instructions

At the next formal programme reconciliation after R3D.1 is qualified, finalized, and committed:

1. Merge this decision into the R3D.4 section of `docs/programme/STYGNOX-ROADMAP.md`.
2. Expand the R3D.4 checklist in `docs/programme/PROGRESS.md` to include:
   - full-screen `stygnox top`;
   - exact wordmark contract;
   - central terminal theme;
   - semantic colour model;
   - live events;
   - plan/progress pane;
   - authority/health pane;
   - selected-event structured detail;
   - run/step/turn timers;
   - truthful provider usage/quota/reset presentation;
   - five-hour and weekly remaining-capacity percentages;
   - provider quota reset timestamps, countdowns and observation freshness;
   - per-turn, per-step, per-run and historical token accounting;
   - input/output/cached/reasoning-token distinctions;
   - deduplicated usage receipts and truthful missing-data treatment;
   - expandable usage investigation and keyboard navigation;
   - canonical event replay, epoch transitions and stale-source detection;
   - real running/stopped/blocked operational observability;
   - full-screen information density and responsive capacity panels;
   - live-process, terminal-safety and non-interference qualification;
   - responsive terminal layouts;
   - read-only initial authority boundary;
   - presentation parity tests.
3. Add a durable issue/finding to `docs/programme/ISSUES.md` recording the requirement and preventing regression into a snapshot-only or raw-JSON-only implementation.
4. Preserve this amendment as historical decision evidence or supersede it with the resulting committed programme-document revision.
5. Do not start R3D.2 until the R3D.1 programme reconciliation and versioning update has been committed.

---

## 12. Non-Goals

This amendment does NOT authorize:

- work on R3D.4 during R3D.1;
- Web UI work;
- Controller API v1 implementation;
- direct `.stygnox` file scraping as a separate authority model;
- resurrection of Ralph presentation/runtime code as live authority;
- weakening human gates;
- changing active R3D stage scope merely for dashboard work.

It records the R3D.4 requirement now so it cannot be lost while preserving the currently active stage boundary.
