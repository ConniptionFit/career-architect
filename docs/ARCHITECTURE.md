# Architecture

## Goals
A small trusted group each keep their own career history in a place they own, and get resumes, letters and scores that never claim more than that history supports. The person's storage location varies (their own Google Drive), and the administrator runs the shared parts once.

## Components

| Component | Runs | Holds | Trust |
|---|---|---|---|
| **Skill** `jobs/` | Read by the client (through Obot, or as a Claude plugin) | Instructions only | Not executable: Obot does not run skill scripts |
| **Jobs vMCP** `deploy/jobs-vmcp.json` | Obot (a virtual MCP server) | Nothing: it bundles the four servers below behind one endpoint, one tool allowlist and one set of descriptions | Only signed-in, named people reach it; every call runs as that person |
| **career-architect MCP server** `mcp-server/` | One container beside Obot | Nothing (stateless) | Trusts only Obot (shared secret, Host allowlist) |
| **Reactive Resume** (RR) | The administrator's instance | Resumes, saved cover letters, application tracker, per person | Each person signs in with their own account (OAuth through Obot) |
| **Google Drive** and **Google Docs** | Obot's catalog servers, **hosted by Obot the company** (`google-drive-mcp.obot.ai`, `google-docs-mcp.obot.ai`) | `Career Architect/` folder in the person's own Drive: profile, rules, facts, skills index, job texts | Each person connects their own Google account (scopes `drive` and `documents`); their token lives with Obot's service, and their documents pass through it. Nothing here reaches the career-architect server except as request text |

The skill and the Jobs vMCP are two halves of one thing. The skill says what to do and which tools to use; the vMCP decides which tools exist. `tests/test_deploy_spec.py` fails when they disagree.

## Why a hosted server as well as a skill
Obot skills are instructions (a `SKILL.md` directory synced from a Git repository); scripts in them are not executed. The deterministic parts (years from role spans, coverage scoring, the atoms check on every bullet and letter paragraph) are what make "no atom, no claim" enforceable rather than a request to the model, so they run as MCP tools. The same code (`jobs/scripts/career.py`) is the command-line tool for local mode, and tests assert the hosted and local paths give identical results.

## Data flow (a tailored resume)
1. The client reads `profile`, `rules`, `skills` and the few `facts - <role>` documents it needs with `google_docs__get_document`.
2. It writes a selection (bullets, each citing an atom) and calls `career_architect__resume_patch` with that text and the documents. The server validates and returns Reactive Resume JSON Patch operations.
3. The client calls RR's `duplicate_resume` (from the person's Master, so template and design carry over) and `apply_resume_patch`, and hands over the PDF link.
4. The selection is saved to Drive as a new version (`google_docs__create_document`, then `google_drive__update_file` to move it into place).
Nothing is stored by the server between or after calls, and request bodies are not logged.

## Storage model
Google Docs holding plain text, one folder per person: `profile`, `rules`, `skills` (generated), `facts - shared`, one `facts - <role-id>` per role, `jobs/<slug>/{jd,selection,cover}`, `_history/`.
- **One document per role** because a career is tens of kilobytes and a resume needs two or three roles. The generated `skills` index carries what scoring and linting need (years, depth, evidence ids, aliases, credentials, career length) and a role-to-atom table, so most tasks read no facts at all.
- **Plain-text Docs**: Sheets coerce values and evaluate formulas, so nothing is a Sheet. The Docs server's `get_document` returns the text unescaped except for a leading section-break line, which the server removes. Drive's own `read_file` exports a Doc to PDF and garbles it, so it is never used for workspace documents. Text from other Drive readers (escaped, doubled blank lines, base64) is still recognised by its marks and cleaned.
- **Versioned writes** for anything bigger than a line, because the Docs server has no "replace the whole document" tool: create the new version, move it into the folder, then rename and move the old one to `_history/`. Nothing is deleted, and a concurrent edit is detected by `modifiedTime`. A one-line correction uses `replace_text` in place (Google keeps the version history).
- Resumes and PDFs are not in Drive; RR is their home so the person can edit the template.

## Decisions and alternatives

| Decision | Alternative | Why this |
|---|---|---|
| Stateless server; the client ferries documents in tool arguments | Server reads Drive itself with a per-user Google OAuth token | No stored Google tokens or per-user state to protect. Cost: document text passes through the model's output (only the cited fragments). A future version can add server-side Drive if the cost matters |
| Shared secret between Obot and the server | Per-user tokens | The server holds no per-user data; Obot authenticates users and decides who may reach it |
| RR authenticated per person (OAuth through Obot) | One shared API key | Every RR write is attributable and confined to that person's data |
| One Jobs vMCP bundling four servers, with an allowlist of tools | Give each person four separate servers | One endpoint to connect and one place that decides which tools exist. The allowlist enforces `SKILL.md` rules 11 and 13 in the gateway (no delete, share, bulk or import tools exist) instead of trusting the model |
| Google Drive and Docs servers from Obot's catalog | Own storage tools in `mcp-server/`, or the same servers self-hosted | Nothing to build or secure, no Google Cloud project to run, and each person's own Google OAuth. Cost: a third party (Obot's hosted service) is in the path of every document, Obot plans to swap these entries for Google's official servers (tool names would change), and no write-whole-document tool, hence the versioned write. A future storage server can replace them behind the same skill protocol |
| The skill limits which RR tools the client may call | Trust the model | Rules 13 and 14 in `SKILL.md`, and the same list enforced by the vMCP |
| Hash-pinned dependency lock and digest-pinned base image | Floating versions | Reproducible, reviewable builds; refresh procedure in `OPERATIONS.md` |

## Limits (by design)
250,000 characters per document, 40 documents and 600,000 characters per call; 2 MB per request body; `posting` reaches only the public Ashby, Greenhouse and Lever APIs, https only.
