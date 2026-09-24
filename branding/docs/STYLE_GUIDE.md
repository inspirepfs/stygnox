# StygNox Development Style Guide v1.0

## 1. Brand direction

StygNox is a **dark-first technical product identity**: controlled, precise, autonomous and evidence-led. The visual language should feel like an advanced operational platform rather than a gaming UI.

The selected brand mark provides the core vocabulary:

- near-black/navy surfaces;
- metallic silver-white typography;
- violet/purple energy accents;
- angular geometry;
- subtle terminal language;
- restrained glow;
- clear hierarchy and strong whitespace.

### Design rule

**Use the purple as energy, not wallpaper.** Most of the interface should remain dark-neutral. Purple highlights state, focus, important controls and brand moments.

---

## 2. Product principles

1. **Evidence before decoration** — operational data, state, provenance and actions must remain more prominent than visual effects.
2. **Dense, not cramped** — StygNox can support technical density, but spacing and grouping must make scanning easy.
3. **Dark-first** — the primary UI is designed for dark mode. Light assets exist for documents and exceptional contexts.
4. **Controlled glow** — use glow only around the brand, active focus, selected states or deliberate hero moments.
5. **Operator confidence** — dangerous, irreversible or authority-changing actions must never rely on colour alone.
6. **Terminal credibility** — monospace styling is reserved for code, commands, IDs, evidence, logs and machine state.
7. **Responsive parity** — mobile may reflow and collapse, but it must not hide critical status or authority information.

---

## 3. Colour system

| Token | Value | Purpose |
|---|---:|---|
| `--sn-bg-950` | `#05090F` | page background |
| `--sn-bg-900` | `#080D16` | alternate page band |
| `--sn-surface` | `#0D1320` | panels |
| `--sn-surface-raised` | `#111A2A` | cards / overlays |
| `--sn-border` | `#26324A` | normal borders |
| `--sn-text` | `#F2F4F8` | primary text |
| `--sn-text-secondary` | `#D6DCE8` | secondary high-emphasis text |
| `--sn-text-muted` | `#9AA8BE` | helper text |
| `--sn-purple` | `#925EED` | primary brand/control accent |
| `--sn-purple-bright` | `#AF76F0` | hover/focus/highlights |
| `--sn-purple-soft` | `#D5A1FA` | high-contrast accent text |
| `--sn-violet` | `#6945EA` | gradients / deeper accent |
| `--sn-signal-blue` | `#7EA8FF` | sparse informational contrast |

Status colours:

- Success `#55D6A5`
- Warning `#F6C76A`
- Danger `#FF6B88`
- Info `#7EA8FF`

The core text and purple tokens meet WCAG AA contrast against the primary near-black background for normal UI usage. Never use purple text on light surfaces without rechecking contrast.

---

## 4. Typography

Recommended stack:

- **Display / headings:** Space Grotesk, fallback Segoe UI/system sans.
- **UI / body:** Inter, fallback Segoe UI/system sans.
- **Technical / code:** JetBrains Mono, Cascadia Code, Consolas.

Rules:

- Headings: compact, slightly negative tracking.
- Body text: 1.55–1.75 line height.
- Avoid all-caps except for kickers, small state labels and terminal metadata.
- Do not use faux sci-fi fonts for body or controls.
- IDs, hashes, commands, evidence paths, plan IDs and log output use monospace.

---

## 5. Layout

Maximum content width: **1180px**.

Primary spacing scale: 4 / 8 / 12 / 16 / 20 / 24 / 32 / 40 / 48 / 64 / 80px.

Breakpoints:

- `sm`: 640px
- `md`: 768px
- `lg`: 1024px
- `xl`: 1280px
- `xxl`: 1536px

Desktop defaults to 12-column thinking. Mobile should collapse to one major content column unless a two-column row is clearly usable.

---

## 6. Surfaces and borders

Panels are near-black/navy with subtle depth.

Use:
- 1px borders;
- 10–16px radii;
- soft black shadows;
- optional low-opacity purple edge glow for focus or featured content.

Avoid:
- heavy glassmorphism everywhere;
- continuous neon outlines;
- more than one dominant glowing element in a viewport;
- bright purple page backgrounds.

---

## 7. Buttons and interaction

Primary actions use a purple-to-violet gradient. Secondary actions remain dark and bordered.

Minimum interactive target: **44px** high.

Every interactive element requires:
- hover state;
- keyboard focus state;
- disabled state where applicable;
- textual/icon cue for critical state.

Destructive actions use the danger colour and explicit wording. Do not represent destructive authority with purple.

---

## 8. Cards

Cards are functional groups, not decorative tiles.

Recommended anatomy:

1. optional kicker or state;
2. short title;
3. concise explanation or metric;
4. relevant evidence or metadata;
5. single primary action or link.

Do not nest more than two card levels.

---

## 9. Terminal / evidence treatment

Use the terminal treatment for:

- live output;
- commands;
- logs;
- hashes;
- evidence streams;
- plan or run state;
- generated ASCII identity.

Use a true black-ish background and monospace text with sparse purple accents. Never make whole paragraphs purple.

---

## 10. Logo use

Primary dark-mode contexts:
- full-colour logo;
- full-colour icon;
- white variation for small/simple overlays.

Purple monochrome is a secondary graphic treatment, not the default product header.

Clear space around a logo should be at least the height of the capital `N` in `Nox`.

Never:
- recolour the eyes independently;
- stretch the mark;
- add a different glow colour;
- place the full-colour logo on a busy purple background;
- use the detailed emblem below a size where facial geometry is legible.

---

## 11. Iconography

UI icons should be:
- simple outline or restrained duotone;
- 1.5–2px apparent stroke at 24px;
- geometrically clean;
- neutral by default;
- purple only for selected/active states.

The StygNox animal mark is a brand emblem, not a generic UI icon.

---

## 12. Motion

Default interaction timing: 120–180ms.

Hero/large transitions: up to 320ms.

Motion should communicate:
- state change;
- successful transition;
- panel appearance;
- progress or execution.

Avoid looping ambient animation except a very subtle brand glow or explicit live-state indicator.

Support `prefers-reduced-motion`.

---

## 13. Accessibility

Required:
- keyboard-visible focus;
- semantic headings;
- labels for form controls;
- non-colour state indicators;
- at least WCAG AA for body text;
- no flashing/glowing animation;
- error text adjacent to the failing control.

Technical density must not override readability.

---

## 14. Homepage reference

The included `homepage.html` is the reference implementation.

### Homepage information architecture

1. Sticky product navigation
2. Hero: name + positioning + two actions
3. Operational trust/status strip
4. Four-stage lifecycle: Plan / Execute / Evidence / Evolve
5. Core capability cards
6. Terminal/evidence preview
7. Governance and human-control section
8. Closing CTA
9. Minimal technical footer

### Hero language

**Autonomous development with evidence, control and recovery built in.**

Supporting copy should explain that StygNox coordinates a bounded development loop, captures evidence, stops for human authority when required and makes recovery deterministic.

This is stronger than generic “AI coding platform” language and matches the product's actual differentiators.

---

## 15. Development assets

- `design-tokens.json` — portable token source
- `css/design-tokens.css` — CSS custom properties
- `css/components.css` — baseline component styling
- `style-guide.html` — visual style reference
- `homepage.html` — reference product homepage
- `assets/brand/` — selected identity assets
- `assets/ascii/` — plain and ANSI-coloured terminal identity
