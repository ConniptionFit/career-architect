# career-architect tools: reference

The `career_architect__*` tools of the Jobs toolset (names below are the bare tool names). Stateless: every tool is a pure function of the text you give it. Nothing is stored, nothing is read from Drive or Reactive Resume, and the person's documents are not logged. All of them except `posting` never leave the server. Tools return `ok`, `errors` and `warnings` counts and an `issues` list of `{level, where, message}` (`E` blocks, `W` is advice).

**Document arguments** (`text`, `skills_md`, `profile_md`, `selection_yaml`, `cover_yaml`, `facts_docs`, `master_json`) take the document exactly as `google_docs__get_document` returned it (`markdown_content`); the server removes the section-break line Docs adds, and also undoes the escaping of other Drive readers. Copy verbatim. Limits: 250,000 characters per document, 40 documents, 600,000 characters per call.

**Which facts fragments to send.** `build_index` needs all of them. `lint_resume`, `lint_cover` and `resume_patch` need only the fragments that hold the roles the selection cites, plus `facts - shared` (credentials and education are printed on the resume). Use the `# Roles` table in `skills` to pick them. Missing one shows up as "role ... is not in the facts you supplied" or an unknown atom id.

| Tool | Use it to | Inputs | Returns |
|---|---|---|---|
| `info` | check the connection | none | version, limits, the date used for "present" |
| `normalize_text` | get clean, editable text from a document you read, before you edit it yourself | `text`, optional `source` (`docs` for Google Docs, `auto`, `drive_read`, `base64`, `plain`) | `text` |
| `build_index` | validate facts and generate the `skills` document | `facts_docs` (all fragments) | `ok`, `skills_md`, counts; or `errors` |
| `match` | score a posting's requirements | `skills_md`, `profile_md`, `requirements` | `table`, `ceiling`, `ceiling_if_every_unasked_is_met`, `rows`, `ask` |
| `lint_resume` | check a resume selection | `selection_yaml`, `skills_md`, `profile_md`, `facts_docs` | issues, `resume_text` |
| `lint_cover` | check a cover letter | `cover_yaml`, `skills_md`, `profile_md`, `facts_docs`, `posting_text` | issues, `cover_text`, `recipient_html`, `content_html`, `name` |
| `resume_patch` | turn a clean selection into Reactive Resume operations | the `lint_resume` inputs, optional `master_json` | `operations`, `resume_name` (at most 64 characters), `resume_name_full`, `resume_slug`, `resume_text`; no operations while there are errors |
| `posting` | read pay, reports-to and description from a public posting | `url` (Ashby, Greenhouse or Lever) | title, pay, reports-to, date, `text`. `pay` is empty when the posting states none |

Errors that are the caller's to fix come back as a plain message (a field named, a limit named). "internal error ... Tell the administrator" means a bug: report it, do not retry with different data.

## Requirements string for `match`

`tag[:must|nice[:min_years]]`, comma separated, for example `okta:must:5,jamf:must,terraform:nice`. Use the tag names in `skills`; aliases resolve. "Required, must have, X+ years" is `must`; "preferred, nice to have, bonus" is `nice`. Include checkable soft requirements (people management, a compliance framework, a clearance, a degree, a certification).

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
