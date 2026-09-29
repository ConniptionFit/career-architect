# Local mode (maintainer)

For one person working from a folder on their machine with the `career` script, without Drive or the hosted server. The documents and rules are the same as hosted mode's SKILL.md; the storage and the deterministic checks run through the script. Use it only when the person says they are working locally. Everything in SKILL.md's rules applies unchanged.

Run the script as `uv run <this skill's folder>/scripts/career.py <command>` (`career` below). It needs Python 3.10 or newer.

## Reactive Resume: the script never calls it

`career` never reaches Reactive Resume over the network: it only builds the JSON Patch `operations` and HTML that Reactive Resume's own MCP server's tools take as input. All resume, PDF, saved-letter and tracker work is the assistant calling that MCP server's tools directly, exactly as `references/reactive-resume.md` describes for hosted mode. Connect it once:

1. In Reactive Resume, sign in and create an API key (Settings > API Keys), or use OAuth if the client supports it.
2. Register the server with the client. For Claude Code:
   ```
   claude mcp add --transport http reactive-resume https://<your-instance>/mcp --header "x-api-key: <your key>"
   ```
   (`-s user` registers it for every project instead of just this one.) Other MCP clients: point them at `https://<your-instance>/mcp` with the same header, or OAuth if offered.
3. Ask the assistant to call the MCP tool `list_resumes`. If it lists your resumes, the connection works. Find (or create) your styled resume named "Master" and note its id.
4. Put that id in `profile.md` as `rr_master` (the assistant can do this with a text edit; there is no `career master` command).

No API key or Reactive Resume address is ever stored by this script or written into the data folder.

## Data folder

`$CAREER_DATA`, or `--data <folder>`, or `~/Documents/Career Architect`. If it is missing, ask where it is.

| File | What |
|---|---|
| `profile.md` | identity, positioning, `never_claim`, `known_gaps`, the Master resume's id (`rr_master`), voice sample |
| `rules.md` | standing wording rules |
| `skills.md` | generated index (`career skills`) |
| `facts.md` | source of truth: roles containing atoms; open it directly only to edit |
| `jobs/<slug>/` | `jd.md`, `selection.yml`, `resume.md`; for a letter `cover.yml`, `cover.md` |

`career init` creates `profile.md` and `facts.md` from the templates if missing (it never overwrites). Templates: `assets/`. `setup.sh` installs the skill and the data folder; it does not touch Reactive Resume.

## Commands

| Command | Does |
|---|---|
| `career skills` | validate `facts.md`, regenerate `skills.md` |
| `career match --req "okta:must:5,jamf:must"` | coverage table and score ceiling |
| `career select --tags "okta,jamf"` | candidate atoms per role, best match first; the only reading of the history a resume needs |
| `career build <slug>` | lint `selection.yml`, write `resume.md` for a plain-text read-through |
| `career patch <slug> [--master-json <file>] [--sync-design]` | lint `selection.yml` and, if clean, print `{resume_name, resume_name_full, resume_slug, operations}` for the MCP tools |
| `career cover-patch <slug>` | lint `cover.yml` and, if clean, print `{name, recipient_html, content_html}` for the MCP tools |
| `career posting <url>` | pay, reports-to and description from Ashby, Greenhouse or Lever |
| `career check` | confirms the data folder, `profile.md`, `facts.md`, `rules.md` and `rr_master` are set up (no network) |

Nothing here lists, creates or edits a resume, cover letter or tracker row: that is always a direct MCP tool call, following `references/reactive-resume.md` exactly as hosted mode does. `references/tools.md` still applies for the tag and document formats (skip the parts about Drive documents; read the local files instead).

## Building a tailored resume

1. `career select --tags "..."` for candidate atoms, then write `jobs/<slug>/selection.yml` (format in `references/tools.md`).
2. Ask the assistant to call MCP `list_resumes`, confirm the Master id matches `rr_master`, and `read_resume` it. Save that JSON to a file (for example `jobs/<slug>/master.json`).
3. `career patch <slug> --master-json jobs/<slug>/master.json`. Fix every `E` in `resume.md`; read the `W` lines and fix the real ones.
4. Call MCP `duplicate_resume` with `resume_name` and `resume_slug` from the output, then `apply_resume_patch` on the copy with `operations` unchanged. `download_resume_pdf` for the link (10 minutes).
5. **Changes:** edit the one bullet in `selection.yml`, run `patch` again, `apply_resume_patch` the new operations to the same resume (`read_resume` it first if it may have been edited).
6. **The Master:** only when asked, build a `general` selection, run `career patch general --master-json <the Master's own JSON>`, show what would change, and apply the operations to the Master's id (not a duplicate) only after they say yes.

## Cover letters

1. Write `jobs/<slug>/cover.yml` (format in `references/tools.md`). The job's tailored resume should already exist.
2. `career cover-patch <slug>`. Fix every `E` in `cover.md`.
3. Follow `references/reactive-resume.md`, "Cover letters": `list_cover_letters` first (by the resume's or tracker row's id) and `create_cover_letter` if none exists, using the printed `name`, `recipient_html` as `recipient`, `content_html` as `content`; otherwise `read_cover_letter` and, if the words match what you last wrote, `update_cover_letter` with the revision you just read. Never overwrite an edit made in Reactive Resume; show the person the difference and ask.

## The application tracker

Entirely MCP tools, exactly as `references/reactive-resume.md`, "Applications" describes for hosted mode: `list_applications` (filtered by `tags: [<company-slug>]` first), `read_application`, `create_application`, `update_application`, `add_application_note`, `get_application_stats`. There is no local file and no script command for it. The "Research block" procedure (read the row, replace only the `RESEARCH <date>` block in the notes, send the merged text) is done the same way: read the text, edit it, send it back.

If `uv` or the script cannot run, do the same steps by reading `skills.md` and `facts.md` directly. It works, it just costs more tokens.
