# StygNox Agent Operating Instructions

This file is the repository-level entry point for coding agents and automated development tools.

## Start here

Before planning or changing the repository, establish the current task scope and read the relevant project guidance.

The StygNox project-local skill catalogue is installed under:

- `.agents/skills/`
- `skills-lock.json`

The human-readable catalogue and routing guidance are:

- `docs/agent-skills.md`
- `docs/agent-skill-routing.md`

Treat these documents as the source of truth for which specialist skills are available and when they should be used.

## Skills are part of the engineering workflow

Before specialised work:

1. Identify the type of work being performed.
2. Consult `docs/agent-skill-routing.md`.
3. Select the smallest relevant set of installed skills.
4. Read each selected `.agents/skills/<skill>/SKILL.md` before applying it.
5. Follow the skill guidance where it improves the work.
6. Do not load unrelated skills simply because they are installed.

Do not rely on remembered skill names or remembered skill contents when the repository copy is available.

## Authority boundary

Installed skills provide specialist methodology and guidance. They do not grant additional authority.

A skill must not:

- broaden the active work-order scope;
- override operator instructions or human approval gates;
- weaken test or verification requirements;
- change lifecycle, recovery, authority, or safety semantics without explicit scope;
- modify tests when the active work order prohibits test mutation;
- turn an optional recommendation into an architectural requirement without evidence.

The active work order, repository policy, controller authority model, and explicit operator instructions take precedence over skill guidance.

## Evidence-first engineering

StygNox uses an evidence-first workflow.

For unfamiliar, high-impact, or cross-cutting code, consider `codemapper` before editing. Use it for structure, symbol relationships, callers/callees, test relationships, and impact analysis. Use normal text search when the task is textual rather than structural.

For tests, use `testing-anti-patterns` to avoid tests that merely reproduce implementation details, verify mocks instead of behaviour, or introduce test-only production behaviour.

For API/provider-consumer boundaries, consider `contract-testing-builder`.

For browser and UI behaviour, prefer behavioural validation with the relevant Playwright and web-app testing skills rather than tests that only assert static markup or hard-coded values.

## Frontend and Web UI work

The presence of frontend skills is not permission to revive or incrementally repair retired legacy Web UI code.

When a Web UI work order is explicitly authorised, use the routing document to select the relevant state-management, React, design-system, frontend-design, accessibility, browser-testing, and UX-review skills.

UI state must reflect authoritative StygNox/controller state rather than duplicated or invented frontend state.

Controls and options should appear only when they are valid for the current state and authority context.

## Accessibility

Accessibility is a first-class quality requirement for user-facing Web UI work.

Use the AccessLint skill family according to task scope:

- `accessibility-scan` for automated single-page checks;
- `accessibility-inspect` for hands-on keyboard, focus, reflow, and accessibility-tree checks;
- `accessibility-audit` for whole-product/milestone assessment;
- `accessibility-diff` for accessibility regression checks;
- `accessibility-fix` for remediation of confirmed findings.

Automated checks do not replace human-required accessibility judgement.

## Documentation

Use `doc-author` when substantial user, operator, API, architecture, or developer documentation is part of the authorised work.

Keep durable project knowledge in the repository rather than only in chat or agent state.

## Completion claims

Before stating that implementation work is complete, fixed, passing, ready, or successfully validated:

1. Read and apply `.agents/skills/verification-before-completion/SKILL.md`.
2. Run the authoritative verification appropriate to the change.
3. Check the actual output.
4. Compare the result with the work order and acceptance criteria.
5. Report remaining uncertainty or failures explicitly.

Passing a subset of tests is not sufficient evidence of completion when additional acceptance criteria exist.

## Default operating sequence

Use this sequence unless the active work order defines a stricter one:

`scope -> inspect evidence -> understand authority -> select relevant skills -> implement -> test behaviour -> verify evidence -> claim completion`

Do not let a skill drive repository changes before scope, authority, and evidence are understood.
