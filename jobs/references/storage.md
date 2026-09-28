# Storage protocol: the person's Google Drive

The person's records are Google Docs holding plain text, in one folder they own. The Drive connector is the only way they are read or written. The career-architect server never sees Drive; you read a document and pass its text to a tool.

Connector tools used: `search_files`, `read_file_content`, `create_file`, `update_file` (title and parent only), `get_file_metadata`. Nothing else. Never call `trash_file`, `share_file` or anything that changes permissions (SKILL.md rule 11).

## Layout

```
Career Architect/                 folder, marker of the workspace; lives anywhere in the person's Drive
  profile                         YAML front matter + notes (identity, never_claim, known_gaps, pending, RR Master id)
  rules                           standing wording rules (years framing, titles, voice, scope limits)
  skills                          GENERATED index from build_index; never edited by hand
  facts - shared                  aliases, credentials, education, log
  facts - <role-id>               one document per role: its atoms (role id = the `id` field, kebab-case)
  jobs/                           folder
    <slug>/                       folder per posting (slug = company-role, kebab-case)
      jd                          the posting text
      selection                   the resume selection (YAML), once written
      cover                       the cover letter (YAML), once written
  _history/                       folder; superseded versions of any document, never deleted by this skill
```

Why one document per role: a whole career runs to tens of kilobytes, and a resume needs two or three roles. The `skills` index carries what scoring and linting need (years, depth, evidence atom ids, aliases, credentials, career length) plus a `# Roles` table saying which role holds which atom, so a task opens only the fragments it cites.

Every document is a Google Doc created from `text/plain`. Titles are exact and case-sensitive.

## Find the workspace

1. `search_files` with `query: title = 'Career Architect' and mimeType = 'application/vnd.google-apps.folder'` and `excludeContentSnippets: true`.
2. One result: that is the workspace. Note its id. Several: list them with their owner and last-modified time and ask which one. None: onboarding (`references/onboarding.md`).
3. List a folder's contents with `parentId = '<folder id>'` (add `and title = 'profile'` for a single document). A folder id is stable; remember it for the rest of the task instead of searching again.

If the folder was shared with the person rather than owned by them, reading works and writing needs the owner's permission. Say so instead of retrying.

## Read

`read_file_content(fileId)` returns the document as markdown text: punctuation is backslash-escaped and every line is followed by a blank line. Two consequences:

- **Pass documents to the career-architect tools as they came.** The server cleans them (`normalize_text` is applied to every document argument). Do not tidy them yourself first; a "tidy" copy is where a fact gets changed.
- **When you are going to edit a document,** call `normalize_text` on it first and edit the clean text it returns. Never edit the escaped text.

Copy documents into tool arguments verbatim. Do not summarise, reorder or drop lines; the checks are only as good as the text they get. If a check says an atom or role is missing, first suspect that you passed the wrong or a truncated fragment.

Note each document's `modifiedTime` (from `search_files` or `get_file_metadata`) when you read it. You need it to detect a concurrent edit before you write.

## Write: versioned, never in place

The connector cannot change a document's content (`update_file` changes the title or parent only), so a write is "create the new version, then retire the old one". Nothing is deleted, and at no moment is there no current document.

1. **Validate first.** A facts change is checked before it is saved: run `build_index` on the complete new set of fragments and continue only when `ok` is true. A selection or letter is saved after `lint_resume` / `lint_cover` shows no errors, or explicitly marked as a draft in its title (`selection (draft)`).
2. **Check for a concurrent edit.** `get_file_metadata` on the current document. If its `modifiedTime` is later than the one you noted when you read it, someone (or another session) changed it: re-read it, merge, and show the person what differs before saving.
3. **Create the new version:** `create_file` with `title` (the exact document title), `parentId`, `textContent`, `contentMimeType: text/plain`. Send clean text, never text you got from `read_file_content` without `normalize_text`.
4. **Retire the old version:** `update_file(fileId: <old id>, title: "<title> (superseded YYYY-MM-DD HHMM)", parentId: <_history folder id>)`. One call sets both the title and the folder; if the move is refused, rename only.
5. **Regenerate the index** after any facts change: `build_index` over all fragments, then write the returned `skills_md` as `skills` with steps 2 to 4. The index is a cache; a stale one makes scores wrong, so do this in the same task as the facts change.
6. Tell the person, in one line, what was saved and where.

If step 3 succeeded and step 4 failed, two documents share a title. Rule for readers: use the one with the latest `modifiedTime`; finish the rename when you notice, and mention it.

Sending less: a change to one atom rewrites one role's fragment, not the whole career. Keep fragments to about one role each; split a role only if it passes about 25 atoms.

## Document formats

- `profile`, `rules`: markdown. `profile` starts with a `---` YAML front matter block (see `assets/profile.md`); `rules` is plain markdown (see `assets/rules.md`).
- `facts - shared`, `facts - <role-id>`: plain YAML slices of the facts schema (see `assets/facts-shared.md` and `assets/facts-role.md`). A fenced ```yaml block is accepted too. A role atom id is unique across every fragment; the index build reports duplicates.
- `skills`: exactly what `build_index` returned in `skills_md`.
- `jd`: the posting text, plus its URL and date on the first two lines.
- `selection`, `cover`: the YAML documents the workflows describe.

Drive's connector coerces content that looks like a spreadsheet formula or a date when it is stored in a Sheet. That is why nothing here is a Sheet.

## Limits the server enforces

250,000 characters per document, 40 documents and 600,000 characters per call. A tool call that exceeds them fails with the limit named; send fewer fragments (only the cited roles), not a truncated one.

## What is never stored in Drive

Resumes, PDFs and saved cover letters (RR), API keys or tokens (nowhere), and anything about a person other than the account owner.
