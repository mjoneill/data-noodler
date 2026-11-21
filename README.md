# Data Noodler

**Talk to your Google Analytics and Search Console. Skip the dashboards.**

Data Noodler connects AI apps such as Claude (Code and Desktop) and Codex to your Google Analytics 4 and Google Search Console data, so you can ask questions about how all your sites are doing, in plain language, instead of clicking through report screens.

It is for anyone who looks after websites: an individual, a team, an organization or an institution.

- **Your data stays yours.** Each person signs in with their own Google account, through a Google app you create yourself. The project ships the capability, never anyone's data access.
- **Read-only.** It reads reports; it does not change your Analytics or Search Console settings.
- **Short-lived sign-in, by design.** With your Google app in "Testing" status, a sign-in lasts 7 days. If a credential ever leaked, it would be useful for a week at most. The trade-off is signing in again once a week. If you're in a Google Workspace organization, you can choose an "Internal" app instead, which has no weekly sign-in; [`GOOGLE-CLOUD-SETUP.md`](data-noodler/GOOGLE-CLOUD-SETUP.md#before-you-start-one-decision-that-shapes-everything) explains both.

## Status

**Early preview.** Public since 2026-11-20. We use it every day on macOS in Claude Code. It has been installed and run on Windows machines with both Claude and Codex, but we don't develop on Windows ourselves, so we're always looking for feedback from Windows users. This release's Codex plugin doesn't start on native Windows yet; the [Windows notes](data-noodler/skills/data-noodler-setup/references/windows.md) say what is and isn't working there. The setup instructions were rewritten this week and nobody has yet followed them from scratch, so expect rough edges, especially in the Google Cloud setup.

**Feedback is the point of this preview.** If a step is unclear, fails, or works differently on your machine, please [open an issue](../../issues), or, if you'd rather not use GitHub, email `mjoneill+noodlerfeedback@gmail.com` instead. Say which app you used (Claude Code, Claude Desktop, Codex, ChatGPT), your operating system, and the step where it went wrong. If you installed with an AI app, it will have written an install report under `~/.config/data-noodler/install-reports/`. That report is the most useful thing you can send. It leaves out credentials and report data, but read it first and send it only if you're happy to. Never paste a credential, a client secret, or report data into an issue or an email.

It's shared as-is, with no support commitment. To report a security problem privately, see [`SECURITY.md`](SECURITY.md).

## Which apps work where

| App | macOS | Windows |
|---|---|---|
| Claude Code | **Confirmed**: a real question answered. It's where we use it daily. | **Confirmed** on Windows 11. |
| Claude Desktop | **Confirmed**, after a full quit and reopen, on two machines. | **Confirmed** on Windows 11, including the Microsoft Store version. |
| Codex | Installs and is reachable, but hasn't yet answered a real GA question here. It should work; that's not yet proven. | **Doesn't start yet.** This release's plugin starts its servers through `/bin/sh`. |
| ChatGPT desktop app: Work mode | **Confirmed**: a real question answered (ChatGPT 26.1021). | **Doesn't start yet**, for the same reason as Codex. |
| ChatGPT desktop app: Codex view | Served by the same plugin and runtime as Work, but not separately tested. | **Doesn't start yet**, for the same reason. |
| ChatGPT desktop app: Chat mode | No. It's hosted, so it can't reach servers on your computer without a hosted tunnel this package doesn't provide. Use Work instead. | No, for the same reason. |
| claude.ai or ChatGPT in a browser | No. Browser chats run their tools on the vendor's servers. | No. |

On Windows, these aren't proven yet: install paths containing spaces, upgrading an install, and exports into a project folder. Linux isn't a supported target.

Details: [`INSTALL.md`](data-noodler/INSTALL.md#what-you-get-and-what-you-dont) has the evidence for each app, the [Windows notes](data-noodler/skills/data-noodler-setup/references/windows.md) list what is and isn't working there, and [`ARCHITECTURE.md`](data-noodler/ARCHITECTURE.md#what-is-proven-and-what-is-not) says what has been proven, and how.

## Start here

The product lives in [`data-noodler/`](data-noodler/). Begin with [`data-noodler/START-HERE.md`](data-noodler/START-HERE.md), then [`data-noodler/GOOGLE-CLOUD-SETUP.md`](data-noodler/GOOGLE-CLOUD-SETUP.md) to create your own Google app.

## Contributing: guards against leaks

Nobody's credentials, report data or identifying details belong in this repository. Three checks keep them out:

- **CI, on every push and pull request** (`tools/leak_guard.py`). It refuses credential files and secrets (by file name and by content, so a renamed file is caught too), real-looking OAuth client ids, report output (`.csv`, `.xlsx`, `.html`, `_outputs/`) outside `tests/fixtures/`, a filled-in `deployment.json`, and home folders other than the placeholders `x`, `example`, `Jane`, `a` and `you`. Before it scans, CI proves each rule still catches a planted example. A refusal names the rule, the file and the line, never the value.
- **A local pre-push hook** (`tools/personal_guard.py`) for the values only you know. It refuses a push that contains a property or account id from your own property snapshot, or any line of `~/.config/data-noodler/personal-guard.txt` (your organization's name, colleagues' names, your Cloud project id). That list stays on your computer. Turn the hook on once per clone:

  ```
  git config core.hooksPath tools/hooks
  ```

  With neither list present it says so on every push and checks nothing.
- **Commit identities** (`tools/identity_guard.py`, in the same hook and in CI). Every commit publishes its author's and committer's email. Accepted: a GitHub noreply address (`…@users.noreply.github.com`, which keeps your mailbox out of the public history), or a plus-address of your own (`you+tag@yourdomain.com`, which does publish your mailbox). Refused: a plain mailbox with no `+tag`, and any computer-default identity (`.local`, `localhost`). Set yours once per clone before committing or rebasing: `git config user.name "Your Name"` and `git config user.email <id>+<login>@users.noreply.github.com` (GitHub shows yours under Settings → Emails).

"Google Analytics" and "Google Search Console" are trademarks of Google LLC. This project is not affiliated with or endorsed by Google.

## Licence

MIT. See [`LICENSE`](LICENSE). Data Noodler installs, but does not include, Google's analytics-mcp server, which is separately licensed under the Apache License 2.0.
