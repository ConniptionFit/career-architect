# Changelog

## 2.1.0, server 1.1.0 (2026-09-28)

The skill now targets one bundle of tools, the **Jobs** virtual MCP server, instead of three separately connected tools.

- **Jobs vMCP.** `deploy/jobs-vmcp.json` defines it: Career Architect, Reactive Resume, Google Drive and Google Docs behind one endpoint, 37 tools in total, each described for an agent. Destructive, sharing, bulk, import and AI-writing tools are not exposed. `deploy/apply-jobs-vmcp.js` applies the spec to Obot.
- **Storage moved to Google Docs tools.** Drive cannot write content and reads a Doc as a garbled PDF, so records are read with `google_docs__get_document` and written with `google_docs__create_document` (a new version, moved into the folder with `google_drive__update_file`) or `google_docs__replace_text` (one line). `jobs/references/storage.md` is rewritten for this.
- **Server 1.1.0.** Recognises the leading section-break line Google Docs adds (`normalize_text` has a `docs` source); stops treating ordinary blank-line-separated prose as doubled Drive text; tool descriptions now say when to use each tool.
- **Tests.** `tests/test_deploy_spec.py` keeps the skill, the spec and the server's tool list in step; the Docs-shaped text is simulated in `tests/drive_sim.py`.
- **Claude plugin.** `.claude-plugin/` makes the repository a plugin marketplace so Claude apps can install the skill and keep it current.
- **Docs.** `docs/EXTENDING.md`; the runbook covers the vMCP, profiles and what reaches clients by itself.

To upgrade an existing deployment: rebuild the container, create the Jobs vMCP and run the apply script (`docs/OPERATIONS.md`, sections 4 and 7), add Google Drive and Google Docs to the access policy, and have each person connect Google Docs once.

## 2.0.0, server 1.0.0 (2026-09-28)

Hosted, multi-user version: the skill in hosted mode, the stateless career-architect MCP server, Google Drive storage per person, Reactive Resume per person, and the runbook.
