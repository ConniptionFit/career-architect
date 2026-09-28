#!/usr/bin/env bash
# LOCAL MODE installer: one person, files on their own machine, no Obot. (For a group, see docs/OPERATIONS.md.)
# Installs the jobs skill (invoke it with /jobs) and sets up Reactive Resume access. Safe to re-run.
#
#   bash setup.sh                # asks for the API key only if none is stored yet
#   bash setup.sh --rekey        # replace the stored key
#   bash setup.sh --yes          # replace an existing, different installed skill without asking
#
# The installed skill is the whole jobs/ folder, hosted-mode front page included: tell it you are working locally
# (see jobs/references/local-mode.md). The data folder is $CAREER_DATA, default ~/Documents/Career Architect.
#
# It never touches your profile.md or facts.md (beyond filling an empty rr_master), and the key is
# read with echo off, written to ~/.config/career/rr.env (mode 600), and never printed.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS="${CAREER_SKILLS_DIR:-$HOME/.claude/skills}"
SRC="$HERE/jobs"
DEST="$SKILLS/jobs"
CONF="$HOME/.config/career/rr.env"
CAREER="$DEST/scripts/career.py"

command -v uv >/dev/null || { echo "uv is required (brew install uv)" >&2; exit 1; }
[ -f "$SRC/SKILL.md" ] || { echo "cannot find the skill source at $SRC" >&2; exit 1; }
[ "$(basename "$DEST")" = "jobs" ] || { echo "refusing to sync into $DEST" >&2; exit 1; }

# 1. skill: mirror the source into the personal skills folder Claude Code loads
YES=0; for a in "$@"; do [ "$a" = "--yes" ] && YES=1; done
if [ -d "$DEST" ] && [ "$YES" = 0 ] && ! diff -rq -x '__pycache__' -x '*.pyc' "$SRC" "$DEST" >/dev/null 2>&1; then
  echo "An installed skill already exists at $DEST and differs from this repository:" >&2
  diff -rq -x '__pycache__' -x '*.pyc' "$SRC" "$DEST" | head -20 >&2 || true
  echo "Installing replaces it (files only there are deleted). Re-run with --yes to proceed; keep a copy first if it has changes you want." >&2
  exit 1
fi
mkdir -p "$(dirname "$DEST")"
rsync -a --delete --exclude '__pycache__' --exclude '*.pyc' "$SRC/" "$DEST/"
echo "skill    installed at $DEST"

# the same skill used to be installed as career-architect; drop that copy (only if it is ours) so /jobs is the one entry
LEGACY="$SKILLS/career-architect"
if [ -f "$LEGACY/scripts/career.py" ] && grep -q "Deterministic helpers" "$LEGACY/scripts/career.py"; then
  rm -rf "$LEGACY"; echo "skill    removed the old copy at $LEGACY"
fi

# 2. API key: only the key goes in this file; the URL lives in profile.md
if [ "${1:-}" = "--rekey" ] || ! { [ -f "$CONF" ] && grep -q '^RR_API_KEY=.' "$CONF"; }; then
  printf 'Reactive Resume API key (input hidden): ' >&2
  IFS= read -rs key || true
  echo >&2
  key="${key//[[:space:]]/}"
  [ -n "$key" ] || { echo "no key entered; nothing stored" >&2; exit 1; }
  ( umask 077; mkdir -p "$(dirname "$CONF")"; printf 'RR_API_KEY=%s\n' "$key" > "$CONF" )
  chmod 600 "$CONF"
  unset key
  echo "key      stored in $CONF (mode 600)"
else
  echo "key      already stored in $CONF (run with --rekey to replace it)"
fi

# 3. data folder and templates (never overwrites), then find your Master resume (creating an empty one if none exists)
uv run --quiet "$CAREER" init
uv run --quiet "$CAREER" master --if-unset --create || true

# 4. one-step connection test
echo "--- career check"
uv run --quiet "$CAREER" check || true
echo "---"
echo "Done. If the old anthropic-skills:career-architect skill is still enabled in the Claude app, disable it so only this one triggers."
