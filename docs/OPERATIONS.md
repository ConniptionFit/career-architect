# Operations runbook

For the administrator. Hostnames below are placeholders: `obot.example.com`, `resume.example.com`. Exact labels in Obot's admin UI can differ between versions; the values to enter do not.

Prerequisites: an Obot instance with an authentication provider, a Reactive Resume 5.x instance, Docker with Compose on the host Obot's MCP servers run on, and a Docker network both reach (`postgres_net` in `mcp-server/compose.example.yaml`; change it to yours).

## 1. Deploy the MCP server

On the Docker host:

```
mkdir -p <compose-dir>/career-architect-mcp && cd <compose-dir>/career-architect-mcp
git clone https://github.com/ConniptionFit/career-architect src
cp src/mcp-server/compose.example.yaml docker-compose.yaml
( umask 077; printf 'CAREER_MCP_TOKEN=%s\n' "$(openssl rand -hex 32)" > .env )
docker compose up -d --build
```

The server has no published ports; only containers on the shared network reach it, as `http://career-architect-mcp:8080/mcp`. `CAREER_MCP_ALLOWED_HOSTS` must contain that exact `host:port` (the compose file sets it). Without a token the server will not start.

### Verify a deployment
```
docker compose ps                                     # healthy
docker compose logs --tail 20                         # no errors
docker exec <any container on the network> python -c "import urllib.request as u; print(u.urlopen('http://career-architect-mcp:8080/healthz').read())"
```
Then, in Obot (step 2), open the server's tool preview: you should see `info`, `normalize_text`, `build_index`, `match`, `lint_resume`, `lint_cover`, `resume_patch` and `posting`. Call `info` and expect the version and limits.

## 2. Register the servers in Obot

**career-architect** (admin: MCP Servers, add a Remote server):
- URL `http://career-architect-mcp:8080/mcp`
- A header `X-Career-Token` whose value is the token from `.env`, marked sensitive and configured once for everyone (it is a server credential, not a personal one).
- Name `career-architect`. If Obot refuses a private address, set `OBOT_SERVER_DISALLOW_PRIVATE_IPMCP=false` on Obot.

**Reactive Resume** (Remote server):
- URL `https://resume.example.com/mcp`, no static header. Reactive Resume publishes OAuth metadata and supports dynamic client registration, so Obot discovers it and each person authorises with their own account (callback `https://obot.example.com/oauth/mcp/callback`). Name it `Reactive Resume`.
- Each person authorises once (the Authenticate button on the server) and the tool preview then lists Reactive Resume's tools.

## 3. Reactive Resume sign-in

Reactive Resume 5.x accepts an OpenID Connect provider through environment variables:

```
OAUTH_PROVIDER_NAME=<label on the button>
OAUTH_CLIENT_ID=...   OAUTH_CLIENT_SECRET=...
OAUTH_DISCOVERY_URL=https://auth.example.com/application/o/<slug>/.well-known/openid-configuration
OAUTH_SCOPES=openid profile email
```
The provider's redirect URI is `https://resume.example.com/api/auth/callback/custom`. Google works the same way with `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`. Notes:
- `FLAG_DISABLE_SIGNUPS` blocks single-sign-on sign-ups as well as email ones. If it is set, a new person's first SSO login is refused: create their account another way, or lift the flag while you onboard.
- Gate the application in the identity provider with a group (for example "Reactive Resume Users") so only invited people can reach it.
- Keep a backup of `.env` before each change and recreate the container (`docker compose up -d`) to apply it.

## 4. Publish the skill in Obot

1. Agent Management, Skills, Sources: add `https://github.com/ConniptionFit/career-architect` (an HTTPS Git URL; the skill directory is `jobs/`). Obot syncs sources hourly; sync manually after a push.
2. Skill Access Policies: create a policy naming the `jobs` skill and the people or group allowed to use it (users have no access to skills by default).
3. MCP access: grant the same people the `career-architect` and `Reactive Resume` servers.

## 5. Onboard a person

1. Identity: create their account in your identity provider and add them to the Reactive Resume group.
2. Obot: they need to sign in to Obot (it uses your configured provider) and be in the access policies of step 4.
3. Reactive Resume: if sign-ups are disabled, see step 3. They sign in once with single sign-on; then they authorise the Reactive Resume server in Obot.
4. Google: they connect their own Google Drive connector in their client. Nothing about Drive is configured on your side.
5. First conversation: they run the `jobs` skill; it finds no `Career Architect` folder and runs onboarding (`jobs/references/onboarding.md`): it creates the folder in their Drive, captures their history, and points at their Master resume in Reactive Resume. They should create or choose a Master resume in Reactive Resume first (template and design carry over to every tailored resume).

## 6. Update

```
cd <compose-dir>/career-architect-mcp
git -C src pull --ff-only && docker compose up -d --build
```
Then re-check the tool preview in Obot. Skill changes need no deploy: push to the repository and sync the source.

**Refreshing pins** (monthly, or when a security advisory lands):
- Dependencies: from `mcp-server/`, `uv pip compile requirements.in --python-version 3.12 --python-platform linux --generate-hashes -o requirements.lock`, review the diff, run the tests (`README.md`), rebuild.
- Base image digest in the `Dockerfile`: `docker buildx imagetools inspect python:3.12-slim-bookworm` and copy the `sha256` digest of the index; rebuild and test.
- Obot itself is kept on `latest` on this deployment; re-run the verification after Obot upgrades.

## 7. Rotate the token

```
cd <compose-dir>/career-architect-mcp
( umask 077; printf 'CAREER_MCP_TOKEN=%s\n' "$(openssl rand -hex 32)" > .env )
docker compose up -d
```
Then update the `X-Career-Token` header value on the server in Obot. Do this whenever someone who knew the token leaves, or the `.env` was exposed.

## 8. Someone leaves

Remove them from the Obot access policies and the identity group; delete their Reactive Resume account. Their Google Drive is theirs.

## 9. Monitoring and troubleshooting
- Health: `/healthz` (unauthenticated, returns the version only). The container healthcheck uses it; the `autoheal` label restarts an unhealthy one where that helper runs.
- Logs are quiet by design (WARNING). A tool crash logs the tool name and exception type; user text is never logged. Set `LOG_LEVEL=INFO` temporarily to see the normal bad-input messages.
- User-facing symptoms and fixes: `jobs/references/troubleshooting.md`.
