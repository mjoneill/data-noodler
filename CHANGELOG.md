# Changelog

[Data Noodler](README.md) › Changelog

What changed in how Data Noodler behaves, newest first, in plain language.

An entry is added whenever something a user or an agent can see changes: a tool, one of its options, the instructions the server gives the agent, a file in either skill, an installer flag, or the version of Google's analytics-mcp that gets installed. Each entry names the documents that were checked against the change and says which of them changed. A test compares the "Surface" code on the newest entry with the software and fails when they differ, so a visible change can't ship without an entry.

## 2026-11-28: An upgrade starts by getting the newest package

To upgrade, point your agent at the Data Noodler repository and ask it to help you upgrade. It now gets the newest copy first, by updating the clone you already keep or making a new one, and follows the instructions that came with that copy. Before this, the instructions never said to do any of that, so an agent could upgrade from an old copy it found on your disk and report success.

The upgrade's read-only check now prints the version installed beside the version you're about to install, so you both see what will change. The same check now counts every running Data Noodler server. It used to miss Google's analytics server when an app started it through its shortcut, which could have let an upgrade begin while that app was still using it.

Smaller changes in the same instructions: a blank maintainer field no longer sends a machine that already has Data Noodler back to first-time setup. The agent gives you the undo command before you quit your apps, and tells you what to say when you come back. The Windows note about fresh installs now sits with the fresh-install steps. Two results the skill copier can print now have a description.

Also recorded here, because they merged before this changelog covered the skills: the install check lists entries registered under an older name of Data Noodler's server, which the upgrade removes, and the searches for the sign-in file look at most two folders deep.

**Surface:** `c1cb449f46e1`

**Docs checked:** `data-noodler/skills/data-noodler-setup/SKILL.md` (changed), `data-noodler/skills/data-noodler-setup/references/windows.md` (changed), `README.md` (changed), `data-noodler/START-HERE.md` (changed), `data-noodler/skills/data-noodler-setup/references/troubleshooting.md`, `data-noodler/README.md`, `data-noodler/ARCHITECTURE.md`, `data-noodler/BUILD-YOUR-OWN.md`.

## 2026-11-28: A change to a skill now needs an entry here

Nothing changes in how Data Noodler behaves. From this entry on, the check behind this changelog also covers the two skills: the instructions an agent follows to answer analytics questions and to install Data Noodler, with their reference pages and scripts. A change to any file in either skill now needs an entry here, the same as a change to a tool. A wording fix that leaves the meaning alone needs one too, and one line is enough for it.

**Surface:** `6ae34dc09666`

**Docs checked:** `CHANGELOG.md` (changed), `README.md`, `data-noodler/ARCHITECTURE.md`.

## 2026-11-28: The agent checks for one page under several URLs

Before it reports by page, the agent now checks whether one page appears under several URLs: http beside https, with and without www, with and without a trailing slash, in different letter case, with a query string, or with a fragment. It shows you what it found, with the views or clicks those extra URLs carry, and asks how to treat each kind: merge, keep separate, or flag as something to fix on the site. When the extra URLs carry too little to change the answer, it says so and carries on. Your choice is recorded, so a rerun makes it again.

For Google Analytics, the agent is also told what each page field can show. The plain page path leaves out the hostname, so on a property that receives several sites it adds different sites' pages together. The agent checks the hostnames first and asks whether to break them out.

**Surface:** `64359ba33df6`

**Docs checked:** `data-noodler/skills/data-noodler/SKILL.md` (changed), `data-noodler/BUILD-YOUR-OWN.md` (changed), `README.md`, `SECURITY.md`, `data-noodler/README.md`, `data-noodler/START-HERE.md`, `data-noodler/ARCHITECTURE.md`.

## 2026-11-28: The agent keeps a notebook in your project

In Claude Code and Codex, the agent now keeps a notebook called `data-noodler-notebook.md` in the project folder, beside `_outputs/`. It writes short dated entries as the work happens: what you wanted to know, what it ran, what came back, hypotheses and whose they are, choices you made, and questions still open. Entries are added and never edited. A mistake is fixed by a new entry marked as a correction.

At the start of a later session in the same project, the agent reads the notebook and tells you in one line that it has. Your new question sets the direction. An earlier finding comes up only when it bears on what you're asking.

The notebook holds findings about your data. If the project is a git repository that doesn't ignore the file, the agent tells you that committing would publish it.

**Surface:** `55dff57e012b`

**Docs checked:** `data-noodler/skills/data-noodler/SKILL.md` (changed), `README.md`, `SECURITY.md`, `data-noodler/README.md`, `data-noodler/START-HERE.md`, `data-noodler/ARCHITECTURE.md`, `data-noodler/BUILD-YOUR-OWN.md`.

## 2026-11-28: The agent does its arithmetic with a script

The agent is now told to compute with a script that reads the exported file. Plain Python is enough, and nothing gets installed without asking you first. The agent checks the script before it trusts the answer: the number of rows the script read has to match the export's receipt, and for a metric that counts events, such as page views, the script's total is compared with one figure fetched directly from Google. The script is saved in the same folder as the export and shown to you with the result. A small sum from two or three figures can still be done by hand, and the agent says when it did that. In a chat app whose code can't open files on your computer, the agent says what it couldn't compute.

Both skills also gained one sentence. When a skill and the software disagree about a fact, the agent follows the software and tells you what disagreed.

**Surface:** `55dff57e012b`

**Docs checked:** `data-noodler/skills/data-noodler/SKILL.md` (changed), `data-noodler/skills/data-noodler-setup/SKILL.md` (changed), `data-noodler/BUILD-YOUR-OWN.md` (changed), `README.md`, `SECURITY.md`, `data-noodler/README.md`, `data-noodler/START-HERE.md`, `data-noodler/ARCHITECTURE.md`.

## 2026-11-28: The changelog starts here

Nothing changes with this entry. It records the starting point: the tools, their options, the server's instructions and the installer's flags as they stood on the day the changelog began.

**Surface:** `dad42fe19a6f`

**Docs checked:** `README.md`, `SECURITY.md`, `data-noodler/README.md`, `data-noodler/START-HERE.md`, `data-noodler/GOOGLE-CLOUD-SETUP.md`, `data-noodler/ARCHITECTURE.md`, `data-noodler/BUILD-YOUR-OWN.md`, `data-noodler/skills/data-noodler-setup/SKILL.md`, `data-noodler/skills/data-noodler-setup/references/windows.md`, `data-noodler/skills/data-noodler-setup/references/troubleshooting.md`, `data-noodler/skills/data-noodler-setup/references/install-report.md`, `data-noodler/skills/data-noodler/SKILL.md`. None changed for this entry.
