# Extending it

Where each kind of change goes, what must change with it, and which test fails if you forget. The design is meant to grow by adding to four lists, never by editing a rule in place: workflows in the skill, tools in the server, servers in the Jobs vMCP, documents in Drive.

## The map

| The change | Files | Held together by |
|---|---|---|
| A new thing the assistant can do (a workflow) | `jobs/workflows/<name>.md`, a row in `jobs/SKILL.md` "Route" | `tests/test_skill_package.py` (frontmatter limits, links, every file reachable from the route table, no personal details), `tests/test_mcp_server.py` (the guide serves every document the skill names). Ships with the next server deploy |
| A new check or builder (a career-architect tool) | `jobs/scripts/career.py`, `mcp-server/server.py`, `jobs/references/tools.md`, `deploy/jobs-vmcp.json`, `tests/` | `tests/test_deploy_spec.py` (server, spec and tools.md must list the same tools) |
| The connector address, or how people install it | `connect/`, then `connect/make.sh` again | `tests/test_connect_plugin.py` (the launcher only launches, the generator refuses a wrong address) |
| Another MCP server in the Jobs vMCP (Gmail, Calendar, Notion, a job board) | Obot, `deploy/jobs-vmcp.json`, a `jobs/references/<source>.md`, a row in `SKILL.md` | `tests/test_deploy_spec.py` (every exposed tool must be explained in the skill; dangerous ones stay off) |
| Another place to keep the person's records | `jobs/references/storage.md` (the protocol), nothing in the server | `tests/test_deploy_spec.py` (storage.md names exactly the exposed Drive and Docs tools) |
| A new field in the facts, profile or selection | `jobs/scripts/career.py`, the templates in `jobs/assets/`, `jobs/references/tools.md` | `tests/test_career.py`, `tests/test_hosted_core.py` |

Run everything with:

```
uv run --python 3.12 --with "mcp==2.2.0" --with pyyaml python -m unittest discover -s tests
uvx --python 3.12 --from skills-ref agentskills validate jobs
```

`.github/workflows/ci.yml` runs these on every push, and parses the manifests.

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

## The connect plugin

What people install in claude.ai, Cowork or Claude Code is one plugin: a ten-line launcher skill and your Jobs connector. The launcher says "call `career_architect__guide`"; the server answers with the current instructions from `jobs/`. That is why it is set and forget: the instructions are never copied to anyone, so there is nothing to keep in step. The same is true of every MCP client, with or without skills.

Make it once, and again only if the connector address changes (do not delete and recreate the vMCP: its id is in the address):

```
connect/make.sh https://<your obot>/mcp-connect/<vmcp id> ../my-jobs-plugin
cd ../my-jobs-plugin && git init && git add -A && git commit -m "Jobs connect plugin" && gh repo create <name> --public --source . --push
```

Make the repository **public**. It holds one address, protected by Obot's sign-in and your access policies, and a private repository could not be added by the people you invite unless you made each a collaborator. (The address does reveal your hostname and vMCP id.)

People add it: claude.ai, *Customize, Plugins, Add, Add marketplace*, the repository; Claude Code, `/plugin marketplace add <owner>/<repo>` then `/plugin install jobs@career-architect-connect`. `connect/README.md` is copied into it and says the same to them.

Why not ship the full skill in the plugin: it would be a copy, and a copy is what goes stale. Claude Code updates marketplaces only when the user turns auto-update on, and on claude.ai the automatic sync needs a webhook on the repository, which the people who add it cannot create. The launcher survives all of that: an old launcher still calls `guide`.

What can still differ per person: whether the assistant calls `guide` first. The launcher, the tool's own description and the vMCP description all say to; check it in a real conversation after a change to any of them.

## Release checklist

1. Change `deploy/jobs-vmcp.json` and the skill in the same commit; tests and `agentskills validate` pass.
2. `CHANGELOG.md`: what changed and whether anything must be done by hand.
3. If `mcp-server/` changed, or anything under `jobs/` (the instructions ship in the image): bump `SERVER_VERSION` when the server changed; push; on the host `bash src/deploy/update.sh` (fetches, rebuilds, waits for healthy); check `docker compose logs` is quiet.
4. If the tool list or descriptions changed: run `deploy/apply-jobs-vmcp.js`; open the Inspector; check the count. Order: to add a tool, apply first and deploy after; to remove one, deploy first and apply after.
5. Sync the skill source in Obot (or wait for the hourly sync).
6. Start a new conversation in a client with the connector and run one real task: score a posting.
7. Tag it: `git tag -a vX.Y.Z -m "<the CHANGELOG title>" && git push origin vX.Y.Z`. The tag is the rollback point (`docs/OPERATIONS.md`, section 7).

## Things to know about Obot

- The tool list and descriptions of a vMCP are live. The skill in Obot is a Git sync, hourly.
- The Google Drive and Docs entries come from Obot's catalog, which follows Obot's releases. Obot says it will move them to Google's official MCP servers; when that happens tool names and behaviour change. The apply script disables any tool it does not know, so a swap fails closed (the skill would report missing tools) instead of exposing something new. Re-read `jobs/references/storage.md` against the new tools before re-enabling.
- `deploy/apply-jobs-vmcp.js` uses Obot's own UI API (`/api/vmcps`), which is not a documented, stable API. If a future Obot changes it, use the UI: the spec says what to enable and what to write.
- Open issues that touch vMCPs are listed in `docs/OPERATIONS.md`, section 4. Check them before a large edit.
