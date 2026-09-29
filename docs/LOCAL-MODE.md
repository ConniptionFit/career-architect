# Local mode notes

Local mode is one person working from a folder with the `career` script and Reactive Resume's own MCP server connected in their client. The commands are listed in `jobs/references/local-mode.md`.

## The script never touches Reactive Resume

Earlier versions of this script called Reactive Resume's REST API directly (an API key in `~/.config/career/rr.env`, `career push`, `career cover`, `career letters`, `career master`, `career pdf`, `career apply`, `career resumes`). Reactive Resume now ships its own MCP server, so the script no longer needs to speak HTTP to it at all: `career patch` and `career cover-patch` print the JSON Patch operations and HTML, and the assistant applies them with Reactive Resume's MCP tools directly, the same way hosted mode always has (`jobs/references/reactive-resume.md`). This removed several hundred lines of REST client code and the local API-key file entirely.

## One-time setup in Reactive Resume

1. Create an API key (Settings > API Keys), or use OAuth if the client supports it.
2. Register the Reactive Resume MCP server with your client (`jobs/references/local-mode.md` has the exact command for Claude Code).
3. Ask the assistant to call `list_resumes` to confirm the connection, find (or create) your styled "Master" resume, and record its id as `rr_master` in `profile.md`.
4. Open the Master in the builder and pick a template while looking at real content (`career patch general` with no `--master-json` uses Reactive Resume 5.x's own item shapes, enough to fill the Master once for this).

## Verification status

Verified against Reactive Resume 5.3.1's REST API through the version that used it directly (real PDFs rendered and inspected: JSON Patch, including design settings under `/metadata`, duplicate, PDF download). The current MCP-based flow reuses the exact same `career.content_ops` / `career.letter_html` functions that hosted mode's server already exercises against a live instance, so the operations produced are unchanged; what changed is who sends them over the wire.
