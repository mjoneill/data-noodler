# Start here

[Data Noodler](../README.md) › Start here

This package puts Google Analytics 4 and Google Search Console tools into the Claude and ChatGPT desktop apps, and Claude Code and Codex in the terminal, on a Mac or Windows machine, with **read-only** access to the data each person's own Google account can already see. (There is no installation for browser versions of Claude or ChatGPT.)  

This document is written for an AI agent to facilitate installation of Data Noodler. Installation should be conducted in active collaboration/conversation between the agent and the primary person/user the agent works with. There are a limited number of steps that require the person to perform. 

**If you are an agent, read this whole page before doing anything.** Then open `deployment.json`, which decides which of two situations you are in.

## Already installed?

If `~/.config/data-noodler/config.json` exists on this machine, Data Noodler is already installed here, and this is likely an upgrade. Confirm with the user. If it is, make sure this folder is the newest copy of the package first (in a git clone, `git pull --ff-only`; otherwise download it again). Then go to `skills/data-noodler-setup/SKILL.md` in this folder and follow its upgrade path. The first-time setup below is for a machine with no install.

## Which situation is this?

`deployment.json` describes the deployment this package belongs to: who maintains it, where the Google sign-in file comes from, where install reports go.

Decide by the **`maintainer`** field. The two team-only fields, `maintainer_contact` and `install_reports_to`, may be blank on purpose (a just-for-yourself setup), so do not decide by them.

- **`maintainer` is filled in** → someone already set this package up, for themselves or for their team, organization or institution. You are installing or upgrading one more machine in that deployment. Go to `skills/data-noodler-setup/SKILL.md` and follow it; it reads `deployment.json` as it goes.
- **`maintainer` is blank** → nobody has set it up for this user yet. This may be because the user is setting it up just for themselves, or they are the primary user setting it up for a team, organization or institution. Confirm with your user which context you are assisting with. Your job is to **set it up for the first time**: understand the approach, help the user make the decisions only they can make, create their Google sign-in, fill in `deployment.json`, and install on their machine; and, only if other people will use it too, prepare what they will hand to those people. The rest of this page is that path.

## What is deliberately not in this package

- **`data-noodler-client.json`**, the Google OAuth client file. It is specific to a deployment's own Google Cloud project, so it is not in this package and never goes into a git repository. In an existing deployment it comes from the maintainer named in `deployment.json`; a new deployment creates its own (`GOOGLE-CLOUD-SETUP.md`).
- **Credentials.** Each person signs in with their own Google account during install; the resulting token stays on their machine.
- **The original deployment's records**: install histories, runbooks, machine details. Those stay private to whoever shared this.

## Setting it up for the first time

Work through these with the user, in order. Do not skip ahead to installing; steps 1–3 are decisions that change what gets installed.

**First, ask: is this just for you, or for other people too?**

- **Just you** (an individual, with your own sites): you are both the maintainer and the only user. You create your own Google sign-in, add only your own Google account as a test user, and hand nothing to anyone. Leave the team-only fields in `deployment.json` (`maintainer_contact`, `install_reports_to`) blank, and skip step 6.
- **Other people too** (a team, organization or institution): you are the maintainer. Everyone gets the sign-in file from you, and step 6 is how you hand the package over.

### 1. Understand the approach first

Read, in this order, and summarize each for the user in a few sentences:

1. `ARCHITECTURE.md`: what the pieces are, why the install is split between an agent and tested code, and what the security posture is.
2. [`GOOGLE-CLOUD-SETUP.md`](GOOGLE-CLOUD-SETUP.md): how a deployment gets its own Google sign-in. Users frequently have questions about what this sequence of steps is for.  It is often useful to explain it to them as clearly as possible. Often, saying something like this helps: "Because Data Noodler lets me read your Google Analytics and Search Console data, I need a way to sign in to them with read-only access. This step sets up that Google App."
3. [`skills/data-noodler-setup/SKILL.md`](skills/data-noodler-setup/SKILL.md), and `references/windows.md` if any Windows machines are involved.
4. `skills/data-noodler-setup/references/troubleshooting.md`.

