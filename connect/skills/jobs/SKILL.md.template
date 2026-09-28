---
name: jobs
description: Career assistant that scores job postings against a person's verified work history, writes tailored resumes and cover letters that claim nothing their records do not support, prepares interviews, researches applications and keeps the application tracker. Each person's qualifications live in their own Google Drive, in a folder named after them under `AI/JobSearch`; resumes, cover letters and the tracker live in Reactive Resume. Use it for anything about a job posting, resume, cover letter, application, interview or job-search research, and for first-time setup of a person's career records.
license: MIT
compatibility: Needs the Jobs connector that ships in this plugin, connected and signed in (Google and Reactive Resume are authorised inside Obot).
metadata:
  author: ConniptionFit
  role: launcher
---

# Jobs

This is a launcher. The instructions, the rules and every workflow are served live by the Jobs connector, so they are always the current version and nothing in this file can go stale.

1. Call the `guide` tool of the Jobs connector with no arguments (it is `career_architect__guide`; your client may show a prefix before that name, and may load tools on demand, so load it first). Follow what it returns.
2. When the instructions say to read a document such as `references/storage.md` or `workflows/score.md`, call `guide` again with that path as `topic`.
3. If there is no `guide` tool, the Jobs connector is not connected. Tell the person to open the Jobs connector (the plugin's Connectors tab) and connect it, sign in, and authorise Google and Reactive Resume when asked. Do not write a resume, letter or score without the instructions: a document nobody checked is what this assistant exists to prevent.
