#!/usr/bin/env bash
# Make the deployment's connect plugin: a folder that is its own plugin repository (launcher skill + your Jobs connector).
#   connect/make.sh https://obot.example.com/mcp-connect/<vmcp id> ../my-jobs-plugin
# It copies this folder, turns the skill template into SKILL.md and writes your connector address into .mcp.json.
# Push the result as its own repository; see docs/EXTENDING.md, "The connect plugin".
set -euo pipefail
url="${1:?usage: make.sh <https address of the Jobs vMCP> <target folder>}"
target="${2:?usage: make.sh <https address of the Jobs vMCP> <target folder>}"
case "$url" in https://*/mcp-connect/*) ;; *) echo "error: the address should look like https://<obot>/mcp-connect/<vmcp id>" >&2; exit 2 ;; esac
case "$url" in *"<"*|*" "*|*'"'*) echo "error: the address contains characters that do not belong in it" >&2; exit 2 ;; esac
here="$(cd "$(dirname "$0")" && pwd)"
[ ! -e "$target" ] || [ -z "$(ls -A "$target" 2>/dev/null)" ] || { echo "error: $target exists and is not empty" >&2; exit 2; }
mkdir -p "$target/skills/jobs" "$target/.claude-plugin"
cp "$here/.claude-plugin/plugin.json" "$here/.claude-plugin/marketplace.json" "$target/.claude-plugin/"
cp "$here/skills/jobs/SKILL.md.template" "$target/skills/jobs/SKILL.md"
printf '{\n  "mcpServers": {\n    "jobs": {\n      "type": "http",\n      "url": "%s"\n    }\n  }\n}\n' "$url" > "$target/.mcp.json"
sed '/<!-- template-only/,$d' "$here/README.md" > "$target/README.md"
cp "$here/../LICENSE" "$target/LICENSE"
echo "wrote $target"
