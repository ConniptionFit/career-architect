# Onboarding a new person

Use when the person has no workspace folder under `AI/JobSearch` (`references/storage.md`, "Find the workspace"), or asks to set up their records. The goal is a workspace in their own Drive, a first set of atoms they confirmed, and a Master resume in Reactive Resume. Do it in short steps and say what each one creates. A first session usually covers steps 1 to 4; the rest can wait.

## 1. Confirm access before creating anything

- Drive and Docs: call `google_drive__list_files` with `max_results: 1` once. If it fails with an authorisation error, the person has not connected their Google account to the Jobs server: tell them to open the Jobs server in their client (or Obot) and connect Google Drive and Google Docs, then stop.
- Reactive Resume: call `reactive_resume__list_resumes`. If it fails, the person has not signed in to Reactive Resume through the Jobs server (or the administrator has not given them an account): say so and stop. Do not ask for an API key. Sign-in is through the account they use for the server.
- career-architect: call `career_architect__info`. It answers with the server version and limits.

If none of these tools exist, the person is not connected to the Jobs server at all: point them to the setup steps for their client and stop. Do not fall back to local mode unless they ask.

## 2. Create the workspace

The location is fixed (`references/storage.md`, "Find the workspace"): `AI/JobSearch/<their name>`, found or created the same way for everyone. Ask one question first: **what's your first name (or what would you like your folder called)?** Then, inside `JobSearch`, create with `google_drive__create_folder` (`parent_id` for the inner ones):

`<their name>`, and inside it `jobs` and `_history`. If a folder with that name already exists there and is not them (check `profile` inside it), ask for a different name.

Then create the documents from the templates in `assets/`, filled from the conversation:

| Document | Template | Fill with |
|---|---|---|
| `profile` | `assets/profile.md` | name, headline, contact, location, positioning. Leave `never_claim`, `known_gaps` and `pending` for step 4. |
| `rules` | `assets/rules.md` | Leave the headings; fill as the person states preferences. |
| `facts - shared` | `assets/facts-shared.md` | Credentials and education they give you. |

Create each with `google_docs__create_document` and move it into the folder with `google_drive__update_file` (`references/storage.md`, "A new version", steps 3 and 4). Do not put anything in Drive that is not in the layout there.

## 3. Capture the history, one role at a time

Follow `workflows/intake.md` ("Capturing an atom"). For each role, save one `facts - <role-id>` document from `assets/facts-role.md`. Ask the person to paste an existing resume or LinkedIn export, or to point at one already in their Drive (`google_drive__read_file` reads an uploaded PDF or Word file): read it once, propose atoms in their words, and let them confirm each. Mark anything they did not confirm `unconfirmed`.

After every role: run `build_index` on all fragments so far. If it returns errors, fix them before saving anything. Then save `skills` (`references/storage.md`, "Write").

Always ask: **"Is there anything you do not want claimed or implied, even if it is adjacent to real experience?"** Record the answers in `never_claim`. Ask which requirements they know they lack, and record them in `known_gaps`.

## 4. Reactive Resume Master

The Master is the styled resume every tailored resume is copied from, so its template and design carry over.

- If the person already has a resume in RR they like: `list_resumes`, and record that id in `profile` as `rr_master`.
- If not: tell them to create or import one in Reactive Resume and choose its template and design, then come back. Creating a resume from scratch through the assistant is not part of this skill (SKILL.md rule 13).
- Put the Master's id in `profile` under `rr_master`. Never edit the Master without being asked.

## 5. Hand over

Show them, in a short list: what is in the workspace, which facts are `unconfirmed` and need an answer, and the three things they can now ask for: score a posting, a tailored resume, a cover letter. Tell them Drive is theirs: they can open any document, and old versions are in `_history`.

## What you must not do here

- Do not create anything outside the layout, in another folder, or in a shared drive unless they ask.
- Do not import documents you were not given. Read only what the person points at.
- Do not fill facts from your general knowledge of what a person in their field "probably did".
- Do not set up a second workspace for the same person. If a workspace exists, use it.
