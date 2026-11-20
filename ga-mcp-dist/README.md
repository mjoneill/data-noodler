# Google Analytics and Search Console tools for local AI apps

This package puts Google Analytics 4 and Google Search Console tools into
Claude Code, Claude Desktop, Codex and the ChatGPT desktop app (its Work and
Codex modes) on a Mac or Windows machine. Access is **read-only**, and each
person sees only what their own Google account can already see.

It is written for an AI agent to install, with a person beside it for the few
steps only a person can do.

## Start

Open this folder in Claude Code or Codex and say:

> Read START-HERE.md and help me set this up.

`START-HERE.md` tells the agent which of two situations it is in:

- **`deployment.json` is filled in**: someone has already set this package up
  for your institution or team, and you are installing one more machine.
- **`deployment.json` is blank**: nobody has set it up where you are. The
  agent walks you through creating your own Google sign-in
  (`GOOGLE-CLOUD-SETUP.md`, about 20 minutes in the Google Cloud console),
  filling in the profile, installing, and preparing the hand-off to
  colleagues.

To install by hand instead, follow `INSTALL.md`.

## What is in it

| | |
|---|---|
| `analytics-mcp` | Google's own GA4 server, installed from PyPI at a pinned version. 9 tools. Its optional write tool is never enabled. |
| `companion/` | A second server built here. 15 tools: property lookup, credential status, a reporting guide, exports to CSV, and Search Console. |
| `installer/` | Scripts the agent runs: probe the machine, write its config, register the apps, verify, upgrade with rollback. |
| `skills/` | The instructions an agent follows to install. |
| `marketplace/` | A Codex plugin that packages both servers and the query skill. |
| `tests/` | The test suite. Run it with the interpreter `analytics-mcp` is installed under. |

`ARCHITECTURE.md` explains why it is shaped this way, the security posture,
and what has and has not been proven on real machines.

## What is not in it

- **No credentials and no data.** There is no shared account. Each person
  signs in with their own Google account, and the token stays on their
  machine.
- **No Google sign-in file.** `ga-mcp-client.json` belongs to a deployment's
  own Google Cloud project. You create your own, and it never goes into a
  repository; `.gitignore` here excludes it.

## Requirements

macOS 12 or later, or Windows 11. No administrator rights are needed on
either. Codex on Windows is not proven; `ARCHITECTURE.md` keeps the list.

## Status

Shared as-is, with no support commitment. See `LICENSE`.
