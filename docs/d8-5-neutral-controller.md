# D8.5 neutral authority, controller, and execution policy

D8.5 moves the installed Stygnox product from a safe lifecycle shell to a
neutral, installed controller authority. It does not adopt the legacy Ralph or
ZEN controller as product identity, and it does not make a host adapter the
default.

## Boundary

D8.5 owns:

- the neutral installed Stygnox profile and controller identity;
- one tracked, atomic execution-policy surface;
- reviewed provider/model/effort selection;
- controller activation/deactivation bound to an active D8.3 transaction;
- exact run preview and reconfirmation semantics;
- the installed Codex provider adapter; and
- neutral runtime evidence under `.stygnox`.

D8.5 does not own Web/TUI presentation, carry-forward UX, release packaging, or
removal of source-tree compatibility code. Those remain D8.6/D8.7 work.

## Neutral installed profile

The installed profile is fixed by the product rather than inherited from the
adopted project:

- identity: `Stygnox`
- profile: `stygnox-default`
- command: `stygnox`
- controller command: `stygnox controller`
- runtime root: `.stygnox`
- tracked configuration: `stygnox.toml`
- tracked policy: `stygnox.policy.md`
- artifact namespace: `stygnox`
- completion commit prefix: `chore(stygnox):`
- host adapter: none by default

Use:

```bash
stygnox profile show --project-root /path/to/project
```

The installed profile cannot be replaced by target-project profile fields.
Legacy source-tree Ralph entrypoints remain compatibility/development surfaces,
not installed controller fallbacks.

## Atomic execution policy

D8.5 consolidates the execution settings that were previously fragmented
between model policy, efficiency policy, and run flags. The tracked execution
policy contains:

- provider
- model
- effort
- efficiency mode
- reserve percentage
- wait-for-limits
- usage polling interval
- maximum loops

Neutral defaults intentionally select no provider, model, or effort. The other
defaults are `RELAXED`, 5% reserve, wait-for-limits enabled, 60-second usage
polling, and one maximum loop.

Inspect the current policy:

```bash
stygnox execution-policy show --project-root /path/to/project
```

Preview a reviewed provider/model/effort override before changing tracked
configuration:

```bash
stygnox execution-policy preview \
  --project-root /path/to/project \
  --operator OPERATOR \
  --provider codex \
  --model gpt-5.6-terra \
  --effort high \
  --reviewer REVIEWER
```

`set` requires the exact preview digest and explicit confirmation. Any change to
provider, model, effort, efficiency, reserve, wait behavior, polling, or loop
count changes the preview digest and invalidates the previous confirmation.
Non-neutral provider/model/effort selection requires a named reviewer.

Once transaction authority has begun, execution policy is locked. D8.5 does not
permit a model, effort, provider, or efficiency policy to change underneath an
active transaction.

Reset follows the same preview/reconfirmation rule and restores the neutral
policy rather than silently selecting an implementation default.

## Controller activation

D8.2 handoff still records controller execution as disabled. This preserves the
meaning of the D8.2-D8.4 qualification gates. D8.5 adds a separate controller
activation gate.

Activation requires:

1. confirmed adoption;
2. an ACTIVE D8.3 transaction;
3. the same operator identity;
4. the exact transaction authority baseline;
5. the installed neutral Stygnox profile; and
6. a valid reviewed execution policy when provider/model/effort are selected.

Activate with:

```bash
stygnox controller activate \
  --project-root /path/to/project \
  --operator OPERATOR \
  --confirm ACTIVATE
```

Activation can succeed under neutral provider/model/effort settings, but provider
execution remains unavailable. This deliberately separates controller authority
from permission to dispatch a model.

Use `stygnox controller status` to inspect the active controller state.

## Run preview and provider execution

A provider turn is two-phase:

```bash
stygnox controller run-preview \
  --project-root /path/to/project \
  --operator OPERATOR \
  --objective 'bounded objective' \
  --repository-authority read-only
```

Then run with the exact returned preview digest:

```bash
stygnox controller run \
  --project-root /path/to/project \
  --operator OPERATOR \
  --objective 'bounded objective' \
  --repository-authority read-only \
  --preview PREVIEW_SHA256 \
  --confirm RUN
```

The preview binds the objective, repository authority, provider, model, effort,
configuration, reviewer evidence, and controller/transaction authority. A stale
or changed preview is refused.

The D8.5 built-in installed provider adapter is `codex`. Unsupported providers
fail closed. The adapter invokes the selected model and effort explicitly and
uses the requested repository sandbox authority. D8.5 restricts controller
execution to one loop. Multi-loop scheduling and richer orchestration are not
introduced by this stage.

A read-only turn must not alter the project baseline. A write-authorized turn
may alter it, but the result is explicitly marked `qualification-required`;
D8.5 does not silently treat a changed worktree as accepted completion.

## Compatibility

D8.5 keeps D8.1-D8.4 semantics intact:

- D8.1 still proves installed product identity and source/target isolation.
- D8.2 handoff still starts with controller execution disabled.
- D8.3 remains the transaction/recovery authority and dirty restoration layer.
- D8.4 remains the migration, upgrade, support, and uninstall lifecycle layer.
- `0.1.0.dev5` accepts package-only upgrade from `0.1.0.dev4` in addition to
  the earlier development package versions.

The D8.4 support record remains a D8.4 lifecycle statement and therefore still
reports controller execution disabled for that stage. The D8.5 controller state
is the authoritative record for current controller activation.

## Qualification

Run:

```bash
python3 scripts/qualify_d8_5_controller.py
```

The qualifier builds and installs the wheel into a fresh virtual environment and
uses the installed `stygnox` executable. It exercises new/unborn, clean, and
dirty Git fixtures, hostile Ralph decoys, reviewed and unreviewed execution
policy, stale confirmation refusal, controller activation, neutral provider
refusal, atomic policy set/reset, and a fake installed Codex provider binary.

The fake provider records its exact invocation so qualification can prove model,
effort, and sandbox selection without consuming a live model turn.

## D8.5 release gate

D8.5 is qualified only when all of the following are true:

- installed profile/controller/runtime identity is neutral Stygnox;
- no target-local or source-tree Ralph controller is used as fallback;
- neutral policy selects no provider/model/effort;
- a non-neutral override is reviewer-bound before handoff/authority;
- changing an override invalidates prior confirmation;
- controller activation is bound to active D8.3 transaction authority;
- neutral policy refuses provider execution;
- the installed provider adapter uses the reviewed model/effort exactly;
- clean and dirty operator material remains preserved;
- execution-policy set/reset is atomic and reconfirmed;
- D8.1-D8.4 installed-artifact qualifications remain green; and
- the full regression population remains green.

Web/TUI presentation is intentionally outside this boundary and begins only in
D8.6 using the approved Stygnox branding and CSS design assets.
