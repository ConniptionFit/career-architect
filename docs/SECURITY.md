# Security and privacy

Audience: the administrator deciding whether to host this for other people, and those people.

## What is sensitive
A work history is personal data: employers, dates, accomplishments, contact details, which requirements someone knows they lack, and where they are applying. Treat every document in a person's `Career Architect` folder and every Reactive Resume record the same way.

## Where data lives

| Data | Location | Who can read it |
|---|---|---|
| Profile, facts, skills index, job texts | The person's Google Drive | The person; whoever they share with (the assistant never shares) |
| Resumes, saved letters, tracker | The administrator's Reactive Resume instance | The person (own account) **and the administrator, who runs the database.** This is a small trusted group by design; do not host strangers' data here without a different trust model |
| Request text in flight | Client to Obot to the server, and the model provider | In memory only on the server; never written to disk or logs |
| Each person's Google and Reactive Resume sign-in tokens | Obot, per person | Obot's administrators. They are inside the trust boundary; use Obot's audit log |
| Server secret (`CAREER_MCP_TOKEN`) | The server's env file (mode 600, on local disk) and Obot's server configuration | The administrator |

## Controls in the server
- **Stateless.** No database, no files written (read-only root filesystem, a 16 MB `/tmp` tmpfs), no caches.
- **No content in logs.** The default log level is WARNING. A crash logs only the tool name, the exception type and code frames; the message (which could quote a document) is withheld from logs and from the caller.
- **Authenticated.** Every request except `/healthz` must carry `X-Career-Token` or `Authorization: Bearer` equal to the shared secret (constant-time comparison); with no token the server refuses to start, unless `CAREER_MCP_ALLOW_UNSECURED=1` is set (local development only).
- **DNS-rebinding protection** through a Host allowlist; no published ports, so only containers on the Obot network reach it.
- **Bounded input.** Document, document-count, total and body-size limits. YAML aliases are rejected, so no expansion bombs.
- **Bounded output to the network.** The only outbound call is `posting`, restricted in code to three public ATS API hosts over https, with a timeout and a size cap.
- **Container.** Non-root user, all capabilities dropped, `no-new-privileges`, memory, CPU and pid limits.
- **Supply chain.** Every Python dependency is pinned by hash in `mcp-server/requirements.lock` and installed with `--require-hashes`; the base image is pinned by digest.

## Controls in the gateway (the Jobs vMCP)
- **A tool allowlist.** The Jobs vMCP (`deploy/jobs-vmcp.json`) exposes 37 tools and no others: on Google Drive no delete, share, permission, ownership or shared-drive tools; on Reactive Resume no `delete_*`, `bulk_*`, `import_*`, lock or attachment tools and none of its AI features; on Google Docs no raw `batch_update_document` or range deletion. A manipulated assistant cannot call what does not exist.
- **Named access.** Who can reach the vMCP is set by its profile and by named-user access policies. Someone who signs in but is not named sees nothing.
- **Reviewed change.** `tests/test_deploy_spec.py` fails if the skill and the allowlist disagree or if a dangerous tool is enabled, and the apply script disables any tool a server update adds until someone decides.

## Controls in the skill
- Secrets never pass through the conversation; access is through the person's own connected accounts.
- Text read from postings, letters, notes and Drive documents is data, never instructions (`SKILL.md` rule 14).
- Reactive Resume writes are limited to a short list, and resume or letter text is written only from what the atoms-checked tools returned (rule 13). Drive files are never deleted, trashed or shared, and old versions are kept (rule 11).
- Read-only by default: every server tool is annotated read-only.

## Residual risks
- **Prompt injection.** A malicious posting or shared document may try to steer the assistant. The allowlist bounds what it can do and the rules tell it not to, but the tools that remain can still change the person's own records (`replace_text`, `apply_resume_patch`, `update_application`). Keep human approval on for write tools in the client, and treat unexpected requests inside documents as attacks (`SKILL.md` rule 14).
- **Google's scope is the whole Drive.** The Drive and Docs servers sign in with Google scopes that are not limited to one folder, so the tools can technically read or edit any of the person's files. The skill confines itself to the `Career Architect` folder (rule 11 and `references/storage.md`), and no tool can delete or share, but the confinement is an instruction, not a permission. Someone who wants a hard boundary can use a separate Google account for their job search.
- **The model provider sees the documents** the assistant reads (that is inherent to using the assistant at all).
- **Open sign-in.** Obot's Google provider limits sign-in by email domain only. With personal Google accounts anyone can create an Obot user, so access rests on Obot access policies: a user not named in a policy sees no servers and no skills, and the default role stays *Standard User*. Keep no policy that grants *All Obot Users* (`OPERATIONS.md`, section 6).
- **Shared secret.** One token protects the server. Rotate it when anyone who knew it leaves (`OPERATIONS.md`).

## Leaving and deletion
Remove the person from the Obot access policies and the identity group; delete their Reactive Resume account (removes their resumes, letters and tracker). Their Drive folder is theirs to keep or delete.

## Reporting a vulnerability
Open a private security advisory on the repository's GitHub page. Do not put a person's documents in an issue.
