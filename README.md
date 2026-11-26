# Data Noodler

**Talk to your agent about your analytics and search console data, avoid the dashboards and interfaces.**

Data Noodler connects AI apps such as Claude and ChatGPT to your Google Analytics 4 and Google Search Console data, so you can ask questions about how all your sites are doing, in plain language, instead of clicking through report screens and navigating confusing and cumbersome interfaces.

It is for anyone who looks after or publishes to websites: individuals, teams, or entire organizations.

With Data Noodler: 
- **Your data stays yours.** Each person signs in with their own Google account, through a Google app you create yourself or you create for your team or org. Each user only has access to the GA and GSC data that their GA account has permission to see.
- **Access to GA4 and GSC is Read-only.** The integration allows your users and AI agents to read and view data. It is not configured with edit access in either GA4 or GSC. 
- **Access is time bound to ~7 days** If you set it up for "Testing" in Google, all users are required to re-authenticate every 7 days. This means that if a credential were somehow to leak from a user's desktop, it would be useful for a week at most.  And even if it were to leak, it would only provide read-only access to the GA and GSC accounts the user is authorized to access. If you're in a Google Workspace organization and setting it up for your team or org, you can choose an "Internal" app instead. These have no weekly sign-in requirement. [`GOOGLE-CLOUD-SETUP.md`](data-noodler/GOOGLE-CLOUD-SETUP.md#before-you-start-one-decision-that-shapes-everything) explains both.

## Status

**Early stable.** Data Noodler has been public since 2026-11-20, and an earlier version by invitation only for months prior. It is in use daily across Windows and Mac, ChatGPT and Claude. 

**Feedback.** Feedback and questions are welcome! Please [open an issue](../../issues), or, if you'd rather not use GitHub, email `mjoneill+noodlerfeedback@gmail.com` instead. Say which app you used (Claude Code, Claude Desktop, Codex, ChatGPT), your operating system, and the step where it went wrong. If you installed Data Noodler with an AI app, it will have written an install report under `~/.config/data-noodler/install-reports/`. That report is frequently the most useful thing you can send if asking questions. Note that it should leaves out credentials and PII, but it is entirely agent written (your agent), so you can clean it and shape it however you choose. 

Data Noodler is shared as-is, with no support commitment. To report a security problem privately, see [`SECURITY.md`](SECURITY.md).

## Which apps work where

| App | macOS | Windows |
|---|---|---|
| Claude | **Confirmed** working in the desktop app and the Claude Code TUI | **Confirmed** working on Windows 11 (desktop app). 
| ChatGPT | **Confirmed**: working in the desktop app and the Codex TUI | **Confirmed** working on Windows 11 (desktop app). |
| claude.ai or ChatGPT in a browser | No. | No. |

Details: [`INSTALL.md`](data-noodler/INSTALL.md#what-you-get-and-what-you-dont) has the evidence for each app, the [Windows notes](data-noodler/skills/data-noodler-setup/references/windows.md) list what is and isn't working there, and [`ARCHITECTURE.md`](data-noodler/ARCHITECTURE.md#what-is-proven-and-what-is-not) says what has been proven, and how.

## Installation and Setup

Installation and setup is agent driven, meaning you will point your Claude Code or Codex agent at this repo and ask it to walk you through setup. However, before you begin, you should know the answer to the following questions:

1) Are you setting setting this up for yourself and/or a team?  In this case, your agent will walk through setting up the Google App component of Data Noodler in addition to walking through configuring your Claude or ChatGPT products to work with Data Noodler.
2) Are you setting this up but someone has already created the Google App component of Data Noodler?  In this case, your agent will only walk through configuring your Claude or ChatGPT products to work with Data Noodler. 

The product lives in [`data-noodler/`](data-noodler/). Begin with [`data-noodler/START-HERE.md`](data-noodler/START-HERE.md), then [`data-noodler/GOOGLE-CLOUD-SETUP.md`](data-noodler/GOOGLE-CLOUD-SETUP.md) to create your own Google app.

## Contributing: guards against leaks

If you are interested in contribution, understand that nobody's credentials, report data or identifying details are shared back to this repository. To prevent this, we have implemented the following:

- **CI, on every push and pull request** (`tools/leak_guard.py`). It refuses credential files and secrets (by file name and by content, so a renamed file is caught too), real-looking OAuth client ids, report output (`.csv`, `.xlsx`, `.html`, `_outputs/`) outside `tests/fixtures/`, a filled-in `deployment.json`, and home folders other than the placeholders `x`, `example`, `Jane`, `a` and `you`. Before it scans, CI proves each rule still catches a planted example. A refusal names the rule, the file and the line, never the value.
- **A local pre-push hook** (`tools/personal_guard.py`) for the values only you know. It refuses a push that contains a property or account id from your own property snapshot, or any line of `~/.config/data-noodler/personal-guard.txt` (your organization's name, colleagues' names, your Cloud project id). That list stays on your computer. Turn the hook on once per clone:

  ```
  git config core.hooksPath tools/hooks
  ```

  If neither are present, nothing will be checked on a push.
- **Commit identities** (`tools/identity_guard.py`, in the same hook and in CI). Every commit publishes its author's and committer's email. Accepted: a GitHub noreply address (`…@users.noreply.github.com`, which keeps your mailbox out of the public history), or a plus-address of your own (`you+tag@yourdomain.com`, which does publish your mailbox). Refused: a plain mailbox with no `+tag`, and any computer-default identity (`.local`, `localhost`). Set yours once per clone before committing or rebasing: `git config user.name "Your Name"` and `git config user.email <id>+<login>@users.noreply.github.com` (GitHub shows yours under Settings → Emails).

"Google Analytics" and "Google Search Console" are trademarks of Google LLC. This project is not affiliated with or endorsed by Google.

## Licence

MIT. See [`LICENSE`](LICENSE). Data Noodler installs, but does not include, Google's analytics-mcp server, which is separately licensed under the Apache License 2.0.

## Remember

Have fun. Be kind. Share generously.
