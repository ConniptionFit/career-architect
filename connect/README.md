# Jobs connect plugin

One install for the Jobs job-search assistant: a small launcher skill and the Jobs connector (a remote MCP server). The launcher only tells the assistant to call the connector's `guide` tool, which returns the current instructions, so what people use updates whenever the administrator updates the server, with nothing to update on their side.

## Install

- **claude.ai or the desktop app:** Customize, Plugins, Add, Add marketplace, then this repository's address. Install `jobs`. Open the plugin's Connectors tab, add and connect the Jobs connector (you sign in to Obot with your Google account), then authorise Google Drive, Google Docs and Reactive Resume when Obot asks. Do this once.
- **Claude Code:** `/plugin marketplace add <owner>/<this repository>`, `/plugin install jobs@career-architect-connect`, then `/mcp` to connect the Jobs connector.

You need to be added by the administrator first: Obot shows nothing to anyone it does not know. Use one install path: this plugin, or a copy of the skill, not both.

<!-- template-only: make.sh drops everything below this line -->

## For the administrator

This folder in `career-architect/connect/` is a template. `make.sh <your Jobs vMCP address> <folder>` turns it into a repository of its own; see `docs/EXTENDING.md`, "The connect plugin".
