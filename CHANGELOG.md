# Changelog

## 2.5.0, server 1.2.0 (2026-10-23)

- **Large reads run in read-only subagents.** Full-payload tool results (20 to 100 KB each: facts fragments, the `skills` index, `list_applications`, `list_resumes`) were filling the conversation. New rule 16 and a "Large reads" section in `SKILL.md` say to hand heavy reads and checks to a subagent where the client has one, to report only what decides the answer, to treat a large read as write-once, and never to echo a raw payload. Without a subagent tool the same rules apply to a single agent that reads one document at a time and distills it at once.
- **New documents, served by `guide` like the rest:** `references/delegation.md` (when to delegate, how to start a subagent, the rules every subagent follows, the reply contract, oversized results, the no-subagent fallback) and four subagent prompt documents: `references/subagent-facts.md`, `subagent-score.md`, `subagent-lint.md` and `subagent-lookup.md`. A subagent fetches its own prompt by topic, so the prompt text never enters the main conversation.
- **Subagents never write.** Writes stay with the main agent under the storage protocol. The lint subagent can return the exact `operations` (resume) or `cover_text` (letter) that a write needs.
- `workflows/score.md`, `resume.md`, `cover.md` and `references/storage.md` point to the above. No tool or server change, so no vMCP re-apply; deploying the server ships the new instructions. The connect plugin is unchanged (its launcher already calls `guide`).
- Found in trial runs against the live connector: a subagent hand-copying a 15 KB index added a stray line, so the rule is now "copy once, compare line counts"; a full listing of 20 applications was about 100 KB and was saved to a file, so the lookup prompt says how to parse it.

## 2.4.1, server 1.2.0 (2026-09-29)

