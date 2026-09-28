# Local mode notes

Local mode is one person working from a folder with the `career` script and a Reactive Resume API key. The commands are listed in `jobs/references/local-mode.md`. Notes from testing it:

## Reactive Resume behind a proxy
A Cloudflare-fronted instance rejects Python's default User-Agent with `403 Error 1010`. The script sends its own (`career-architect/2`) and reports a proxy block or a login page with a specific hint. If you add Cloudflare Access or a WAF rule, exempt `/api/openapi/*`. Plain `http://` to a public host is upgraded to `https://` because the server's 301 would otherwise turn POST and PATCH into GETs.

## One-time setup in Reactive Resume
1. Create an API key (Settings > API Keys) on the instance named by `rr_url` and give it to `setup.sh` when asked.
2. `setup.sh` creates an empty **Master** resume if none exists. `career master --fill` populates it with real content and US Letter defaults, only while the page settings are still Reactive Resume's defaults.
3. Open the Master in the builder and pick a template while looking at real content. Every tailored resume copies the Master's template and design.

## Verification status
Verified against Reactive Resume 5.3.1 with real PDFs rendered and inspected:
- API key auth, listing, create, duplicate, JSON Patch (including design settings under `/metadata`), PDF download.
- `push`: a duplicate of the Master inherits template and design and gets the summary, experience, skills, header links, education and certifications.
- Saved cover letters: `cover` creates the job's letter linked to its resume and tracker row and updates the same one later; `career letters` lists, shows, exports, imports, renames, duplicates, refreshes the style of and deletes them. Updates and deletes send the `expectedRevision` they read. A letter edited in the browser is never overwritten without `--overwrite`. There is no PDF endpoint for saved letters, so `cover.pdf` comes from the resume's `target=cover-letter` render.
- The `tests/test_live_cover_letters.py` test runs only with `CAREER_LIVE=1` and touches only letters it creates and deletes.
