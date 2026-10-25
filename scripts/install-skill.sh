#!/usr/bin/env bash
# Installs the sprint-review-progress skill for Claude Code (copies it to ~/.claude/skills).
# Also copies this repo's .env to ~/.sprint-review.env when that file does not exist yet,
# so the installed skill can find its Jira settings from any folder.
#
#   ./scripts/install-skill.sh          install
#   ./scripts/install-skill.sh --force  overwrite an existing install
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source_dir="$repo/skills/sprint-review-progress"
target="$HOME/.claude/skills/sprint-review-progress"

if [[ -e "$target" && "${1:-}" != "--force" ]]; then
  echo "Already installed at $target. Run with --force to overwrite." >&2
  exit 1
fi
mkdir -p "$(dirname "$target")"
rm -rf "$target"
cp -R "$source_dir" "$target"
echo "Skill installed: $target"

env_dst="$HOME/.sprint-review.env"
if [[ -f "$repo/.env" && ! -f "$env_dst" ]]; then
  cp "$repo/.env" "$env_dst"
  chmod 600 "$env_dst"
  echo "Settings copied to $env_dst"
elif [[ ! -f "$env_dst" ]]; then
  echo "No settings yet. Copy .env.example to $env_dst and fill it in." >&2
fi
echo "Check it:  python \"$target/scripts/sprint_progress.py\" --check"
