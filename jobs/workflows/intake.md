# Intake and updates

Where things are saved: `references/storage.md`. First-time setup, workspace creation and the Master resume: `references/onboarding.md`. Templates for each document are in `assets/`.

A change to the facts is always the same four steps: edit the role's fragment (clean text: `normalize_text` first), run `build_index` over all fragments and fix any error, save the fragment as a new version, save the returned `skills_md` as the new `skills`. Do all four in the same task, and tell the person in one line what changed.

## Capturing an atom
Ask about one role at a time. For each accomplishment get: what they did in their own words (this becomes `say`), the tools (`tags`), how deep it went
(`exposure` read a dashboard, `used` did it, `owned` was the person responsible, `designed` chose the approach), any figures (`nums`), and whether it is confirmed.
Keep `say` to one plain sentence. Do not polish it; the polish comes later and the plain version is what keeps resumes sounding like the person.
`status`: `verified` (they confirmed it), `needs_number` (real, but a claim like "saved thousands of hours" has no source figure), `unconfirmed`, `excluded`.
Atom ids are unique across all fragments: a short role prefix and a number (`nw-01`). Add a dated line to `log:` in `facts - shared` for each session. Fix mistakes by editing the atom, not by adding a correction beside it.

If they state a fact but not which job or what they did, do not guess a role. Write it under `pending:` in `profile` in their words, ask the two missing questions (which job, what they did), and turn it into an atom when answered.

Always ask: **"Is there anything you do not want claimed or implied, even if it is adjacent to real experience?"** Record the answers in `never_claim` in `profile`. Ask what requirements they know they lack and record them in `known_gaps`.

## New role
Create `facts - <role-id>` from `assets/facts-role.md` (id, title, org, span, context, atoms). A new job is a new document; the older roles are not touched.

## Migrating an existing profile or resume (once)
Read the source a single time. Do not open archived or superseded versions, or every old resume.
- Verified accomplishments become atoms with `status: verified`. Their exact wording goes into `say`.
- "Treat with caution" items become `needs_number` atoms.
- Excluded or unconfirmed items become atoms with the matching status (keep them so they are not rediscovered and re-asked).
- Explicit tool or skill exclusions become `never_claim`. Known gaps become `known_gaps`.
- Standing wording instructions do not become atoms: they go into `rules`, and absolute prohibitions into `never_claim`.
- Work environment constraints and positioning go into the body of `profile`. Certifications go into `credentials` in `facts - shared`.
Then build the index and show the person the generated `skills` to sanity check the years.

## Reconciling several source documents
- A claim that recurs, worded differently, across independently written documents is trustworthy.
- A claim found in one document only, or one whose dates clash with a role already confirmed, is `unconfirmed`. Ask the person next time; do not merge it silently or drop it silently.
- An unquantified superlative ("impacted the entire workforce") usually got embellished along the way. Keep the underlying accomplishment, mark it `needs_number`, and ask for the real figure.
- When they settle something, update the atom's status and add a line to `log:`.
