# career-architect tools: reference

The `career_architect__*` tools of the Jobs toolset (names below are the bare tool names). Stateless: every check is a pure function of the documents you give it. Nothing is stored, nothing is read from Drive or Reactive Resume, and the person's documents are not logged. `posting` reads public job boards; the `records_*` tools and the path arguments read and save files in the person's own GitHub records repository (`references/storage-github.md`); nothing else leaves the server. Tools return `ok`, `errors` and `warnings` counts and an `issues` list of `{level, where, message}` (`E` blocks, `W` is advice).

**Document arguments** (`text`, `skills_md`, `profile_md`, `selection_yaml`, `cover_yaml`, `facts_docs`, `master_json`) take the document exactly as `google_docs__get_document` returned it (`markdown_content`); the server removes the section-break line Docs adds, and also undoes the escaping of other Drive readers. Copy verbatim. Limits: 250,000 characters per document, 40 documents, 600,000 characters per call.

**Path arguments (records on GitHub).** Beside each document argument there is a path argument (`skills_path`, `profile_path`, `selection_path`, `cover_path`, `posting_path`, and the list `facts_paths`), plus `repo` and `ref`. For a person whose records are on GitHub, pass paths and leave the text empty: the server reads the files, and the answer carries `records_commit`, which you pass as `ref` to later calls in the same task. `facts_paths: ["facts/"]` means every file in the folder. Text and paths can be mixed for facts (an unsaved edit as text, the rest as paths).

**Which facts fragments to send.** `build_index` needs all of them. `lint_resume`, `lint_cover` and `resume_patch` need only the fragments that hold the roles the selection cites, plus `facts - shared` (credentials and education are printed on the resume). Use the `# Roles` table in `skills` to pick them. Missing one shows up as "role ... is not in the facts you supplied" or an unknown atom id.

| Tool | Use it to | Inputs | Returns |
|---|---|---|---|
| `info` | check the connection | none | version, limits, the date used for "present" |
| `guide` | read the skill's own documents from the server, so no local copy is needed and the version is always current | optional `topic` (`start`, or a document path such as `workflows/score.md` or `references/storage.md`; the `.md` is optional) | `text`, `skill_version`, `topics` |
| `normalize_text` | get clean, editable text from a document you read, before you edit it yourself | `text`, optional `source` (`docs` for Google Docs, `auto`, `drive_read`, `base64`, `plain`) | `text` |
| `build_index` | validate facts and generate the `skills` document | `facts_docs` (all fragments) | `ok`, `skills_md`, counts; or `errors` |
| `match` | score a posting's requirements | `skills_md`, `profile_md`, `requirements` | `table`, `ceiling`, `ceiling_if_every_unasked_is_met`, `rows` (status `met`, `partial`, `short`, `adjacent`, `gap` or `unasked`), `ask` |
| `lint_resume` | check a resume selection | `selection_yaml`, `skills_md`, `profile_md`, `facts_docs` | issues, `resume_text` |
| `lint_cover` | check a cover letter | `cover_yaml`, `skills_md`, `profile_md`, `facts_docs`, `posting_text` | issues, `cover_text`, `recipient_html`, `content_html`, `name` |
| `resume_patch` | turn a clean selection into Reactive Resume operations | the `lint_resume` inputs, optional `master_json` | `operations`, `resume_name` (at most 64 characters), `resume_name_full`, `resume_slug`, `resume_text`; no operations while there are errors |
| `posting` | read pay, reports-to and description from a public posting | `url` (Ashby, Greenhouse or Lever) | title, pay, reports-to, date, `text`. `pay` is empty when the posting states none |
| `records_status` | tell whether the person's records are on GitHub, and check that connection | optional `repo` | `mode`, `reachable`, `repo`, `commit`, header names that arrived (never values), `problem` |
| `records_list` | list one folder of the GitHub records repository | optional `folder`, `repo`, `ref` | `records_commit`, `items` (path, file or folder, `sha`) |
| `records_read` | read record files when you need their words | `paths` (a path ending in `/` reads the folder), optional `repo`, `ref` | `records_commit`, `files` (path, `text`, `sha`) |
| `records_write` | save one whole record file, plain text, as a new commit | `path`, `text`, `sha` as read (empty only for a new file), `message`, optional `repo` | `path`, new `sha`, `commit`, `created`; refused when the file changed since you read it |

Errors that are the caller's to fix come back as a plain message (a field named, a limit named). "internal error ... Tell the administrator" means a bug: report it, do not retry with different data.

## Requirements string for `match`

`tag[:must|nice[:min_years]]`, comma separated, for example `okta:must:5,jamf:must,terraform:nice`. A missing level is `must`, so always write it.

- Use the tag names in `skills`; aliases resolve. A tag the index does not have can only come back `unasked`, so map "identity providers" to the person's IdP tag and "lifecycle automation" to their lifecycle tag before inventing a name.
- "Required, must have, X+ years", and the bullets under "you have / what you bring", are `must`. "Preferred, nice to have, bonus, helpful, not required" are `nice`. "X+ years or equivalent experience" is `nice` with the years.
- One requirement per posting bullet, about 12 musts at most. "Such as A, B or C" is one requirement: the listed one the person has, or the first.
- Include checkable soft requirements (people management, a compliance framework, a clearance, a degree, a certification). Leave out qualities records cannot show (communication, judgment, problem solving, testing).

How `match` scores: must-haves gate the ceiling, nice-to-haves only add to it (all musts met is 8, 9 or 10 by how many extras are covered). `adjacent` means no evidence for the tag itself but hands-on evidence for a tool that does the same job (Kandji for Jamf, Tines for Okta Workflows), from built-in peer groups plus the person's `related` map in `facts - shared`. It scores as partial, is listed in `ask`, and is never claimed. `never_claim` and `known_gaps` always win over it.

## Selection document (`selection`)

```yaml
target: {company: Fabrikam, role: Systems Engineer}   # role is the posting's own title; both required
summary: "Two sentences at most."
skills:                       # display order; each item must exist in the skills index
  - {name: Identity, items: [Okta, SCIM]}
roles:                        # ids and titles come from the facts; you choose the bullets
  - id: northwind-se
    bullets:
      - {atom: nw-01, text: "the bullet"}     # one atom per bullet; atoms: [a, b] to combine two
```

## Cover letter document (`cover`)

```yaml
target: {company: Fabrikam, role: Systems Engineer}
recipient: ["Hiring Manager", "Fabrikam"]     # address-block lines; a real name if the posting gives one
salutation: "Dear Hiring Manager,"            # optional
paragraphs:
  - {jd: true, text: "About the company or role, from the posting only. No claims about the person."}
  - {atoms: [nw-02, nw-05], text: "A claim about the person; cite the atoms that back it."}
closing: "Sincerely,"                         # optional; the signature is the name in profile
```

A paragraph without atoms must be `jd: true`. Pass the posting text as `posting_text` so statements about the company can be checked.
