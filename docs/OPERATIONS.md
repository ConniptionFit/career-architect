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

**Where the token file lives.** If the compose directory is on a network share (CIFS/SMB or NFS mounts often report every file as mode 0777 and ignore `chmod`), do not keep the token there. Test with `touch t && chmod 600 t && stat -c %a t`. When it prints 777, keep the token on the host's local disk and pass it explicitly:

```
mkdir -p ~/.config/career-architect-mcp && chmod 700 ~/.config/career-architect-mcp
( umask 077; printf 'CAREER_MCP_TOKEN=%s\n' "$(openssl rand -hex 32)" > ~/.config/career-architect-mcp/env )
docker compose --env-file ~/.config/career-architect-mcp/env up -d --build
```
Use the same `--env-file` on every `docker compose` command for this project. Leaving it off fails with "set CAREER_MCP_TOKEN" instead of starting the server without a secret.

The server has no published ports; only containers on the shared network reach it, as `http://career-architect-mcp:8080/mcp`. `CAREER_MCP_ALLOWED_HOSTS` must contain that exact `host:port` (the compose file sets it). Without a token the server will not start.

### Verify a deployment
```
docker compose ps                                     # healthy
docker compose logs --tail 20                         # no errors
docker exec <any container on the network> python -c "import urllib.request as u; print(u.urlopen('http://career-architect-mcp:8080/healthz').read())"
```
Then, in Obot (step 2), open the server's tool preview: you should see `info`, `normalize_text`, `build_index`, `match`, `lint_resume`, `lint_cover`, `resume_patch` and `posting`. Call `info` and expect the version and limits.

## 2. Register the servers in Obot

**career-architect** (Obot admin: MCP Servers, Add MCP Server, choose *Remote Server*):
- Name `Career Architect`; a short description (Obot caps it at 160 characters).
- *Restrict connections to: Exact URL* `http://career-architect-mcp:8080/mcp`.
- Configuration, add one item: Usage *Header*, Key `X-Career-Token`, Value *Static*, the token from the server's env file, Sensitive on. Static means the administrator sets it once and no user is ever asked for it. (*User-Supplied* would make every user paste the token.) Obot stores a static value in the entry, where administrators can read it; it protects the server from other containers on the network, not from Obot administrators.
- If Obot refuses a private address, set `OBOT_SERVER_DISALLOW_PRIVATE_IPMCP=false` on Obot.
- Save, then open the entry's *Tools* tab and *Populate Tool Preview* (or *Regenerate*). That dialog asks for the header value even though it is static; paste the token once and click Launch. If Obot answers `409 ... the object has been modified`, click Launch again: the entry was updated between page load and request.
- The preview should list the eight tools.

**First real connection.** Connect from a client (an Obot-connected Claude) and call `info`. Then run `docker logs career-architect-mcp`: it should be empty. A line `unauthorized request to /mcp: token header missing` means Obot did not send the static header (re-check the item above); `present but wrong` means the value differs from the server's token.

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

1. Skills, Sources, *Add Source URL*: name `career-architect`, URL `https://github.com/ConniptionFit/career-architect`, reference `main`, no credential (the repository is public). Obot syncs sources hourly and immediately on adding; a new commit needs a manual sync or the next hourly run. The `jobs` skill should appear as valid.
2. **Who can use it is decided by access policies, not by sign-in.** Create one named-user policy in each place, both called `Career Architect users`:
   - MCP Servers, Access Policies: users = the people allowed, servers = `Career Architect` and `Reactive Resume` (pick the two servers, never *Everything in Global Registry*).
   - Skills, Access Policies: the same users, skill = `jobs` (pick the skill itself, not the repository entry, so a skill added to the repository later is not shared automatically).
3. Narrow any wildcard policy that grants *All Obot Users* (Obot ships an `Everything` policy for servers and for skills). Add the administrator by name to it first, then remove *All Obot Users*, then save. Do it in that order so the administrator never loses access.

## 5. Sign-in and default access

Obot's Google provider can restrict sign-in only by email domain, not by individual address (set *Allowed E-Mail Domains* to your organisation's domain if you have one). With personal `gmail.com` accounts anyone with a Google account can sign in, so the safety comes from authorization: **a person who is not named in a policy sees no servers and no skills.** Keep the *Default User Role* (Identity & Access, Roles) at *Standard User*, the lowest role, and keep no policy that grants *All Obot Users*. Chat needs a model provider; while none is configured a Standard User has nothing to chat with.

Checks after any policy change: MCP Servers, Access Policies lists only named policies (plus the administrator's); the same for Skills. An unlisted user has no access.

If you need a true sign-in whitelist (only accounts you create can sign in), Obot's *Local* provider does that, but switching provider signs everyone out and does not carry accounts, connected services or history over, so decide before you have data in Obot.

### Onboard a person

1. Give them the Obot address. They sign in once with their Google account; that creates their user with no access.
2. Add them by name to both `Career Architect users` policies (MCP Servers and Skills).
3. Identity: create their account in your identity provider and add them to the Reactive Resume group. If sign-ups are disabled in Reactive Resume (`FLAG_DISABLE_SIGNUPS` also blocks single-sign-on sign-ups), lift it while they sign in once or create the account another way.
4. They connect Google Drive in their client and authorise Reactive Resume in Obot (each person authorises their own account).
5. First conversation: they run the `jobs` skill, which finds no `Career Architect` folder and runs onboarding (`jobs/references/onboarding.md`). They should create or choose a Master resume in Reactive Resume first (its template and design carry over to every tailored resume).

### Someone leaves

Remove them from both `Career Architect users` policies and the identity group; delete their Reactive Resume account. Their Drive is theirs.

## 6. Update

```
cd <compose-dir>/career-architect-mcp
git -C src pull --ff-only && docker compose --env-file <env-file> up -d --build
```
Then re-check the tool preview in Obot. Skill changes need no deploy: push to the repository and sync the source.

**Refreshing pins** (monthly, or when a security advisory lands):
- Dependencies: from `mcp-server/`, `uv pip compile requirements.in --python-version 3.12 --python-platform linux --generate-hashes -o requirements.lock`, review the diff, run the tests (`README.md`), rebuild.
- Base image digest in the `Dockerfile`: `docker buildx imagetools inspect python:3.12-slim-bookworm` and copy the `sha256` digest of the index; rebuild and test.
- Obot itself is kept on `latest` on this deployment; re-run the verification after Obot upgrades.

## 7. Rotate the token

Write a new token to the env file you use (see step 1), recreate the container with the same `--env-file`, then update the header value on the Obot entry (Configuration tab) and regenerate the tool preview.

```
cd <compose-dir>/career-architect-mcp
( umask 077; printf 'CAREER_MCP_TOKEN=%s\n' "$(openssl rand -hex 32)" > <env-file> )
docker compose --env-file <env-file> up -d
``` Do this whenever someone who knew the token leaves, or the `.env` was exposed.

## 8. Monitoring and troubleshooting
- Health: `/healthz` (unauthenticated, returns the version only). The container healthcheck uses it; the `autoheal` label restarts an unhealthy one where that helper runs.
- Logs are quiet by design (WARNING). A tool crash logs the tool name and exception type; a rejected request logs its path and whether a token header was present, never the token; user text is never logged. `LOG_LEVEL` (default `WARNING`) is read at start, and INFO logs tool error messages, which can quote a document's parser errors, so leave it at WARNING outside debugging.
- User-facing symptoms and fixes: `jobs/references/troubleshooting.md`.
