# Storage protocol: the person's Google Drive

The person's records are Google Docs holding plain text, in one folder they own, at a **fixed location**: `AI/JobSearch/<their name>`, the same path in every deployment of this skill. It is fixed so the location never has to be searched for or guessed, and so several people signed into the same Drive (a family, a shared account) each get their own folder instead of colliding on one generic name. They are read and written through the Jobs toolset's Google Docs and Google Drive tools, which act as the signed-in person. The career-architect tools never see Drive; you read a document and pass its text to them.

Tools used (full names as the Jobs toolset lists them; a client may put its own prefix in front):

| Tool | For |
|---|---|
| `google_drive__list_files` | find the workspace folder; list a folder (`parent_id`) with each document's id and `modifiedTime` |
| `google_drive__get_file` | one file's metadata, to check `modifiedTime` before a write |
| `google_drive__create_folder` | create the workspace folders (onboarding, a new job) |
| `google_drive__update_file` | move a document into its folder; rename and move a superseded one to `_history` |
| `google_docs__get_document` | read a document: `title`, `markdown_content`, `revision_id` |
| `google_docs__create_document` | create a document with a `title` and plain-text `initial_content` |
| `google_docs__replace_text` | change one line of a document in place |
| `google_docs__append_text` | add text at the end of a document |
| `google_drive__read_file` | only to read a file the person uploaded (an old resume, PDF or Word) when they ask you to import it |

Nothing else exists in the toolset, and you do not look for another way: no deleting, sharing or permission changes (SKILL.md rule 11).

## Layout

```
AI/                                folder, fixed: the same top-level name in every deployment
  JobSearch/                       folder, fixed: everything this skill keeps lives under here
    <name>/                        folder per person, named after them (John's is `John`); the workspace
      profile                      YAML front matter + notes (identity, never_claim, known_gaps, pending, RR Master id)
      rules                        standing wording rules (years framing, titles, voice, scope limits)
      skills                       GENERATED index from build_index; never edited by hand
      facts - shared               aliases, credentials, education, log
      facts - <role-id>            one document per role: its atoms (role id = the `id` field, kebab-case)
      jobs/                        folder
        <slug>/                    folder per posting (slug = company-role, kebab-case)
          jd                       the posting text
          selection                the resume selection (YAML), once written
          cover                    the cover letter (YAML), once written
      _history/                    folder; superseded versions of any document, never deleted by this skill
```

Why one document per role: a whole career runs to tens of kilobytes, and a resume needs two or three roles. The `skills` index carries what scoring and linting need (years, depth, evidence atom ids, aliases, credentials, career length) plus a `# Roles` table saying which role holds which atom, so a task opens only the fragments it cites.

Every document is a Google Doc holding plain text. Titles are exact and case-sensitive.

## Find the workspace

The parent path is fixed, so it is found (or made), never searched for by content:

1. `google_drive__list_files` with `parent_id: root`, `mime_type: application/vnd.google-apps.folder`, `file_name_contains: AI`. Names match as substrings (so this can also return unrelated folders such as "Google AI Studio"): keep only a result named exactly `AI`. None: `google_drive__create_folder(folder_name: "AI")`.
2. The same inside it for `JobSearch` (`parent_id: <AI folder id>`): find the exact match or create it.
3. List `JobSearch` (`parent_id: <JobSearch folder id>`, `mime_type: application/vnd.google-apps.folder`): these are the people who already have a workspace here. Zero: this is a new person, follow `references/onboarding.md`. One: that is the workspace; note its id and name. Several: list the names and ask which one is them, or whether to make a new one.
4. List the workspace folder with `parent_id: <its id>`; add `file_name_contains` for one document (`profile`, `facts - `; remember `facts` also matches `facts - shared`). Ids are stable: keep them for the rest of the task instead of searching again. The `jobs` folder holds one folder per posting; list `jobs` to find a slug, then list that folder.

Never search the person's whole Drive (no `parent_id`) to find any of this: the fixed path means you never need to.

If the workspace folder was shared with the person rather than owned by them, reading works and writing needs the owner's permission. Say so instead of retrying.

## Read

`google_docs__get_document(document_id)` returns `markdown_content`: the document text as written, with no escaping, except that Google Docs puts a `---` line first (a section break). The career-architect tools remove it. So:

