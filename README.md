# career-architect

A job-search assistant for a small trusted group, built to run on an [Obot](https://obot.ai) MCP gateway. Each person's career history is kept as small structured records (atoms) in **their own Google Drive**. A skill tells the assistant how to use them, a small hosted MCP server does the deterministic work (years, scoring, linting), and [Reactive Resume](https://rxresu.me) holds the resumes, cover letters and the application tracker.

The rule that shapes everything: **no atom, no claim.** Every bullet in a resume or letter traces to something the person confirmed, so nothing they would have to defend in an interview was made up along the way.

> **This repository's hosted deployment (Obot instance, Reactive Resume instance, career-architect MCP server) is
> personal infrastructure run by the author, [ConniptionFit](https://github.com/ConniptionFit), for their own small
> group.** It is not a shared or public service, nobody outside that group can sign in to it, and no connect plugin
> should be built to point at it. If you want to use this skill: run local mode against your own Reactive Resume
> (below), or fork the repository and stand up your own copy of the whole stack — [docs/FORKING.md](docs/FORKING.md).

```
      the person's client (Claude, through Obot or a Claude plugin)
                               |
                Jobs vMCP: one endpoint, one tool allowlist
                               |
   +---------------+-----------+---------+------------------+
   |               |                     |                  |
Google Docs   Google Drive       career-architect    Reactive Resume
(their own    (their own         (stateless, this    (their own account,
 account)      account)           repository)         OAuth)
   |               |                     |                  |
   +-------+-------+                     |                  |
           |                             |                  |
  AI/JobSearch/<name>/           checks and builders   resumes, cover
  profile, rules, facts,                               letters, tracker
  skills index, job texts
```

## What is in the repository

| Path | What |
|---|---|
| `jobs/` | The skill (Agent Skills standard: `SKILL.md`, `workflows/`, `references/`, `assets/`, `style/`). This is what Obot syncs. |
| `jobs/scripts/career.py` | The deterministic core, also a command-line tool for local mode. |
| `mcp-server/` | The hosted MCP server (`server.py`), its hash-pinned dependency lock, `Dockerfile` and `compose.example.yaml`. |
| `deploy/` | The Jobs vMCP definition (`jobs-vmcp.json`: which tools exist and how they are described) and a script that applies it to Obot. |
| `connect/` | Template for the one-install plugin (launcher skill + your Jobs connector) that people add in claude.ai, Cowork or Claude Code. |
| `deploy/update.sh` | One command to deploy a version of the server on the Docker host, and to roll back to a tagged one. |
| `tests/` | Offline tests: `uv run --python 3.12 --with "mcp==2.2.0" --with pyyaml python -m unittest discover -s tests` |
| `docs/` | Architecture, operations runbook, security and privacy notes, [how to extend it](docs/EXTENDING.md), and [how to fork it for your own group](docs/FORKING.md). |
| `setup.sh` | Installer for local mode (one person, files on their machine). |

## Deploying for a group, on your own infrastructure

This is how the author's own deployment is built, and how to build an independent one of your own — **not** how to
join the author's. Every box below (Obot, Reactive Resume, the MCP server's Docker host) must be one you administer;
see [docs/FORKING.md](docs/FORKING.md) for the full checklist, starting from forking the repository.

1. Run the MCP server next to your own Obot (`mcp-server/compose.example.yaml`).
2. Register it, your own Reactive Resume, Google Drive and Google Docs as MCP servers in your Obot, and bundle them as one **Jobs** vMCP with the tool allowlist in `deploy/jobs-vmcp.json`.
3. Add your fork as a Skill source in your Obot (and, for the Claude apps, publish your own plugin marketplace, `connect/make.sh`); grant your group access.
4. Onboard each person: an account, access, and a first conversation that creates their `AI/JobSearch/<name>` Drive folder.

The runbook, with every value to enter, is [docs/OPERATIONS.md](docs/OPERATIONS.md). Design and decisions are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md); what is stored, where, and what is protected is in [docs/SECURITY.md](docs/SECURITY.md); the fork-and-self-host checklist is [docs/FORKING.md](docs/FORKING.md).

## Local mode

One person, no Obot: `bash setup.sh` installs the skill into `~/.claude/skills/jobs` and creates the data folder (`$CAREER_DATA`, default `~/Documents/Career Architect`). It never touches Reactive Resume; connect Reactive Resume's own MCP server in your client once (`jobs/references/local-mode.md` has the exact command). See that file and [docs/LOCAL-MODE.md](docs/LOCAL-MODE.md). `setup.sh` copies the whole `jobs/` folder over an existing install, so run it only on a machine where that is what you want.

## Status

Verified against Reactive Resume 5.3.x. The hosted server, its container image and the Obot registration are documented but a given deployment has to be checked with `docs/OPERATIONS.md`, "Verify a deployment".

## License

MIT, see [LICENSE](LICENSE).
