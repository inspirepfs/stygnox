#!/usr/bin/env bash
set -euo pipefail

# StygNox project-local Agent Skills bootstrap.
# Usage:
#   ./scripts/setup-agent-skills.sh
#   ./scripts/setup-agent-skills.sh /path/to/stygnox
#
# Override the CLI version if needed:
#   SKILLS_CLI_VERSION=1.7.0 ./scripts/setup-agent-skills.sh

PROJECT_ROOT="${1:-$(pwd)}"
SKILLS_CLI_VERSION="${SKILLS_CLI_VERSION:-1.7.0}"

cd "$PROJECT_ROOT"

if ! command -v git >/dev/null 2>&1; then
  echo "ERROR: git is required." >&2
  exit 1
fi

if ! command -v npx >/dev/null 2>&1; then
  echo "ERROR: npx is required. Install a current Node.js/npm toolchain first." >&2
  exit 1
fi

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "ERROR: $PROJECT_ROOT is not inside a Git repository." >&2
  exit 1
fi

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

echo "StygNox skills bootstrap"
echo "Repository : $REPO_ROOT"
echo "CLI        : skills@$SKILLS_CLI_VERSION"
echo

# Keep installation telemetry out of the project bootstrap by default.
export DISABLE_TELEMETRY="${DISABLE_TELEMETRY:-1}"

INSTALL_FAILURES=()

skills_add() {
  local source="$1"
  shift
  local args=()
  local skill
  for skill in "$@"; do
    args+=(--skill "$skill")
  done

  echo
  echo "==> ${source}: $*"
  if ! npx --yes "skills@${SKILLS_CLI_VERSION}" add "$source" "${args[@]}" --yes; then
    echo "WARN: install command failed for ${source}: $*" >&2
    INSTALL_FAILURES+=("${source}:$*")
  fi
}

# Codebase intelligence / impact analysis
# Repo-wide discovery does not reach this deeply nested skill with skills@1.7.0,
# so install from the exact GitHub subtree.
skills_add https://github.com/zenobi-us/dotfiles/tree/main/files/devtools/agent/bundles/developer/skills/devtools/codemapper \
  codemapper

# Design and real-browser validation
skills_add https://github.com/anthropics/skills \
  frontend-design \
  webapp-testing

# Durable design-system architecture
skills_add https://github.com/hueyexe/frontend-agent-skills \
  design-systems-frontend-architecture

# React architecture, performance, and UI review
skills_add https://github.com/vercel-labs/agent-skills \
  web-design-guidelines \
  vercel-composition-patterns \
  vercel-react-best-practices

# Broader UX/design intelligence
skills_add https://github.com/nextlevelbuilder/ui-ux-pro-max-skill \
  ui-ux-pro-max

# Frontend state ownership
skills_add https://github.com/akillness/jeo-skills \
  state-management

# Backend/API/streaming guidance
skills_add https://github.com/fastapi/fastapi \
  fastapi

# Behavioural and realtime browser testing
skills_add https://github.com/currents-dev/playwright-best-practices-skill \
  playwright-best-practices

# Test-quality anti-pattern guard
# The original sammcj catalogue entry is currently out of sync with its
# default branch. Use a live maintained copy with Python/pytest and TS/Jest.
skills_add https://github.com/bobmatnyc/claude-mpm-skills \
  testing-anti-patterns

# API/provider-consumer contract testing
skills_add https://github.com/patricio0312rev/skills \
  contract-testing-builder

# Accessibility quality suite (current AccessLint skill names)
skills_add https://github.com/accesslint/skills \
  accessibility-scan \
  accessibility-inspect \
  accessibility-audit \
  accessibility-diff \
  accessibility-fix

# UX critique and later-stage finishing
# Impeccable v4 consolidates critique/polish/delight into one skill.
skills_add https://github.com/pbakaus/impeccable \
  impeccable

# Durable documentation
skills_add https://github.com/mintlify/docs \
  doc-author

# Evidence-before-completion gate
skills_add https://github.com/obra/superpowers \
  verification-before-completion

echo
echo "==> Validating expected project skills"

EXPECTED_SKILLS=(
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

missing=0
for skill in "${EXPECTED_SKILLS[@]}"; do
  if [[ -f ".agents/skills/${skill}/SKILL.md" ]]; then
    printf '  PASS  %s\n' "$skill"
  else
    printf '  FAIL  %s (missing .agents/skills/%s/SKILL.md)\n' "$skill" "$skill"
    missing=1
  fi
done

if [[ ! -f skills-lock.json ]]; then
  echo "  FAIL  skills-lock.json was not generated"
  missing=1
else
  echo "  PASS  skills-lock.json"
fi

if [[ "${#INSTALL_FAILURES[@]}" -gt 0 ]]; then
  echo
  echo "==> Upstream install failures"
  for failure in "${INSTALL_FAILURES[@]}"; do
    echo "  WARN  ${failure}"
  done
fi

echo
echo "==> Installed skill inventory"
npx --yes "skills@${SKILLS_CLI_VERSION}" list || true

echo
echo "==> Git status"
git status --short -- .agents skills-lock.json 2>/dev/null || true

if [[ "$missing" -ne 0 ]]; then
  echo
  echo "ERROR: one or more expected skills failed validation." >&2
  exit 1
fi

cat <<'EOF'

Skills installation validated.

Recommended files to commit:
  .agents/skills/
  skills-lock.json
  docs/agent-skills.md

Do not treat an installed skill as automatic authority to modify the repo.
Its use should still be explicitly authorised by the active StygNox work order.
EOF
