# StygNox Agent Skill Routing

Use this document to choose project-local skills deliberately. Installed does not mean mandatory for every task: use the smallest relevant combination.

| Work type | Primary skill(s) | What they add |
|---|---|---|
| Repository exploration, unfamiliar code, dependency/change impact | `codemapper` | AST-based structure, symbols, callers/callees, test relationships and impact analysis |
| Large tool output, long test/build logs, broad search results, large JSON/source excerpts, context pressure | `headroom` | Reduces model-context cost while retaining reversible raw evidence; use only when the output is materially large |
| FastAPI endpoints, backend API behaviour, streaming/SSE | `fastapi` | Current FastAPI implementation patterns and streaming guidance |
| Provider/consumer API compatibility | `contract-testing-builder` | Contract tests and compatibility checks across boundaries |
| Test design or test review | `testing-anti-patterns` | Guards against mock-behaviour tests, implementation-detail tests and test-only production code |
| Browser E2E and realtime behaviour | `playwright-best-practices`, `webapp-testing` | Real-browser behavioural validation, realtime interaction and robust Playwright patterns |
| React component architecture | `vercel-composition-patterns` | Composition, explicit variants and avoidance of conditional/boolean-prop sprawl |
| React performance and implementation review | `vercel-react-best-practices` | Data fetching, rendering, bundle and re-render discipline |
| Frontend state ownership | `state-management` | Decides what belongs to local, shared, URL or authoritative server/controller state |
| Design-system architecture | `design-systems-frontend-architecture` | Reusable tokens, components, states and UI governance |
| New UI visual direction | `frontend-design`, `ui-ux-pro-max` | Product-grade visual design, hierarchy, interaction and responsive UX patterns |
| UI review and standards | `web-design-guidelines`, `impeccable` | Usability review, design critique and production finishing |
| Automated accessibility check | `accessibility-scan` | Single-page automated WCAG-oriented checks |
| Hands-on accessibility check | `accessibility-inspect` | Keyboard, focus, reflow and accessibility-tree assessment |
| Whole-product accessibility assessment | `accessibility-audit` | Broader WCAG 2.2 audit workflow |
| Accessibility regression check | `accessibility-diff` | Detects newly introduced accessibility problems |
| Accessibility remediation | `accessibility-fix` | Repairs confirmed accessibility findings and verifies them |
| Documentation | `doc-author` | Structured durable user/developer/operator documentation |
| Final completion/fix/readiness claim | `verification-before-completion` | Requires fresh evidence before success claims |

## Common combinations

### Backend/API change

Use `codemapper` when impact is unclear, then `fastapi` where FastAPI behaviour is involved. Add `contract-testing-builder` when a provider/consumer boundary changes. Finish with `verification-before-completion`.

### Test repair or regression coverage

Use `testing-anti-patterns` before designing the regression. Use the narrowest test tool appropriate to the behaviour. Finish with `verification-before-completion`.

### Context and token efficiency

Use `headroom` when a tool result is materially large (roughly over 200 tokens) and a compressed representation is sufficient for the next reasoning step.

Prefer:
- `LogCompressor` for large test/build logs.
- `SearchCompressor` for large grep/ripgrep output.
- `SmartCrusher` for large JSON/tool responses.
- `CodeCompressor` for large source excerpts.
- targeted symbol/range reads before compression where that avoids generating the large output at all.

Raw evidence remains authoritative. Preserve the original on disk and compress only the representation injected into model context.

Do not use compression as a substitute for:
- exact Git diffs or hashes;
- controller state or provenance;
- byte-exact evidence;
- errors, failures, stack traces, or other material diagnostic evidence.

Headroom may compress **evidence presentation**, never **evidence authority**.

### Web UI vNext implementation

Start with authoritative controller/API state. Use `state-management`, then `design-systems-frontend-architecture` and `vercel-composition-patterns`. Add `frontend-design` or `ui-ux-pro-max` for visual/interaction design and `vercel-react-best-practices` during implementation.

Use `playwright-best-practices` plus `webapp-testing` for actual browser behaviour. Use the AccessLint skills for accessibility. Use `web-design-guidelines` and `impeccable` for review and finishing only after functional correctness is established.

### UI finishing

Use `impeccable` deliberately:

- critique before final design acceptance;
- polish after functional behaviour is proven;
- delight only after correctness, usability and accessibility are established.

Do not use visual polish to mask incomplete or incorrect behaviour.

## Skill discovery

To see the installed project skills:

```bash
npx skills@1.7.0 list
```

Or inspect the canonical project copies:

```bash
find .agents/skills -maxdepth 2 -name SKILL.md -print | sort
```

For any selected skill, read its repository copy before use:

```bash
cat .agents/skills/<skill>/SKILL.md
```

The installed set is pinned/recorded by `skills-lock.json`.
