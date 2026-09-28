# Troubleshooting

Diagnose one step at a time, report the exact failing step, and stop. Do not retry in a loop, and never work around a failed check by skipping it.

| Symptom | Likely cause | What to do |
|---|---|---|
| No `career_architect__`, `google_` or `reactive_resume__` tools are listed | The person is not connected to the Jobs server, or their session started before they were given access | Say so and stop; the administrator checks the person's access in Obot (`docs/OPERATIONS.md`, "Onboard a person"). Some clients load tools on demand: search for the tool by name before deciding it is missing |
| Only some of the sources are listed (for example no `google_docs__` tools) | The Jobs server was changed after the session started, or that source's sign-in expired | Ask the person to reconnect the Jobs server (or start a new session). Meanwhile scoring by hand from the `skills` document is fine (state that `match` was not run); do not write a resume or letter |
| `career_architect__info` fails with an authorisation error | The server's shared secret changed | Administrator: `docs/OPERATIONS.md`, "Rotating the token" |
| A tool says a field is too long or a limit | 250,000 characters per document, 40 documents, 600,000 per call | Send fewer or only the cited fragments |
| "role ... is not in the facts you supplied" | A fragment was left out of `facts_docs` | Add the fragment that holds that role (see the `# Roles` table) |
| `build_index` reports `role id duplicate` or `atom id missing or duplicate` | Two fragments define the same id, usually a role saved twice | Find the older one in the folder, and move it to `_history` (rename only; never trash) |
| `build_index` reports YAML errors | A hand edit broke the syntax, or an alias (`&x`, `*x`) was used (not allowed) | Show the person the line; fix it in the fragment |
| A document looks garbled, wrapped or has a stray `---` at the top | It was read with `google_drive__read_file` (a PDF export), or Docs' leading section break was edited into the text | Read it with `google_docs__get_document`; run `normalize_text` with `source: docs` before editing |
| `AI/JobSearch` has two folders that could be the person, or two `AI` or `JobSearch` folders exist | A copy, a shared folder, or another exact-name match | Ask which; never merge them |
| Drive or Docs write refused | Read-only access to a shared folder, or the Google sign-in expired | Tell the person; they need edit access or a workspace of their own, or to reconnect Google |
| A new document sits in the root of My Drive | `create_document` always creates there and the move step failed | `google_drive__update_file` with `new_parent_id` set to the right folder |
| Reactive Resume tools fail with an authorisation error | The person has not signed in to Reactive Resume through the Jobs server, or their session expired | Have them reconnect Reactive Resume in the Jobs server's settings (Obot: connected servers). Never ask for a key |
| `apply_resume_patch` rejects an operation | The Master's item shape differs from the default | `references/reactive-resume.md`, "Resumes", step 5 |
| `update_cover_letter` reports a revision conflict | Saved elsewhere while you worked | Read again, retry once, then tell the person |
| `posting` says the id is not on the board | The posting closed or was renumbered | Try the company's own page; say which source each number came from |

Local maintainer mode has its own check command; see `references/local-mode.md`.
