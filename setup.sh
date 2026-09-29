#!/usr/bin/env bash
# LOCAL MODE installer: one person, files on their own machine, no Obot. (For a group, see docs/OPERATIONS.md.)
# Installs the jobs skill (invoke it with /jobs) and the local data folder. Safe to re-run.
#
#   bash setup.sh                # install / update
#   bash setup.sh --yes          # replace an existing, different installed skill without asking
#
# The installed skill is the whole jobs/ folder, hosted-mode front page included: tell it you are working locally
# (see jobs/references/local-mode.md). The data folder is $CAREER_DATA, default ~/Documents/Career Architect.
#
# This script never touches Reactive Resume: connecting its MCP server is a one-time step in your client, not
# something this script can do (see "Next" below). It never touches your profile.md or facts.md.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS="${CAREER_SKILLS_DIR:-$HOME/.claude/skills}"
SRC="$HERE/jobs"
DEST="$SKILLS/jobs"
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

# 2. data folder and templates (never overwrites)
uv run --quiet "$CAREER" init
echo "--- career check"
uv run --quiet "$CAREER" check || true
echo "---"
cat <<'NEXT'
Done. If the old anthropic-skills:career-architect skill is still enabled in the Claude app, disable it so only this one triggers.

Next, one time only: connect the Reactive Resume MCP server (this script cannot do it for you). In Reactive Resume,
create an API key under Settings > API Keys, then register the server with your client, for example in Claude Code:

  claude mcp add --transport http reactive-resume https://<your-instance>/mcp --header "x-api-key: <your key>"

Then start a jobs session and ask it to call the MCP tool list_resumes to confirm the connection, find (or create)
your styled "Master" resume, and put its id in profile.md as rr_master. Full detail: jobs/references/local-mode.md.
NEXT