Say plainly what you found: what this package does well, what it assumes, and anything that does not fit the user's situation. It was first built and tested on one organization's mix of machines and apps; theirs may differ.  Note: users frequently have questions about the safety and security of the tools they are installing.  If a user asks about this, it is your responsibility to give this package a review and honest assessment and recommendation.  

### 2. The decisions only the user can make

Ask, and write the answers into `deployment.json`:

- **Who maintains this deployment?** The person others will get the sign-in file from and send install reports to. Usually the user you are talking to. (`maintainer`, `maintainer_contact`, `install_reports_to`.) Just for yourself: put your own name in `maintainer` and leave the other two blank.
- **Which Google audience?** Internal (needs Google Workspace and a Cloud project in their organization; no weekly renewal) or External in Testing (works for anyone; 7-day credentials, up to 100 named test users). `GOOGLE-CLOUD-SETUP.md` explains the trade-off. Record the choice in `client_file_source_note`.
- **Which apps, on which machines?** Claude Desktop, Claude Code, Codex, the ChatGPT app; macOS, Windows. Note anything untested for their mix (see "What is proven" in `ARCHITECTURE.md`).
- **Whose Google accounts hold the GA access?** Organization accounts (a team's, company's or institution's Google Workspace), or personal Gmail accounts? This decides who gets added as test users, and whether Internal is even possible. Just for yourself, it is usually your own account.

### 3. Create the Google sign-in

Walk the user through `GOOGLE-CLOUD-SETUP.md`. You cannot do this for them: it happens in their browser, in their Google Cloud console. At the end they have `data-noodler-client.json`. Check it as the guide says (a Desktop client, an `"installed"` key), and place it where the install expects it.

### 4. Adapt what names the original deployment

- `deployment.json`: fill in every field, except that a just-for-yourself setup leaves `maintainer_contact` and `install_reports_to` blank on purpose. Blank team fields are a finished just-me setup, not an unfinished one.
- `marketplace/plugins/data-noodler/.codex-plugin/plugin.json`: the `author`, `developerName` and the example prompts (`defaultPrompt`). Give them the user's own name, or their team's or organization's, and a real site of theirs. If you change anything in that plugin folder, bump its `version`; Codex caches by version.
- The reporting guide (`server/guidance.py`) uses `example.edu` sites as illustrations. They work as they are; swapping in a real site of theirs is optional.

### 5. Install on the user's own machine

Follow `skills/data-noodler-setup/SKILL.md` from Step 1. It ends with `verify.py` exiting 0 for every registered app, a live question answered in each app, and an install report (Step 10). This is the first install in the new deployment, so the report is worth keeping: it is the start of their own records.

### 6. Prepare the hand-off to other people

**Only if others will use it too.** Just for yourself? Skip this step: you are done after step 5.

For each person who will install, the maintainer gives:

- this package (as a zip, or from wherever the maintainer keeps it), **with the filled-in `deployment.json`**;
- `data-noodler-client.json`, handed over directly: password manager, a shared drive only the team can open, or in person. Not over chat, not to a list;
- for an External audience, confirmation that their Google account has been added as a test user, *before* they install;
- the name to send the install report to.

Each person then points their own agent at this package. It reads the filled-in `deployment.json` and takes the first path above.

## Keep these as they are

They are the security posture, and each has a reason recorded in the code or the docs:

- The two **read-only** Google permissions the sign-in requests. Do not add write scopes; the upstream server's write tool stays off.
- The **pinned dependencies** (`installer/constraints.txt`) and the way pip itself is installed by exact URL and checksum. Regenerate pins with the documented process and scan them; do not hand-edit.
- **Exports go only to approved places**: the project folder, the sessions folder, or folders listed in the machine's configuration. The model never names an arbitrary path.
- The `data-noodler-client.json` exclusion in `.gitignore`.

## Who to tell when something is wrong

In a team, organization or institution, your deployment's maintainer is the first stop for problems, and the install reports are how they find out. If you set it up just for yourself, you are your own maintainer. If you find a defect in the package itself, the project would like to know (see the top-level README). It is open source with no support commitment; see `LICENSE`.