- **Pass `markdown_content` to the career-architect tools exactly as it came.** Do not tidy it first; a "tidy" copy is where a fact gets changed.
- **When you are going to edit a document's text yourself,** call `normalize_text` with `source: docs` on it first, edit the clean text it returns, and write that.
- Never read a workspace document with `google_drive__read_file`. Drive exports a Google Doc to PDF for that tool and the text comes back wrapped and garbled.

Copy documents into tool arguments verbatim. Do not summarise, reorder or drop lines; the checks are only as good as the text they get. If a check says an atom or role is missing, first suspect that you passed the wrong or a truncated fragment.

Note each document's `modifiedTime` (from `list_files`) when you read it. You need it to detect a concurrent edit before you write.

## Write

Two kinds of write, chosen by size. Both start with the same first two steps.

1. **Validate first.** A facts change is checked before it is saved: run `build_index` on the complete new set of fragments and continue only when `ok` is true. A selection or letter is saved after `lint_resume` / `lint_cover` shows no errors, or explicitly marked as a draft in its title (`selection (draft)`).
2. **Check for a concurrent edit.** `google_drive__get_file` on the current document. If its `modifiedTime` is later than the one you noted when you read it, someone (or another session) changed it: re-read it, merge, and show the person what differs before saving.

### A new version (a whole document, or any change of more than a line)

Nothing is deleted, and at no moment is there no current document.

3. `google_docs__create_document` with the exact `title` and the clean text as `initial_content`. Never send text you read without `normalize_text` if you edited it.
4. The new document is created in the root of My Drive. Move it now: `google_drive__update_file(file_id: <new id>, new_parent_id: <the folder>)`.
5. Retire the old version: `google_drive__update_file(file_id: <old id>, new_name: "<title> (superseded YYYY-MM-DD HHMM)", new_parent_id: <_history folder id>)`. One call renames and moves.
6. Regenerate the index after any facts change (below).

If step 3 succeeded and step 4 or 5 failed, two documents share a title, or one sits in the wrong folder. Readers use the one in the workspace folder with the latest `modifiedTime`; finish the move or rename when you notice, and mention it.

### One line (a corrected wording, a number, a tag)

3. Confirm from the text you read that the exact line occurs once in the document (count it), and show the person the old and new line.
4. `google_docs__replace_text(document_id, find_text, replace_text)` with `find_text` a single line's worth of text (no line breaks) that occurs once. Google keeps the earlier version in the document's version history. Read the document again and check the change landed where intended.
5. Regenerate the index after any facts change.

Never use `replace_text` to rewrite several lines or to add or remove an atom: that is a new version.

### The index

After any facts change, run `build_index` over all fragments and write the returned `skills_md` as `skills` with a new version. The index is a cache; a stale one makes scores wrong, so do this in the same task as the facts change. Tell the person, in one line, what was saved and where.

Sending less: a change to one atom rewrites one role's fragment, not the whole career. Keep fragments to about one role each; split a role only if it passes about 25 atoms.

## Document formats

- `profile`, `rules`: markdown. `profile` starts with a `---` YAML front matter block (see `assets/profile.md`); `rules` is plain markdown (see `assets/rules.md`).
- `facts - shared`, `facts - <role-id>`: plain YAML slices of the facts schema (see `assets/facts-shared.md` and `assets/facts-role.md`). A fenced ```yaml block is accepted too. A role atom id is unique across every fragment; the index build reports duplicates.
- `skills`: exactly what `build_index` returned in `skills_md`.
- `jd`: the posting text, plus its URL and date on the first two lines.
- `selection`, `cover`: the YAML documents the workflows describe.

Write documents as plain paragraphs: no bold, headings, bullets or tables applied in Docs. `get_document` turns those into markdown marks (`**`, `#`, `-`) and a YAML fragment must read back exactly as it was written. A person who opens a document to look is welcome; if they format one, tell them it will read back with extra marks.

## Limits the server enforces

250,000 characters per document, 40 documents and 600,000 characters per call. A tool call that exceeds them fails with the limit named; send fewer fragments (only the cited roles), not a truncated one.

## What is never stored in Drive

Resumes, PDFs and saved cover letters (RR), API keys or tokens (nowhere), and anything about a person other than the account owner.