- **Documentation only.** The README and connect plugin now say plainly that the hosted deployment described here (Obot, Reactive Resume, the career-architect MCP server) is the author's own personal infrastructure for their own group, not a shared or public service, and that no connect plugin should be built to point at it.
- **New: `docs/FORKING.md`.** The end-to-end process for forking the repository and standing up an independent deployment for a different group: what infrastructure is required (your own Obot, your own Reactive Resume, a Docker host for the MCP server; nothing extra for Google Drive/Docs, which rides on Obot's catalog), the order of steps, and how to build and publish your own connect plugin from your own Jobs vMCP address. Local mode (one person, no Obot) is signposted as the lighter alternative for anyone who does not need the group-hosting path.

## 2.4.0, server 1.2.0 (2026-09-29)

- **Local mode now uses Reactive Resume's own MCP server instead of its REST API.** `career.py` no longer talks to Reactive Resume over the network at all: `career push`, `pdf`, `resumes`, `cover`, `letters`, `master` and `apply`, the REST client (`api`, `rr_cfg`, the API-key file `~/.config/career/rr.env`), and the diagnostic JSON-RPC probe in `career check` are gone. In their place, `career patch` and `career cover-patch` lint a selection or letter and, if clean, print the Reactive Resume JSON Patch operations or cover-letter HTML; the assistant applies them with Reactive Resume's MCP tools directly (`apply_resume_patch`, `create_cover_letter`, `update_cover_letter`, and the rest of `references/reactive-resume.md`), the same way hosted mode always has. The application tracker is MCP tools only, with no local script command. `career check` is now a local-only sanity check (data folder, `profile.md`, `rr_master`); the person asks the assistant to call `list_resumes` to confirm the Reactive Resume connection itself.
- **No more stored API key.** `setup.sh` no longer asks for or writes a Reactive Resume API key; it installs the skill and the data folder only, and prints the one-time step to connect Reactive Resume's MCP server in the client (`jobs/references/local-mode.md`).
- `career.fit_name` and `career.DEFAULT_MASTER` moved from `mcp-server/server.py` into `career.py`, which the server now imports, so the hosted and local paths share one definition (unchanged by this release, but no longer duplicated).
- `tests/test_live_cover_letters.py` (an opt-in live REST test) is removed; the REST-backed `Api` test class in `tests/test_career.py` is replaced with `Patch`, which checks `career patch` / `cover-patch` / `check` directly, no fake server needed.

## 2.3.0, server 1.2.0 (2026-09-28)

- **The workspace location is fixed: `AI/JobSearch/<name>`.** Every deployment of this skill uses the same top-level path, found (or made) by walking `AI` then `JobSearch` rather than searching Drive for a folder named `Career Architect`. Inside `JobSearch`, one folder per person, named after them, holds everything that folder used to hold. This lets several people share one Google account (a family, for example) without their records colliding, and removes the "found two folders with this name somewhere in Drive" failure mode by construction. `jobs/references/storage.md`, `onboarding.md` and `troubleshooting.md` are rewritten for it; nothing in the server or the vMCP changed. The user's own records were migrated to `AI/JobSearch/John/`.
- No tool list or server change, so no vMCP re-apply is needed for this release; deploying the server ships the new instructions.

## 2.2.0, server 1.2.0 (2026-09-28)

- **The skill is served by the connector.** New tool `career_architect__guide` returns the skill's own documents (`start` is `SKILL.md`; `workflows/score`, `references/storage` and the rest by path) from the server image. A client that has the Jobs connector therefore always reads the current instructions, whether or not it has, or has updated, a copy of the skill. Deploying the server (or applying the vMCP spec) is what publishes a change; nothing has to reach each person's machine. The vMCP description and the tool description tell the assistant to call it first. 38 tools in total.
- **`connect/` replaces `.claude-plugin/`.** People install one plugin, a ten-line launcher skill plus the Jobs connector (`connect/make.sh` builds it for your address). The earlier plugin that shipped the full skill is gone: a copy of the skill is what goes stale, and two ways to install `jobs` invited using both.
- **One-command deploy and tagged releases.** `deploy/update.sh [ref]` fetches, rebuilds and waits for the container to be healthy; give it a tag to roll back. Releases are tagged (`v2.2.0`).
- The connect plugin's README no longer shows installers the maintainer's notes (`make.sh` drops the section below the `template-only` marker).
- The container image now carries `jobs/SKILL.md`, `workflows/`, `references/`, `style/` and `assets/` (no scripts, no personal data).

## 2.1.0, server 1.1.0 (2026-09-28)

The skill now targets one bundle of tools, the **Jobs** virtual MCP server, instead of three separately connected tools.

- **Jobs vMCP.** `deploy/jobs-vmcp.json` defines it: Career Architect, Reactive Resume, Google Drive and Google Docs behind one endpoint, 37 tools in total, each described for an agent. Destructive, sharing, bulk, import and AI-writing tools are not exposed. `deploy/apply-jobs-vmcp.js` applies the spec to Obot.
- **Storage moved to Google Docs tools.** Drive cannot write content and reads a Doc as a garbled PDF, so records are read with `google_docs__get_document` and written with `google_docs__create_document` (a new version, moved into the folder with `google_drive__update_file`) or `google_docs__replace_text` (one line). `jobs/references/storage.md` is rewritten for this.
- **Server 1.1.0.** Recognises the leading section-break line Google Docs adds (`normalize_text` has a `docs` source); stops treating ordinary blank-line-separated prose as doubled Drive text; tool descriptions now say when to use each tool.
- **Tests.** `tests/test_deploy_spec.py` keeps the skill, the spec and the server's tool list in step; the Docs-shaped text is simulated in `tests/drive_sim.py`.
- **Claude plugin.** `.claude-plugin/` makes the repository a plugin marketplace so Claude apps can install the skill and keep it current.
- **Docs.** `docs/EXTENDING.md`; the runbook covers the vMCP, profiles and what reaches clients by itself.

To upgrade an existing deployment: rebuild the container, create the Jobs vMCP and run the apply script (`docs/OPERATIONS.md`, sections 4 and 7), add Google Drive and Google Docs to the access policy, and have each person connect Google Docs once.

## 2.0.0, server 1.0.0 (2026-09-28)

Hosted, multi-user version: the skill in hosted mode, the stateless career-architect MCP server, Google Drive storage per person, Reactive Resume per person, and the runbook.
