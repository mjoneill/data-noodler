# The `data-noodler/` folder

This folder is Data Noodler itself. The project's README, with what Data
Noodler is, which apps it works with and how to get started, is
[one level up](../README.md).

**Setting up?** Open this folder in Claude Code or Codex and say:

> Read START-HERE.md and help me set this up.

To install by hand instead, follow [`INSTALL.md`](INSTALL.md).

## What's in here

| | |
|---|---|
| `analytics-mcp` | Google's own GA4 server, installed from PyPI at a pinned version. 10 tools. Its optional write tools are never enabled. |
| `server/` | A second server built here. 15 tools: property lookup, credential status, a reporting guide, exports to CSV, and Search Console. |
| `installer/` | Scripts the agent runs: probe the machine, write its config, register the apps, verify, upgrade with rollback. |
| `skills/` | The instructions an agent follows to install. |
| `marketplace/` | A Codex plugin that packages both servers and the query skill. |
| `tests/` | The test suite. Run it with the interpreter `analytics-mcp` is installed under. |

[`ARCHITECTURE.md`](ARCHITECTURE.md) explains why it's shaped this way.
