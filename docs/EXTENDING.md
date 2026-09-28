# Extending it

Where each kind of change goes, what must change with it, and which test fails if you forget. The design is meant to grow by adding to four lists, never by editing a rule in place: workflows in the skill, tools in the server, servers in the Jobs vMCP, documents in Drive.

## The map

| The change | Files | Held together by |
|---|---|---|
| A new thing the assistant can do (a workflow) | `jobs/workflows/<name>.md`, a row in `jobs/SKILL.md` "Route" | `tests/test_skill_package.py` (frontmatter limits, links, every file reachable from the route table, no personal details) |
| A new check or builder (a career-architect tool) | `jobs/scripts/career.py`, `mcp-server/server.py`, `jobs/references/tools.md`, `deploy/jobs-vmcp.json`, `tests/` | `tests/test_deploy_spec.py` (server, spec and tools.md must list the same tools) |
| Another MCP server in the Jobs vMCP (Gmail, Calendar, Notion, a job board) | Obot, `deploy/jobs-vmcp.json`, a `jobs/references/<source>.md`, a row in `SKILL.md` | `tests/test_deploy_spec.py` (every exposed tool must be explained in the skill; dangerous ones stay off) |
| Another place to keep the person's records | `jobs/references/storage.md` (the protocol), nothing in the server | `tests/test_deploy_spec.py` (storage.md names exactly the exposed Drive and Docs tools) |
| A new field in the facts, profile or selection | `jobs/scripts/career.py`, the templates in `jobs/assets/`, `jobs/references/tools.md` | `tests/test_career.py`, `tests/test_hosted_core.py` |

Run everything with:

```
uv run --python 3.12 --with "mcp==2.2.0" --with pyyaml python -m unittest discover -s tests
uvx --python 3.12 --from skills-ref agentskills validate jobs
claude plugin validate .
```

`.github/workflows/ci.yml` runs the first two on every push.

## Add a workflow

