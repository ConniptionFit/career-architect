# Local mode (maintainer)

For one person working from a folder on their machine with the `career` script, without Drive or the hosted server. The documents and rules are the same; the storage, the checks and the Reactive Resume calls run through the script. Use it only when the person says they are working locally. Everything in SKILL.md's rules applies unchanged.

Run the script as `uv run <this skill's folder>/scripts/career.py <command>` (`career` below). It needs Python 3.10 or newer.

## Data folder

`$CAREER_DATA`, or `--data <folder>`, or `~/Documents/Career Architect`. If it is missing, ask where it is.

| File | What |
|---|---|
| `profile.md` | identity, positioning, `never_claim`, `known_gaps`, Reactive Resume settings, voice sample |
| `rules.md` | standing wording rules |
| `skills.md` | generated index (`career skills`) |
| `facts.md` | source of truth: roles containing atoms; open it directly only to edit |
| `jobs/<slug>/` | `jd.md`, `selection.yml`, `resume.md`, the PDF; for a letter `cover.yml`, `cover.md`, `cover.pdf`, `cover.json` |

`career init` creates `profile.md` and `facts.md` from the templates if missing (it never overwrites). Templates: `assets/`. `setup.sh` installs the skill and writes the Reactive Resume settings.

The Reactive Resume API key lives in `~/.config/career/rr.env` (mode 600). Never ask for it, print it, or write it into the data folder or a client config.

## Commands

| Command | Does |
|---|---|
| `career skills` | validate `facts.md`, regenerate `skills.md` |
| `career match --req "okta:must:5,jamf:must"` | coverage table and score ceiling |
| `career select --tags "okta,jamf"` | candidate atoms per role, best match first; the only reading of the history a resume needs |
| `career build <slug>` | lint `selection.yml`, write `resume.md` |
| `career push <slug>` | duplicate the Master in RR, fill it, save the PDF (`--sync-design`, `--dry`) |
| `career pdf`, `career resumes`, `career master [--fill]` | PDF download, list resumes, refresh the Master from `jobs/general` |
| `career cover <slug> [--dry] [--attach] [--overwrite] [--no-saved]` | lint `cover.yml`, write `cover.md`, create or update the saved letter, write `cover.pdf` |
| `career letters ls\|show\|export\|import\|rename\|duplicate\|refresh-style\|delete` | the saved Cover Letters list (`delete` only when asked) |
| `career apply find\|show\|ls\|stats\|add\|set\|doc` | tracker rows; `add` updates the matching row instead of duplicating |
| `career posting <url>` | pay, reports-to and description from Ashby, Greenhouse or Lever |
| `career check` | tests the URL, health, API key, Master resume, saved letters, MCP endpoint and MCP registration, one step at a time |

Behaviours worth knowing:

- `push` names the resume and PDF `Company - Role - Person Resume`, links the tracker row's resume when `app.json` exists, and fills header, education and certifications from `profile.md` and `facts.md`.
- `cover` never overwrites edits made in Reactive Resume: with `cover.yml` unchanged it leaves the saved letter alone; with both changed it stops (exit 1) until the wanted edits are folded into `cover.yml` and `--overwrite` is used.
- `apply set --notes-file` replaces only the `RESEARCH <date>` block of the notes; `--notes` appends.
- `apply add`, `set` and `find` never need an id: they match on company and role.

## Reactive Resume MCP alongside the script

When the client also has the Reactive Resume MCP tools, use them for single-record reads and edits and keep the script for listings, derived documents and files (the tools return whole records: `list_applications` is about 72,000 characters against 1,200 for `career apply ls`).

| Task | Use |
|---|---|
| List or find applications | `career apply ls`, `career apply find` |
| Read one application | MCP `read_application` |
| Status, follow-up, contacts, salary, tags, archive | MCP `update_application` (provided fields replace; read first, send the merged value) |
| A timeline entry | MCP `add_application_note` |
| Research block | `career apply set --notes-file` |
| Create a row, attach a PDF | `career apply add`, `--attach` |
| Tailored resume, cover PDF, Master, PDF download | `career push`, `career cover`, `career master`, `career pdf` |
| Letters: list, read, duplicate, export, rename | MCP `list_cover_letters`, `read_cover_letter`, `duplicate_cover_letter`, `export_cover_letter`, `update_cover_letter` with `name` only |

If `uv` or the script cannot run, do the same steps by reading `skills.md` and `facts.md` directly. It works, it just costs more tokens.
