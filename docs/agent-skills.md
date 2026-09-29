# StygNox Agent Skills Catalogue

This catalogue records the project-local skills intentionally installed for future StygNox development.

## Authority rule

**Installed does not mean automatically authorised.**

A skill may be present in `.agents/skills/` but should only influence repository changes when the active StygNox/Ralph work order explicitly permits that class of work. This preserves the evidence-first extraction/parity discipline while making later capabilities immediately available.

## Installed skills

| Skill | Source | Intended use | Normal activation point |
|---|---|---|---|
| `codemapper` | `zenobi-us/dotfiles` exact skill subtree (engine originates from CodeMapper) | AST-based codebase mapping, symbol relationships, callers/callees and impact analysis | Repository exploration, audits and change-impact analysis |
| `headroom` | `roman-ryzenadvanced/headroom-skill` | Context/token reduction for large logs, search output, JSON/tool results and source excerpts while retaining reversible raw evidence | Large-output handling and token-efficiency work |
| `frontend-design` | `anthropics/skills` | Product-grade visual/frontend design | Web UI vNext design |
| `webapp-testing` | `anthropics/skills` | Real-browser application validation | Web UI behavioural validation |
| `design-systems-frontend-architecture` | `hueyexe/frontend-agent-skills` | Design tokens, components, states and governance | Web UI architecture |
| `web-design-guidelines` | `vercel-labs/agent-skills` | UI/UX/accessibility review | UI review gates |
| `vercel-composition-patterns` | `vercel-labs/agent-skills` | Scalable React composition | React implementation |
| `vercel-react-best-practices` | `vercel-labs/agent-skills` | React performance/architecture | React implementation and review |
| `ui-ux-pro-max` | `nextlevelbuilder/ui-ux-pro-max-skill` | UI/UX patterns and design intelligence | UX planning and implementation |
| `state-management` | `akillness/jeo-skills` | State ownership decisions | UI state/data-contract design |
| `fastapi` | `fastapi/fastapi` | FastAPI patterns including streaming/SSE | API/live-state work |
| `playwright-best-practices` | `currents-dev/playwright-best-practices-skill` | E2E, realtime and browser testing | Web UI test rebuild |
| `testing-anti-patterns` | `bobmatnyc/claude-mpm-skills` | Guards against mock-behaviour tests, test-only production code and other misleading test patterns; includes Python/pytest and TypeScript/Jest guidance | Test design and regression-quality reviews |
| `contract-testing-builder` | `patricio0312rev/skills` | Provider/consumer API contract testing and compatibility checks | Controller/API/Web UI boundary stability |
| `accessibility-scan` | `accesslint/skills` | Automated single-page WCAG checks | UI implementation and CI checks |
| `accessibility-inspect` | `accesslint/skills` | Hands-on keyboard/focus/reflow/accessibility-tree assessment | Manual accessibility validation |
| `accessibility-audit` | `accesslint/skills` | Whole-product WCAG 2.2 audit workflow | Accessibility release gate |
| `accessibility-diff` | `accesslint/skills` | Accessibility regression comparison | PR/change regression checks |
| `accessibility-fix` | `accesslint/skills` | Remediation and verification of accessibility findings | Fixing confirmed accessibility defects |
| `impeccable` | `pbakaus/impeccable` | Consolidated v4 frontend design/review skill; includes critique, polish, delight, audit and other UI commands | Web UI design, review and finishing |
| `doc-author` | `mintlify/docs` | Maintainable project/user documentation | Throughout stable implementation |
| `verification-before-completion` | `obra/superpowers` | Requires fresh verification evidence before claiming work complete, fixed or passing | Final gate for implementation, repair and release work |

## Suggested invocation order for Web UI vNext

1. `codemapper` for repository mapping and change-impact analysis where useful.
2. Authority/API contract and controller state.
3. `state-management`.
4. `contract-testing-builder` where controller/API consumer boundaries are introduced or changed.
5. `design-systems-frontend-architecture`.
6. `vercel-composition-patterns`.
7. `frontend-design` / `ui-ux-pro-max`.
8. `vercel-react-best-practices`.
9. `fastapi` where API/streaming work is in scope.
10. `testing-anti-patterns` while designing or reviewing tests.
11. `playwright-best-practices` + `webapp-testing`.
12. `accessibility-scan` during implementation; `accessibility-inspect` for hands-on checks.
13. `accessibility-audit` for milestone/release conformance; `accessibility-diff` for regression checks; `accessibility-fix` for confirmed remediation work.
14. `web-design-guidelines`.
15. `impeccable critique` for milestone UX review.
16. `impeccable polish` after functional closure.
17. `impeccable delight` only after correctness and usability are proven.
18. `doc-author` continuously where contracts and behaviour are stable.
19. `verification-before-completion` before any final success/completion claim.

## Maintenance

Project skills are intentionally project-local. Keep `skills-lock.json` with the repository so the skill set is auditable and reproducible.

The bootstrap currently contains **22 explicitly selected skills**. The additional engineering-quality and efficiency skills (`codemapper`, `testing-anti-patterns`, `contract-testing-builder`, `verification-before-completion`, and `headroom`) are intentionally project-local and auditable.


Before updating a third-party skill, review the upstream delta and security audit status. Skill updates are dependency changes and should not silently alter StygNox development behaviour.

### Upstream source corrections

- `codemapper`: `skills@1.7.0` does not discover the deeply nested skill when pointed at the `zenobi-us/dotfiles` repository root, so the bootstrap installs from the exact GitHub subtree containing `SKILL.md`.
- AccessLint: the old `audit` catalogue name has been replaced upstream by a more explicit suite: `accessibility-scan`, `accessibility-inspect`, `accessibility-audit`, `accessibility-diff`, and `accessibility-fix`.
- Impeccable: current v4 consolidates the old standalone `critique`, `polish`, and `delight` skills into the single `impeccable` skill. Those behaviours are now commands/modes of that skill.
- `testing-anti-patterns`: the original `sammcj/agentic-coding` catalogue entry is out of sync with its current default branch, so StygNox uses the live maintained copy from `bobmatnyc/claude-mpm-skills`.

These substitutions track the current upstream skill layouts rather than stale catalogue aliases.