1. Write `jobs/workflows/<name>.md`: when to use it, the steps, which references it reads. Use tool names in the form the skill uses (bare for career-architect and Reactive Resume tools, full for Drive and Docs).
2. Add one row to the "Route" table in `jobs/SKILL.md`. Keep SKILL.md short (the standard's limit is 500 lines and it is about 80 now): it is read at the start of every task, and detail belongs in `workflows/` and `references/`, which are read only when routed to.
3. Do not add a rule that a workflow could carry. The rules in SKILL.md are the ones that hold for every task.

## Add a tool to the career-architect server

A tool is a pure function of the text it is given: no files, no network (except the pinned ATS hosts in `posting`), nothing kept between calls.

1. Put the logic in `jobs/scripts/career.py` so local mode gets it too, and test it there.
2. Wrap it in `mcp-server/server.py` with `@server.tool(...)` and `@guarded`. The docstring is what an agent reads to decide whether to call it, so begin it with "Use to ..." or "Use when ...", say what it returns, and take document arguments as `Doc` so Google Docs text is cleaned.
3. Add the tool name to `enabled` under Career Architect in `deploy/jobs-vmcp.json` and a row in `jobs/references/tools.md`.
4. Bump `SERVER_VERSION`, add a line to `CHANGELOG.md`, rebuild the container (`docs/OPERATIONS.md`, section 7), and run `deploy/apply-jobs-vmcp.js` (a new tool on a server is disabled until the spec enables it).

## Add another MCP server to the Jobs vMCP

The Jobs vMCP is meant to grow: it is one endpoint, so a person who has it gets new sources without connecting anything new. The order matters, because each step is what makes the next one safe.

1. **Register the server** in Obot (catalog or remote). Decide what a person signs in with, and add it to the `Career Architect users` MCP policy.
2. **Add it as a component** of the Jobs vMCP. The component name becomes the tool prefix (`Google Calendar` becomes `google_calendar__`), so name it deliberately.
3. **Start from nothing.** Disable every tool. Then enable only the ones a workflow needs, reads before writes, and never anything that deletes, shares, sends on the person's behalf or changes settings. Write a description for each enabled tool that says when to use it and any rule of ours (see the Drive and Docs entries in `deploy/jobs-vmcp.json`).
4. **Record it** in `deploy/jobs-vmcp.json`: a new object in `sources` with `component`, `prefix` (the component name lower-cased, non-letters as `_`), `origin`, `enabled`, `disabled` (every other tool the server has) and `descriptions`.
5. **Explain it to the skill**: `jobs/references/<source>.md` (which tools, in which order, with which limits), a row in the source table and, if there is a new task it enables, a workflow. `tests/test_deploy_spec.py` fails until every enabled tool is mentioned in a document under `jobs/`.
6. **Say what it adds to the boundary** in `docs/SECURITY.md` (what data it can read, what it can change).
7. Apply the spec (`deploy/apply-jobs-vmcp.js`), check the Inspector, then push. The skill and the tool list change together: a new conversation sees both.

## Change where records are kept

Nothing in the server knows about Drive. `jobs/references/storage.md` is the whole contract: how to find the workspace, read a document, write one, and what a document looks like. To keep records somewhere else (Notion, a folder, a database), write that protocol for the new place, expose its tools through the vMCP as above, and leave `career.py` and `server.py` alone: they take text in and give text out.

## A plugin that bundles the skill and your Jobs vMCP

This repository is a plugin marketplace whose plugin `jobs` carries the skill only. The address of your Obot and the Jobs vMCP (`https://obot.example.com/mcp-connect/<vmcp id>`) belongs to your deployment, so it stays out of this public repository. To have one install bring both, make a small marketplace of your own, in a repository that only your people can read if you prefer, with one file, `.claude-plugin/marketplace.json`:

```json
{
  "name": "jobs-at-example",
  "owner": { "name": "Example" },
  "plugins": [
    {
      "name": "jobs",
      "description": "Job-search assistant: the jobs skill and its Jobs connector.",
      "source": { "source": "github", "repo": "ConniptionFit/career-architect" },
      "mcpServers": {
        "jobs": { "type": "http", "url": "https://obot.example.com/mcp-connect/<vmcp id>" }
      }
    }
  ]
}
```

The skill comes from this repository, at its default branch, so it updates with every commit; the connector is the one line that is yours. In claude.ai the connector then appears on the plugin's *Connectors* tab and each person signs in through Obot; Claude Code loads it with the plugin.

Add the marketplace: claude.ai, *Customize, Plugins, Add, Add marketplace*; Claude Code, `/plugin marketplace add <owner>/<repo>`. Keeping it current is in `docs/OPERATIONS.md`, section 7. Pin a release instead of tracking `main` by adding `"ref": "<tag>"` to the `source`.

## Release checklist

1. Change `deploy/jobs-vmcp.json` and the skill in the same commit; tests, `agentskills validate`, `claude plugin validate .` pass.
2. `CHANGELOG.md`: what changed and whether anything must be done by hand.
3. If `mcp-server/` changed: bump `SERVER_VERSION`; push; on the host `git -C src pull --ff-only && docker compose --env-file <env-file> up -d --build`; check `docker compose logs` is quiet.
4. If the tool list or descriptions changed: run `deploy/apply-jobs-vmcp.js`; open the Inspector; check the count.
5. Sync the skill source in Obot (or wait for the hourly sync).
6. Start a new conversation and run one real task: score a posting.

## Things to know about Obot

- The tool list and descriptions of a vMCP are live. The skill in Obot is a Git sync, hourly.
- `deploy/apply-jobs-vmcp.js` uses Obot's own UI API (`/api/vmcps`), which is not a documented, stable API. If a future Obot changes it, use the UI: the spec says what to enable and what to write.
- Open issues that touch vMCPs are listed in `docs/OPERATIONS.md`, section 4. Check them before a large edit.
