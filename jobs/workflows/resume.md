# Tailored resume

Reactive Resume (RR) does the layout. Your only prose output is the summary and the bullets in the selection. Storage: `references/storage.md`; RR calls: `references/reactive-resume.md`; server tools: `references/tools.md`.

0. Read `rules`, `profile` and `skills` from the workspace. `rules` holds the standing wording rules (years framing, allowed title framings, scope limits) that override style preferences.
1. **Slug** = `company-role` in kebab-case. For an all-purpose resume use the slug `general`, target company `General Purpose`, and skip `jd`. Save the posting text as `jobs/<slug>/jd` (with its URL and date on the first two lines) so the tracker and later interview prep have it.
   `target.company` and `target.role` are both required, and `role` is the posting's own job title: they become the resume's name (`Company - Role - Person Resume`).
2. Extract requirement tags as in `score.md` (reuse them if you already scored this posting).
3. **Choose the roles to read.** Always the two most recent roles; add any role the `skills` index shows holds atoms for the requested tags (the `# Roles` table maps atoms to roles). Read those `facts - <role id>` fragments and `facts - shared`. That is all you read of the person's history.
   Candidate atoms are the `verified` and `needs_number` ones. Respect each atom's `note` and `only_for`.
4. **Write the selection** (format in `references/tools.md`). Pick 4 to 6 bullets for the two most recent roles and 2 to 3 for older ones; drop roles the posting does not care about.
   Lead each role with what the posting asks for. Use the posting's own terms only where the atom supports them. Follow `style/voice.md`. Skills you list must exist in `skills`.
5. **Check it:** `resume_patch` with the selection, `skills_md`, `profile_md` and the fragments you read plus `facts - shared`. Fix every `E`. Read the `W` lines and fix the real ones (banned phrases, dashes, repeated openers).
   "adds wording the atom never used" means the bullet may state something the person never said (an outcome, a reason, a scope). Cut it, or ask the person and put the fact in the atom first.
   Read `resume_text` once for a sense of the whole document.
6. **Publish to Reactive Resume:** duplicate the Master with the returned `resume_name` and `resume_slug`, apply the returned `operations` to the copy, then get the PDF link (`references/reactive-resume.md`, "Resumes"). Tell the person the link expires in 10 minutes and that the resume stays in RR, where a template change is one click.
7. **Save the selection** as `jobs/<slug>/selection` in Drive (`references/storage.md`, "Write"), and record the decision in the tracker (below).
8. **Changes:** edit the one bullet in the selection, run `resume_patch` again, and apply the new operations to the same RR resume. If the change is a fact ("it was 1,800 devices, not 1,200"), fix the atom in its fragment first (`workflows/intake.md`), then update the selection.

If a step fails on a connection, use `references/troubleshooting.md`, report the exact failing step, and offer `resume_text` in the chat as the fallback. Do not retry in a loop.

## Tracker
When the person decides to apply (or the resume is made), make sure the posting has a row: look for one (`references/reactive-resume.md`, "Applications"), create it if there is none with status `saved`, the posting URL, tags `[<company slug>]`, and the match score in the notes, and link the tailored resume. When the person says they applied, heard back, got a screen or an offer, update the row without being asked. One row per position; the full research procedure is `workflows/research.md`.
