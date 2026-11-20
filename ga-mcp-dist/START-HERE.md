# Start here

This package puts Google Analytics 4 and Google Search Console tools into
Claude Code, Claude Desktop, Codex and the ChatGPT desktop app (its Work and
Codex modes; not Chat, which is hosted) on a Mac or Windows
machine, with **read-only** access to the data each person's own Google
account can already see. It is written for an AI agent to install, with a
person beside it for the handful of steps only a person can do.

**If you are an agent, read this whole page before doing anything.** Then
open `deployment.json`, which decides which of two situations you are in.

## Which situation is this?

`deployment.json` describes the deployment this package belongs to: who
maintains it, where the Google sign-in file comes from, where install reports
go.

- **Its values are filled in** → someone already set this package up for an
  institution or team. You are installing or upgrading one more machine in
  that deployment. Go to `skills/ga-mcp-setup/SKILL.md` and follow it; it
  reads `deployment.json` as it goes.
- **Its values are blank** → this package was shared with a new institution,
  and nobody has set it up there yet. Your job is to **port it**: understand
  the approach, help the user make the decisions only they can make, create
  their Google sign-in, fill in `deployment.json`, install on their machine,
  and prepare what they will hand to their colleagues. The rest of this page
  is that path.

## What is deliberately not in this package

- **`ga-mcp-client.json`**, the Google OAuth client file. It is specific to a
  deployment's own Google Cloud project, so it is not in this package and
  never goes into a git repository. In an existing deployment it comes from
  the maintainer named in `deployment.json`; a new deployment creates its own
  (`GOOGLE-CLOUD-SETUP.md`).
- **Credentials.** Each person signs in with their own Google account during
  install; the resulting token stays on their machine.
- **The original deployment's records**: install histories, runbooks, machine
  details. Those stay private to whoever shared this.

## Porting it to a new institution

Work through these with the user, in order. Do not skip ahead to installing;
steps 1–3 are decisions that change what gets installed.

### 1. Understand the approach first

Read, in this order, and summarize each for the user in a few sentences:

1. `ARCHITECTURE.md`: what the pieces are, why the install is split between
   an agent and tested code, and what the security posture is.
2. `GOOGLE-CLOUD-SETUP.md`: how a deployment gets its own Google sign-in.
3. `INSTALL.md`: the by-hand install, which is what the skill automates.
4. `skills/ga-mcp-setup/SKILL.md`, and `references/windows.md` if any
   Windows machines are involved.
5. `skills/ga-mcp-setup/references/troubleshooting.md`.

Say plainly what you found: what this package does well, what it assumes,
and anything that does not fit the user's situation. It was built for one
institution's mix of machines and apps; theirs may differ.

### 2. The decisions only the user can make

Ask, and write the answers into `deployment.json`:

- **Who maintains this deployment?** The person others will get the sign-in
  file from and send install reports to. Usually the user you are talking to.
  (`maintainer`, `maintainer_contact`, `install_reports_to`)
- **Which Google audience?** Internal (needs Google Workspace and a Cloud
  project in their organization; no weekly renewal) or External in Testing
  (works for anyone; 7-day credentials, up to 100 named test users).
  `GOOGLE-CLOUD-SETUP.md` explains the trade-off. Record the choice in
  `client_file_source_note`.
- **Which apps, on which machines?** Claude Desktop, Claude Code, Codex, the
  ChatGPT app; macOS, Windows. Note anything untested for their mix (see
  "What is proven" in `ARCHITECTURE.md`).
- **Whose Google accounts hold the GA access?** Institutional accounts, or
  personal Gmail accounts? This decides who gets added as test users, and
  whether Internal is even possible.

### 3. Create the Google sign-in

Walk the user through `GOOGLE-CLOUD-SETUP.md`. You cannot do this for them:
it happens in their browser, in their Google Cloud console. At the end they
have `ga-mcp-client.json`. Check it as the guide says (a Desktop client, an
`"installed"` key), and place it where the install expects it.

### 4. Adapt what names the original deployment

- `deployment.json`: fill every blank.
- `marketplace/plugins/ga-analytics/.codex-plugin/plugin.json`: the
  `author`, `developerName` and the example prompts (`defaultPrompt`). Give
  them the user's institution and a real site of theirs. If you change
  anything in that plugin folder, bump its `version`; Codex caches by
  version.
- The reporting guide (`companion/guidance.py`) uses `example.edu` sites as
  illustrations. They work as they are; swapping in a real site of theirs is
  optional.

### 5. Install on the user's own machine

Follow `skills/ga-mcp-setup/SKILL.md` from Step 1. It ends with `verify.py`
exiting 0 for every registered app, a live question answered in each app, and
an install report (Step 10). This is the first install in the new deployment,
so the report is worth keeping: it is the start of their own records.

### 6. Prepare the hand-off to their colleagues

For each person who will install, the maintainer gives:

- this package (as a zip, or from wherever the maintainer keeps it),
  **with the filled-in `deployment.json`**;
- `ga-mcp-client.json`, handed over directly: password manager, a shared
  drive only the team can open, or in person. Not over chat, not to a list;
- for an External audience, confirmation that their Google account has been
  added as a test user, *before* they install;
- the name to send the install report to.

Each person then points their own agent at this package. It reads the
filled-in `deployment.json` and takes the first path above.

## Keep these as they are

They are the security posture, and each has a reason recorded in the code or
the docs:

- The two **read-only** Google permissions the sign-in requests. Do not add
  write scopes; the upstream server's write tool stays off.
- The **pinned dependencies** (`installer/constraints.txt`) and the way pip
  itself is installed by exact URL and checksum. Regenerate pins with the
  documented process and scan them; do not hand-edit.
- **Exports go only to approved places**: the project folder, the sessions
  folder, or folders listed in the machine's configuration. The model never
  names an arbitrary path.
- The `ga-mcp-client.json` exclusion in `.gitignore`.

## Who to tell when something is wrong

This package was shared as a one-off. Your deployment's maintainer is now
the first stop for problems, and the install reports are how they find out.
If you find a defect in the package itself, the person who shared it with
you would likely want to know, but there is no support commitment implied by
the sharing. See `LICENSE`.
