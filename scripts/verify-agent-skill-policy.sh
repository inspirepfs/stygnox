#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
cd "$ROOT"

required_files=(
  "AGENTS.md"
  "docs/agent-skills.md"
  "docs/agent-skill-routing.md"
  ".github/copilot-instructions.md"
  "CLAUDE.md"
  "GEMINI.md"
  ".cursor/rules/stygnox-skills.mdc"
  "skills-lock.json"
)

required_skills=(
  codemapper
  frontend-design
  webapp-testing
  design-systems-frontend-architecture
  web-design-guidelines
  vercel-composition-patterns
  vercel-react-best-practices
  ui-ux-pro-max
  state-management
  fastapi
  playwright-best-practices
  testing-anti-patterns
  contract-testing-builder
  accessibility-scan
  accessibility-inspect
  accessibility-audit
  accessibility-diff
  accessibility-fix
  impeccable
  doc-author
  verification-before-completion
)

fail=0

echo "==> Agent policy files"
for f in "${required_files[@]}"; do
  if [[ -f "$f" ]]; then
    printf '  PASS  %s\n' "$f"
  else
    printf '  FAIL  %s\n' "$f"
    fail=1
  fi
done

echo
echo "==> Installed project skills"
for s in "${required_skills[@]}"; do
  if [[ -f ".agents/skills/$s/SKILL.md" ]]; then
    printf '  PASS  %s\n' "$s"
  else
    printf '  FAIL  %s\n' "$s"
    fail=1
  fi
done

echo
if [[ "$fail" -eq 0 ]]; then
  echo "PASS: StygNox agent policy and all expected skills are present."
else
  echo "FAIL: StygNox agent policy/skill validation found missing items." >&2
  exit 1
fi
