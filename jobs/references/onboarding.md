# Onboarding a new person

Use when the person has no `Career Architect` folder, or asks to set up their records. The goal is a workspace in their own Drive, a first set of atoms they confirmed, and a Master resume in Reactive Resume. Do it in short steps and say what each one creates. A first session usually covers steps 1 to 4; the rest can wait.

## 1. Confirm access before creating anything

- Drive: call `search_files` with `excludeContentSnippets: true` once. If it fails, the person has not connected Drive: tell them to connect it in their client's connector settings and stop.
- Reactive Resume: call `list_resumes`. If it fails, the person has not authorised Reactive Resume in their client (or the administrator has not given them access): say so and stop. Do not ask for an API key. Sign-in is through the account they use for the server.
- career-architect: call `info`. It answers with the server version and limits.

## 2. Create the workspace

Ask one question first: **where in your Drive should the `Career Architect` folder go?** (Default: My Drive.) Then create, with `create_file` and `mimeType application/vnd.google-apps.folder`:

`Career Architect`, and inside it `jobs` and `_history`.

Then create the documents from the templates in `assets/`, filled from the conversation:

| Document | Template | Fill with |
|---|---|---|
| `profile` | `assets/profile.md` | name, headline, contact, location, positioning. Leave `never_claim`, `known_gaps` and `pending` for step 4. |
| `rules` | `assets/rules.md` | Leave the headings; fill as the person states preferences. |
| `facts - shared` | `assets/facts-shared.md` | Credentials and education they give you. |

Each is a Google Doc from `text/plain`. Do not put anything in Drive that is not in the layout in `references/storage.md`.

## 3. Capture the history, one role at a time

Follow `workflows/intake.md` ("Capturing an atom"). For each role, save one `facts - <role-id>` document from `assets/facts-role.md`. Ask the person to paste an existing resume or LinkedIn export if they have one: read it once, propose atoms in their words, and let them confirm each. Mark anything they did not confirm `unconfirmed`.

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
