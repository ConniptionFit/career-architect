#!/usr/bin/env bash
# Deploy a version of the career-architect server. Run it from the compose directory (the one holding docker-compose.yaml and src/).
#   bash src/deploy/update.sh            the latest main
#   bash src/deploy/update.sh v2.2.0     a release tag: this is also how you roll back
# It fetches, checks out the ref, rebuilds, waits until the container is healthy and says what is left to do in Obot.
set -euo pipefail
ref="${1:-main}"
env_file="${CAREER_ENV_FILE:-$HOME/.config/career-architect-mcp/env}"
name="${CAREER_CONTAINER:-career-architect-mcp}"

[ -f docker-compose.yaml ] && [ -d src/.git ] || { echo "error: run this in the compose directory (docker-compose.yaml and src/)" >&2; exit 2; }
[ -f "$env_file" ] || { echo "error: no token file at $env_file (set CAREER_ENV_FILE)" >&2; exit 2; }
[ -z "$(git -C src status --porcelain)" ] || { echo "error: src/ has local changes; commit or discard them first" >&2; exit 2; }

git -C src fetch --tags --quiet origin
git -C src checkout --quiet "$ref"
[ "$ref" != main ] || git -C src merge --ff-only --quiet origin/main
here="$(git -C src describe --tags --always)"
docker compose --env-file "$env_file" up -d --build

for _ in $(seq 1 30); do
  state="$(docker inspect -f '{{.State.Health.Status}}' "$name" 2>/dev/null || echo missing)"
  [ "$state" = healthy ] && break
  sleep 2
done
[ "$state" = healthy ] || { echo "error: $name is $state after 60 seconds; see: docker logs $name" >&2; exit 1; }

echo "deployed $here ($name is healthy)"
echo "next: if tools were added, removed or re-described, run deploy/apply-jobs-vmcp.js (add a tool: apply BEFORE deploying; remove one: apply AFTER)"
[ "$ref" = main ] || echo "note: src/ is now at $ref, not main. Go back to the latest with: bash src/deploy/update.sh"
