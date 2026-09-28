# Reactive Resume (RR): resumes, letters and the tracker

RR's MCP server is the only place resumes, PDFs, saved cover letters and applications are created or changed. The person signs in to it through their own account, so every call acts as them. Tool names below are RR's; find them by suffix. Read a tool's own schema for exact field names before the first call of a kind, and never guess an id.

RR's tools return whole records, and some are large (a master resume is about 22,000 characters; listing every application about 72,000). Ask for the smallest thing that answers the question, and prefer filtered lists.

## Allowed writes

Anything not on this list is not allowed (SKILL.md rule 13).

| Purpose | Tool | Conditions |
|---|---|---|
| Copy the Master for a posting | `duplicate_resume` | `id` is the Master id from `profile`; `name` is `resume_name` from `resume_patch` (at most 64 characters, RR's limit); `slug` is `resume_slug`; `tags: ["tailored"]` (the tag the local script uses too) |
| Fill that copy | `apply_resume_patch` | `operations` exactly as `resume_patch` returned them; `id` is the copy you just made, never the Master |
| Rename or retag a resume | `update_resume` | metadata only; ask first if the person named it |
| Create the saved letter | `create_cover_letter` | `content` and `recipient` from `lint_cover`'s `content_html` and `recipient_html`; `name` from its `name`; `resumeId` set; `applicationId` set when a tracker row exists |
| Update the saved letter | `update_cover_letter` | only after `read_cover_letter`; pass the `revision` you read as `expectedRevision`; see "Cover letters" |
| Create or update a tracker row | `create_application`, `update_application`, `add_application_note` | see "Applications" |
| Give the person a PDF | `download_resume_pdf` | returns a link valid for 10 minutes; hand it over, do not fetch it |

Reads are always fine: `list_resumes`, `read_resume`, `list_cover_letters`, `read_cover_letter`, `list_applications`, `read_application`, `get_application_stats`, `list_application_tags`, `list_resume_tags`.

## Resumes

1. `list_resumes` and confirm the Master: its id matches `rr_master` in `profile`. If `profile` has none, ask which resume is the Master and record it.
2. `resume_patch` (career-architect) lints the selection and returns `operations`, `resume_name` (at most 64 characters), `resume_name_full` and `resume_slug`. It returns no operations while the lint has errors: fix them, do not work around it.
3. `duplicate_resume` from the Master. It inherits the Master's template and design.
4. `apply_resume_patch` on the copy. New list items in the operations already carry a UUID `id` and `hidden: false`; if RR reports a locked resume, tell the person and stop (never `unlock_resume` yourself).
5. If RR rejects an operation because the item shape differs from the instance's, `read_resume` the copy, pass the trimmed JSON (`data.summary`, first items of `data.sections.experience` and `data.sections.skills`) to `resume_patch` as `master_json`, and apply the fresh operations to a new copy. Do not hand-edit operations.
6. `download_resume_pdf` on the copy and give the person the link, noting it expires in 10 minutes. The resume itself stays in RR: that is where they edit the template, and changing it later is one click.

**Changes.** Edit the one bullet in `selection`, lint again with `resume_patch`, and apply the new operations to the same resume (`read_resume` the resume first if the person may have edited it, and show them what would be replaced). Do not create `v2` copies.

**The Master.** Only when the person asks to refresh it: build a `general` selection, run `resume_patch`, say what will be replaced, and apply it to the Master only after they say yes.

## Cover letters

The letter lives in RR's Cover Letters list, linked to the job's resume and its tracker row.

1. `lint_cover` (career-architect) checks the letter and returns `content_html`, `recipient_html` and `name`.
2. First time: `list_cover_letters` with the job's `resumeId` (or `applicationId`) to see whether one exists; if not, `create_cover_letter` with those fields, `resumeId` and `applicationId`. There is no id to keep: later runs find the letter the same way.
3. Later runs: `read_cover_letter` first, and compare it with the letter as `lint_cover` renders the current `cover` document (RR may reformat whitespace, so compare the words, not the bytes).
   - Same words: update it, passing the `revision` you just read as `expectedRevision`.
   - Different (the person edited it in RR): stop. Show what differs, fold the edits they want into `cover` so they pass `lint_cover`, then update. Never overwrite silently.
   - A revision conflict: read again and retry once; if it still conflicts, stop and tell the person.
4. Reading, renaming, duplicating and exporting saved letters (`list_cover_letters`, `read_cover_letter`, `duplicate_cover_letter`, `export_cover_letter`, `update_cover_letter` with `name` only) are fine on request. `read_cover_letter` returns HTML.
5. A letter the person wrote elsewhere and wants imported is theirs to import (`import_cover_letter` is not on the list). Its claims were never checked against their facts; say so if it comes up.

## Applications (the tracker)

One row per position. Look first, always.

- **Find a row.** `list_applications` has filters for `status`, `tags` and `includeArchived` only, and returns whole records. Each row this skill creates is tagged with the company slug (`fabrikam`), so look up with `tags: ["fabrikam"]` first; if that finds nothing, list with the narrowest `status` you can justify, and only then everything. Match on company and role wording: a different role at the same company is a different row.
- **Read** the row with `read_application` before changing it. It is context, not truth: check it against the current posting and the request, and overwrite what has changed.
- **Create** with `create_application` only when no row exists: company, role (the posting's own title), `status: saved`, the posting URL, `tags: [<company slug>]`, notes with the match score.
- **Update** with `update_application` and pass only what changed. Provided fields **replace** the old value, and that includes `contacts`, `tags` and `notes`: read the row first and send the merged list or text. Status is one of `saved`, `applied`, `screening`, `interview`, `offer`, `rejected`. `followUpAt` is an ISO 8601 timestamp. Withdrew or ghosted: `status: rejected`, `archived: true`, plus a note.
- **Timeline.** A dated event ("applied", "recruiter screen booked") goes in with `add_application_note` (`text`, optional `date` as YYYY-MM-DD). When the person says they applied, heard back, got a screen or an offer, update the row without being asked.
- **Research block.** The research procedure keeps one block in `notes`, starting `RESEARCH <YYYY-MM-DD>` on its own line. To refresh it: `read_application`, replace only that block in the text (a new block replaces the old one, everything else stays), send the merged `notes`.
- **Link the resume.** Set the row's resume to the tailored resume's id when both exist.
- **Contacts** are `{name, role, type}` with `type` of `hiring manager` or `recruiter`; leave email and phone empty. Send the existing contacts plus the new ones.
- `get_application_stats` gives pipeline counts.

Do not attach PDFs to applications (`attach_application_document` needs the file to pass through the conversation as base64); the row links to the resume instead.
