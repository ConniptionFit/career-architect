# Forking this for your own group

The hosted deployment this repository is built around (an Obot instance, a Reactive Resume instance, a
career-architect MCP server) is **personal infrastructure run by this repository's author, for their own small
group.** Nobody else can sign in to it, and nobody else's connect plugin should point at it. There is no shared or
public instance of any of this.

If you want your own people to use this skill, you have two options:

| Option | Infrastructure you need | Guide |
|---|---|---|
| **Local mode.** One person at a time, no group gateway. | Your own Reactive Resume instance (or one you have an account on). | `jobs/references/local-mode.md`, `docs/LOCAL-MODE.md` |
| **Your own hosted deployment.** A group of people, one plugin they install once. | Your own Obot instance, your own Reactive Resume instance, a Docker host for the MCP server, your own connect plugin repository. | This document |

Local mode is the fast path if it's just you, or a couple of people willing to each run `setup.sh` and connect
Reactive Resume's MCP server themselves. Read the rest of this document only if you want the one-install, "sign in
once" experience for a group — which means running the whole stack yourself, independent of the original author's.

## Why you cannot just point at the original deployment

Every piece of hosted infrastructure here is scoped to one administrator:

- **Obot** decides who may sign in and reach the Jobs vMCP (a named-user access policy). The author's Obot instance
  knows nothing about you or your group, and adding you is not something forking the repository does.
- **Reactive Resume** in hosted mode is one instance per deployment; every person in a group signs in to the *same*
  instance under their own account. You cannot mix your group into someone else's instance without giving them
  access to it.
- **The career-architect MCP server** is stateless but still runs as one container, reachable only from the Obot
  instance it is registered against.
- **The connect plugin** people install is just an address: `connect/make.sh` bakes a specific Jobs vMCP URL into a
  ten-line launcher skill. Installing the original author's plugin and expecting it to work against your own Obot
  does nothing; the address in it is fixed at build time.

So: forking the skill's *instructions* is free and encouraged, but running a hosted deployment for other people
always means running your own copy of every box in the architecture diagram in `docs/ARCHITECTURE.md`, under your
own accounts.

## What you need, before you start

| Piece | What it is | Where it comes from |
|---|---|---|
| A GitHub account | To hold your fork, and (later) your connect plugin repository | github.com |
| An Obot instance | The group's sign-in gateway and vMCP host | Self-hosted, or obot.ai's hosted offering |
| An authentication provider for Obot | Who is allowed to sign in at all | Obot supports several (Google, GitHub, OIDC); pick one when you set up Obot |
| A Reactive Resume instance | Resumes, cover letters, the application tracker, one account per person | Self-hosted (Docker Compose, `docs.rxresu.me`) or a hosted instance you control |
| A Docker host, reachable from Obot | Runs the career-architect MCP server container | Any host with Docker Compose on the same network (or one Obot can reach) as Obot |
| Nothing extra for Google Drive and Docs | Obot's own catalog already offers hosted Google Drive and Docs servers; each person connects their own Google account through Obot | Nothing to stand up; see `docs/ARCHITECTURE.md`, "Decisions and alternatives" for the trade-off |

You do **not** need a Google Cloud project or your own OAuth client: storage rides on Obot's catalog servers, and
each person authorizes their own Google account when they first connect.

## The process

1. **Fork the repository.** `github.com/ConniptionFit/career-architect` → Fork. Clone your fork; everything below
   runs from it, not the original.

2. **Stand up Reactive Resume.** Follow `docs.rxresu.me`'s self-hosting guide (Docker Compose). Note its URL: you
   will register it in Obot as an MCP server in step 4. Nothing in this skill talks to Reactive Resume's REST API
   any more (see `CHANGELOG.md`, 2.4.0) — only its own MCP server, so make sure the version you run ships one.

3. **Stand up Obot**, or get an account on an instance you administer. Configure an authentication provider so you
   control who can sign in. This is the group's front door: nobody reaches anything below it without an Obot
   account and your access policy granting them the Jobs vMCP.

4. **Deploy the career-architect MCP server, from your fork**, and register the four servers (career-architect,
   Reactive Resume, Google Drive, Google Docs) in Obot, bundled as your own **Jobs vMCP**. This is the bulk of the
   work and it is written up in full, with every value to enter, in `docs/OPERATIONS.md`, sections 1 through 4.
   Wherever it says `git clone https://github.com/ConniptionFit/career-architect`, clone your fork's address
   instead. Wherever it names a Reactive Resume address, use the one from step 2, not the original author's.

5. **Publish the skill from your fork as a Skill source in Obot** (`docs/OPERATIONS.md`, section 5) — point Obot's
   Git sync at your fork, not the upstream repository, so your later edits reach people without anyone re-installing
   anything.

6. **Build your own connect plugin**, pointed at your own Jobs vMCP address, and publish it as its own **public**
   repository (`docs/EXTENDING.md`, "The connect plugin"):
   ```
   connect/make.sh https://<your obot>/mcp-connect/<your vmcp id> ../my-jobs-plugin
   cd ../my-jobs-plugin && git init && git add -A && git commit -m "Jobs connect plugin" && gh repo create <name> --public --source . --push
   ```
   This is the repository your people add as a plugin marketplace. It is not this repository, and it is not the
   original author's connect plugin repository either — it is a new one, generated from your fork, carrying your
   address.

7. **Onboard your people**: give each one an Obot account and the access policy that reaches the Jobs vMCP
   (`docs/OPERATIONS.md`, "Onboard a person"), and have them install your connect plugin (`connect/README.md`,
   "Install", substituting your plugin repository).

8. **Keep the two repositories straight.** Your fork of `career-architect` is where the skill's instructions and the
   server code live; your generated connect-plugin repository is just an address and rarely changes (it changes only
   if your Jobs vMCP's address changes, per `docs/EXTENDING.md`). Updating your deployment after you pull changes
   from upstream, or make your own, is `docs/OPERATIONS.md`, section 7 ("Update, and what reaches clients by
   itself") and the release checklist in `docs/EXTENDING.md`, run against your own Docker host and your own Obot,
   never the original author's.

## Staying in sync with upstream

Pulling improvements from the original repository into your fork is an ordinary git remote:

```
git remote add upstream https://github.com/ConniptionFit/career-architect
git fetch upstream
git merge upstream/main        # or rebase, or cherry-pick specific commits
```

Run the test suite before deploying anything you merged (`README.md`'s test command), then follow the release
checklist in `docs/EXTENDING.md` against your own infrastructure. Nothing about upstream's deployment, tags or
releases affects yours automatically; you decide when to pull and when to deploy.

## If you only wanted a personal copy

If the "your own group" scope above is more than you need — you just want to run this for yourself, on your own
Reactive Resume, with no Obot, no Docker host and no plugin to publish — you do not need to fork anything. Clone the
repository, run `bash setup.sh`, and follow `jobs/references/local-mode.md`. That is the whole footprint.
