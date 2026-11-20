# Data Noodler

**Talk to your Google Analytics and Search Console. Skip the dashboards.**

Data Noodler connects AI apps such as Claude (Code and Desktop) and Codex to your Google Analytics 4 and Google Search Console data, so you can ask questions about how all your sites are doing, in plain language, instead of clicking through report screens.

It is for anyone who looks after websites: an individual, a team, an organization or an institution.

- **Your data stays yours.** Each person signs in with their own Google account, through a Google app you create yourself. The project ships the capability, never anyone's data access.
- **Read-only.** It reads reports; it does not change your Analytics or Search Console settings.
- **Short-lived sign-in, by design.** With your Google app in "Testing" status, a sign-in lasts 7 days. If a credential ever leaked, it would be useful for a week at most. The trade-off is signing in again once a week.

## Status

Public since 2026-11-20, and shared as-is with no support commitment. To report
a security problem, see [`SECURITY.md`](SECURITY.md).

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
- **Commit identities** (`tools/identity_guard.py`, in the same hook and in CI). Every commit publishes its author's and committer's email. Accepted: a seat's plus-address (`<name>+<seat>@<domain>`, the same identity the seats use in manyhands, so each can attribute its own work) or a GitHub noreply address (`…@users.noreply.github.com`). Refused: a bare mailbox with no `+<seat>`, and any machine-default identity (`.local`, `localhost`). Set yours once per clone before committing or rebasing: `git config user.name <Seat>` and `git config user.email <name>+<seat>@<domain>`.

"Google Analytics" and "Google Search Console" are trademarks of Google LLC. This project is not affiliated with or endorsed by Google.

## Licence

MIT. See [`LICENSE`](LICENSE).
