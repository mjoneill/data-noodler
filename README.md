# Data Noodler

**Talk to your agent about your Analytics and Search Console data, avoid the dashboards and interfaces.**

Data Noodler connects AI apps such as Claude and ChatGPT to your Google Analytics 4 and Google Search Console data, so you can ask questions about how all your sites are doing and discuss their performance in plain language with the AI agents you prefer to work with. Let's face it, dashboards don't let you explore and the interfaces of both GA4 and GSC remain complex and unfamiliar to many users who contribute to websites.  By connecting your data to your agents, you and your users can go beyond numbers reporting and get to actionable insights...without having to be an expert in either interface. 

Data Noodler is for anyone who looks after or publishes to websites, or supports teams of individuals and organizations who do the same. 

With Data Noodler: 
- **Your data stays yours.** Each person signs in with their own Google account, through a Google App (in Google's terms, an OAuth client in a Google Cloud project) that you create yourself or for your team or org. (Instructions included. Your agent can walk you through this.) Each user only has access to the GA and GSC data that their own Google account has permission to see.

- **Access to GA4 and GSC is read-only.** Data Noodler only allows your users and AI agents to read and view data. It is not configured with edit access in either GA4 or GSC, even if a specific user has those permissions on the property in GA or GSC. 

- **Access is time bound to ~7 days.** If you set up your Google App for "Testing," all users will be required to re-authenticate every 7 days. This means that if a credential were somehow to leak from a user's desktop, it would be useful for a week at most.  And even if it were to leak, it would *only* provide read-only access to the GA and GSC accounts the user is authorized to access. 

  Note: If you're in a Google Workspace organization setting up Data Noodler for your team or org, you can set it up as an "Internal" app instead. These have no weekly sign-in requirement. Follow your organization's own approach for that; [`GOOGLE-CLOUD-SETUP.md`](data-noodler/GOOGLE-CLOUD-SETUP.md#troubleshooting) has a short note. I prefer the 7-day reauthentication anyway.

## Status

**Early stable.** Data Noodler has been public since 2026-11-20, but has been deployed privately for months prior. It is in use daily across Windows and Mac operating systems, and integrates ChatGPT and Claude. We haven't tried it with Gemini, Grok, MS Copilot, or other desktop AI applications.

## Which apps work where

| App | macOS | Windows |
|---|---|---|
| Claude | **Confirmed** working in the desktop app and the Claude Code TUI | **Confirmed** working on Windows 11 (desktop app). |
| ChatGPT | **Confirmed**: working in the desktop app and the Codex TUI | **Confirmed** working on Windows 11 (desktop app). |
| claude.ai or ChatGPT in a browser | No. | No. |

Data Noodler has been installed and successfully run on macOS 12+, or Windows 11+. It has been deployed successfully without administrator rights in managed environments. 

Details: [`INSTALL.md`](data-noodler/INSTALL.md#what-you-get-and-what-you-dont) has the evidence for each app, the [Windows notes](data-noodler/skills/data-noodler-setup/references/windows.md) list what is and isn't working there, and [`ARCHITECTURE.md`](data-noodler/ARCHITECTURE.md#what-is-proven-and-what-is-not) says what has been proven, and how.

## Installation, setup, and upgrading

Installation and setup is agent driven, meaning you will point your Claude Code or Codex agent at this repo and ask it to walk you through setup and installation. However, before you begin, you should know the answer to the following questions:

1) Are you setting this up for yourself and/or a team?  In this case, your agent will walk through setting up the Google App component of Data Noodler in addition to walking through configuring your Claude or ChatGPT products to work with Data Noodler.
2) Are you setting this up but someone has already created the Google App component of Data Noodler?  In this case, your agent will only walk through configuring your Claude or ChatGPT products to work with Data Noodler. 
3) Are you just upgrading a previous version? If so, your agent will walk through upgrading your existing installation and setup.  While I can't say this will never happen in the future, historically upgrades have never required revisiting the Google App setup in the Google Cloud console.  

Everything Data Noodler needs is in the [`data-noodler/`](data-noodler/) folder; the rest of this repository is project housekeeping. If you'd like to read before your agent starts, begin with [`START-HERE.md`](data-noodler/START-HERE.md). If you're the one creating your team's Google App, [`GOOGLE-CLOUD-SETUP.md`](data-noodler/GOOGLE-CLOUD-SETUP.md) walks through it.

## How this repo keeps your data out of it

Data Noodler is built by a small team today, but it's public, and issues and pull requests are welcome. Whoever contributes, nobody's credentials, report data or identifying details belong in this repository. Three checks keep them out:

- **CI on every push and pull request** (`tools/leak_guard.py`). It refuses credential files and secrets (by file name and by content, so a renamed file is caught too), real-looking OAuth client ids, report output (`.csv`, `.xlsx`, `.html`, `_outputs/`) outside `tests/fixtures/`, a filled-in `deployment.json`, and home folders other than the placeholders `x`, `example`, `Jane`, `a` and `you`. Before it scans, CI proves each rule still catches a planted example. A refusal names the rule, the file and the line, never the value.
- **A local pre-push hook** (`tools/personal_guard.py`) for the values only you know. It refuses a push that contains a property or account id from your own property snapshot, or any line of `~/.config/data-noodler/personal-guard.txt` (your organization's name, colleagues' names, your Cloud project id). That list stays on your computer. Turn the hook on once per clone:

  ```
  git config core.hooksPath tools/hooks
  ```

  If neither is present, nothing will be checked on a push.
- **Commit identities** (`tools/identity_guard.py`, in the same hook and in CI). Every commit publishes its author's and committer's email. Accepted: a GitHub noreply address (`…@users.noreply.github.com`, which keeps your mailbox out of the public history), or a plus-address of your own (`you+tag@yourdomain.com`, which does publish your mailbox). Refused: a plain mailbox with no `+tag`, and any computer-default identity (`.local`, `localhost`). Set yours once per clone before committing or rebasing: `git config user.name "Your Name"` and `git config user.email <id>+<login>@users.noreply.github.com` (GitHub shows yours under Settings → Emails).


## Feedback

Feedback and questions are welcome! 

Please [open an issue](../../issues), or, if you'd rather not use GitHub, email `mjoneill+noodlerfeedback@gmail.com` instead. Say which app you used (Claude Code, Claude Desktop, Codex, ChatGPT), your operating system, and the step where it went wrong. If you installed Data Noodler with an AI app (as most will), your agent should have written an install report under `~/.config/data-noodler/install-reports/`. That report is frequently the most useful thing you can send if asking questions. Note that the feedback report is generated by your agent with the instruction to NOT include any credentials, PII, etc...  However, it's always worth double-checking before sending anything off your machine. 

Data Noodler is shared as-is, with no support commitment. To report a security problem privately, see [`SECURITY.md`](SECURITY.md).

## License

MIT. See [`LICENSE`](LICENSE). Data Noodler installs, but does not include, Google's analytics-mcp server, which is separately licensed under the Apache License 2.0.

"Google Analytics" and "Google Search Console" are trademarks of Google LLC. This project is not affiliated with or endorsed by Google.

## About the builders

Data Noodler is built by Michael and a team of AI agents working in [Manyhands](https://github.com/mjoneill/manyhands). Check it out.

## Remember

Have fun. Be kind. Share generously.
