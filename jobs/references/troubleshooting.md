# Troubleshooting

Diagnose one step at a time, report the exact failing step, and stop. Do not retry in a loop, and never work around a failed check by skipping it.

| Symptom | Likely cause | What to do |
|---|---|---|
| A career-architect tool is not listed | The server is not enabled for the person, or the session started before it was added | Say so; the person or administrator enables it in Obot. Meanwhile: scoring by hand from the `skills` document is fine (state that `match` was not run); do not write a resume or letter |
| `info` fails with an authorisation error | The server's shared secret changed | Administrator: `docs/OPERATIONS.md`, "Rotating the token" |
| A tool says a field is too long or a limit | 250,000 characters per document, 40 documents, 600,000 per call | Send fewer or only the cited fragments |
| "role ... is not in the facts you supplied" | A fragment was left out of `facts_docs` | Add the fragment that holds that role (see the `# Roles` table) |
| `build_index` reports `role id duplicate` or `atom id missing or duplicate` | Two fragments define the same id, usually a role saved twice | Find the older one in the folder, and move it to `_history` (rename only; never trash) |
| `build_index` reports YAML errors | A hand edit broke the syntax, or an alias (`&x`, `*x`) was used (not allowed) | Show the person the line; fix it in the fragment |
| A document looks doubled, escaped or base64 | Drive connector output pasted where clean text was needed | Run `normalize_text`; edit the result |
| Drive search finds two `Career Architect` folders | A copy or a shared folder | Ask which; never merge them |
| Drive write refused | Read-only access to a shared folder | Tell the person; they need edit access or a workspace of their own |
| Reactive Resume tools fail with an authorisation error | The person has not authorised the server in their client, or their session expired | Have them re-authorise Reactive Resume in the client's connector settings. Never ask for a key |
| `apply_resume_patch` rejects an operation | The Master's item shape differs from the default | `references/reactive-resume.md`, "Resumes", step 5 |
| `update_cover_letter` reports a revision conflict | Saved elsewhere while you worked | Read again, retry once, then tell the person |
| `posting` says the id is not on the board | The posting closed or was renumbered | Try the company's own page; say which source each number came from |

Local maintainer mode has its own check command; see `references/local-mode.md`.
