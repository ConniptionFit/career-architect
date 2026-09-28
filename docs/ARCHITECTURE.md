# Architecture

## Goals
A small trusted group each keep their own career history in a place they own, and get resumes, letters and scores that never claim more than that history supports. The person's storage location varies (their own Google Drive), and the administrator runs the shared parts once.

## Components

| Component | Runs | Holds | Trust |
|---|---|---|---|
| **Skill** `jobs/` | Read by the client through Obot (Agent Skills standard) | Instructions only | Not executable: Obot does not run skill scripts |
| **career-architect MCP server** `mcp-server/` | One container beside Obot | Nothing (stateless) | Trusts only Obot (shared secret, Host allowlist) |
| **Reactive Resume** (RR) | The administrator's instance | Resumes, saved cover letters, application tracker, per person | Each person signs in with their own account (OAuth through Obot) |
| **Google Drive** | The person's account | `Career Architect/` folder: profile, rules, facts, skills index, job texts | The person's own connector; nothing here reaches the server except as request text |

## Why a hosted server as well as a skill
Obot skills are instructions (a `SKILL.md` directory synced from a Git repository); scripts in them are not executed. The deterministic parts (years from role spans, coverage scoring, the atoms check on every bullet and letter paragraph) are what make "no atom, no claim" enforceable rather than a request to the model, so they run as MCP tools. The same code (`jobs/scripts/career.py`) is the command-line tool for local mode, and tests assert the hosted and local paths give identical results.

## Data flow (a tailored resume)
1. The client reads `profile`, `rules`, `skills` and the few `facts - <role>` documents it needs from Drive.
2. It writes a selection (bullets, each citing an atom) and calls `resume_patch` with that text and the documents. The server validates and returns Reactive Resume JSON Patch operations.
3. The client calls RR's `duplicate_resume` (from the person's Master, so template and design carry over) and `apply_resume_patch`, and hands over the PDF link.
4. The selection is saved to Drive as a new version.
Nothing is stored by the server between or after calls, and request bodies are not logged.

## Storage model
Google Docs holding plain text, one folder per person: `profile`, `rules`, `skills` (generated), `facts - shared`, one `facts - <role-id>` per role, `jobs/<slug>/{jd,selection,cover}`, `_history/`.
- **One document per role** because a career is tens of kilobytes and a resume needs two or three roles. The generated `skills` index carries what scoring and linting need (years, depth, evidence ids, aliases, credentials, career length) and a role-to-atom table, so most tasks read no facts at all.
- **Plain-text Docs**, chosen after testing the connector: Sheets coerce values and evaluate formulas; Docs read back with markdown escaping and doubled newlines, which the server normalises (`normalize_text`); base64 downloads add a BOM and CRLF, also normalised.
- **Versioned writes** because the connector cannot change a document's content: create the new version, then rename and move the old one to `_history/`. Nothing is deleted, and a concurrent edit is detected by `modifiedTime`.
- Resumes and PDFs are not in Drive; RR is their home so the person can edit the template.

## Decisions and alternatives

| Decision | Alternative | Why this |
|---|---|---|
| Stateless server; the client ferries documents in tool arguments | Server reads Drive itself with a per-user Google OAuth token | No stored Google tokens or per-user state to protect. Cost: document text passes through the model's output (only the cited fragments). A future version can add server-side Drive if the cost matters |
| Shared secret between Obot and the server | Per-user tokens | The server holds no per-user data; Obot authenticates users and decides who may reach it |
| RR authenticated per person (OAuth through Obot) | One shared API key | Every RR write is attributable and confined to that person's data |
| The skill limits which RR tools the client may call | Trust the model | Rules 13 and 14 in `SKILL.md`. Recommended: also restrict tools in Obot where the version supports it |
| Hash-pinned dependency lock and digest-pinned base image | Floating versions | Reproducible, reviewable builds; refresh procedure in `OPERATIONS.md` |

## Limits (by design)
250,000 characters per document, 40 documents and 600,000 characters per call; 2 MB per request body; `posting` reaches only the public Ashby, Greenhouse and Lever APIs, https only.
