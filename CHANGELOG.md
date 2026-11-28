# Changelog

[Data Noodler](README.md) › Changelog

What changed in how Data Noodler behaves, newest first, in plain language.

An entry is added whenever something a user or an agent can see changes: a tool, one of its options, the instructions the server gives the agent, an installer flag, or the version of Google's analytics-mcp that gets installed. Each entry names the documents that were checked against the change and says which of them changed. A test compares the "Surface" code on the newest entry with the software and fails when they differ, so a visible change can't ship without an entry.

## 2026-11-28: The agent keeps a notebook in your project

In Claude Code and Codex, the agent now keeps a notebook called `data-noodler-notebook.md` in the project folder, beside `_outputs/`. It writes short dated entries as the work happens: what you wanted to know, what it ran, what came back, hypotheses and whose they are, choices you made, and questions still open. Entries are added and never edited. A mistake is fixed by a new entry marked as a correction.

At the start of a later session in the same project, the agent reads the notebook and tells you in one line that it has. Your new question sets the direction. An earlier finding comes up only when it bears on what you're asking.

The notebook holds findings about your data. If the project is a git repository that doesn't ignore the file, the agent tells you that committing would publish it.

**Surface:** `55dff57e012b`

**Docs checked:** `data-noodler/skills/data-noodler/SKILL.md` (changed), `README.md`, `SECURITY.md`, `data-noodler/README.md`, `data-noodler/START-HERE.md`, `data-noodler/ARCHITECTURE.md`, `data-noodler/BUILD-YOUR-OWN.md`.

## 2026-11-28: The agent does its arithmetic with a script

The agent is now told to compute with a script that reads the exported file. Plain Python is enough, and nothing gets installed without asking you first. The agent checks the script before it trusts the answer: the number of rows the script read has to match the export's receipt, and for a metric that adds up, the script's total is compared with one figure fetched directly from Google. The script is saved in the same folder as the export and shown to you with the result. A small sum from two or three figures can still be done by hand, and the agent says when it did that. In a chat app whose code can't open files on your computer, the agent says what it couldn't compute.

Both skills also gained one sentence. When a skill and the software disagree about a fact, the agent follows the software and tells you what disagreed.

**Surface:** `55dff57e012b`

**Docs checked:** `data-noodler/skills/data-noodler/SKILL.md` (changed), `data-noodler/skills/data-noodler-setup/SKILL.md` (changed), `data-noodler/BUILD-YOUR-OWN.md` (changed), `README.md`, `SECURITY.md`, `data-noodler/README.md`, `data-noodler/START-HERE.md`, `data-noodler/ARCHITECTURE.md`.

## 2026-11-28: The changelog starts here

Nothing changes with this entry. It records the starting point: the tools, their options, the server's instructions and the installer's flags as they stood on the day the changelog began.

**Surface:** `dad42fe19a6f`

**Docs checked:** `README.md`, `SECURITY.md`, `data-noodler/README.md`, `data-noodler/START-HERE.md`, `data-noodler/GOOGLE-CLOUD-SETUP.md`, `data-noodler/ARCHITECTURE.md`, `data-noodler/BUILD-YOUR-OWN.md`, `data-noodler/skills/data-noodler-setup/SKILL.md`, `data-noodler/skills/data-noodler-setup/references/windows.md`, `data-noodler/skills/data-noodler-setup/references/troubleshooting.md`, `data-noodler/skills/data-noodler-setup/references/install-report.md`, `data-noodler/skills/data-noodler/SKILL.md`. None changed for this entry.
