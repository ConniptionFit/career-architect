# Cover letter

A finished letter lives in Reactive Resume (RR) as its own entry in **Cover Letters**, linked to the job's resume and its tracker row; the person opens and edits it there. The job's tailored resume must exist first (`workflows/resume.md`). Storage: `references/storage.md`; RR calls: `references/reactive-resume.md`, "Cover letters".

0. Read `rules`, `profile` and `skills`, and the job's `jd` (or the posting the person pasted).
1. Read the fragments that hold the atoms you will cite (start from the atoms the resume used).
2. Write the letter as a `cover` document (format in `references/tools.md`). Three short paragraphs: why this company, using specifics from the posting; the one or two strongest atoms for this role; a brief plain close.
   Roughly 150 to 300 words. Same atoms-only rule and voice rules (`style/voice.md`); a paragraph without atoms must be `jd: true`.
3. `lint_cover` with the letter, `skills_md`, `profile_md`, the cited fragments plus `facts - shared`, and the posting text. Fix every `E`; fix the `W` lines that are real. Read `cover_text` once.
4. Create or update the saved letter as `references/reactive-resume.md` describes: look for an existing letter for the job's resume, read it before updating, pass the revision, and never overwrite the person's own edits.
5. Save the letter as `jobs/<slug>/cover` in Drive (`references/storage.md`, "Write"), and give the person the RR link. The person downloads the letter's PDF from Reactive Resume > Cover Letters; the resume's PDF link comes from `download_resume_pdf`.
6. **Edits:** change one paragraph in `cover`, run `lint_cover`, and update the same saved letter in place. The letter's name is not touched on update, so a rename made in RR is kept.

The letter is generated with a letterhead (name, email, phone, location from `profile`), today's date and the recipient block. Its text is what `lint_cover` returned, so the atoms check applies to everything that reaches RR.
