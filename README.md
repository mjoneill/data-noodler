# Data Noodler

**Talk to your Google Analytics and Search Console. Skip the dashboards.**

Data Noodler connects AI apps such as Claude (Code and Desktop) and Codex to your Google Analytics 4 and Google Search Console data, so you can ask questions about how all your sites are doing, in plain language, instead of clicking through report screens.

It is for anyone who looks after websites: an individual, a team, an organization or an institution.

- **Your data stays yours.** Each person signs in with their own Google account, through a Google app you create yourself. The project ships the capability, never anyone's data access.
- **Read-only.** It reads reports; it does not change your Analytics or Search Console settings.
- **Short-lived sign-in, by design.** With your Google app in "Testing" status, a sign-in lasts 7 days. If a credential ever leaked, it would be useful for a week at most. The trade-off is signing in again once a week.

## Status

Early and private. The setup guide is being reworked for individuals as well as teams.

## Start here

The product lives in [`ga-mcp-dist/`](ga-mcp-dist/). Begin with [`ga-mcp-dist/START-HERE.md`](ga-mcp-dist/START-HERE.md), then [`ga-mcp-dist/GOOGLE-CLOUD-SETUP.md`](ga-mcp-dist/GOOGLE-CLOUD-SETUP.md) to create your own Google app.

## Contributing: two guards against leaks

Nobody's credentials, report data or identifying details belong in this repository. Two checks keep them out:

- **CI, on every push and pull request** (`tools/leak_guard.py`). It refuses credential files and secrets (by file name and by content, so a renamed file is caught too), real-looking OAuth client ids, report output (`.csv`, `.xlsx`, `.html`, `_outputs/`) outside `tests/fixtures/`, a filled-in `deployment.json`, and home folders other than the placeholders `x`, `example`, `Jane`, `a` and `you`. Before it scans, CI proves each rule still catches a planted example. A refusal names the rule, the file and the line, never the value.
- **A local pre-push hook** (`tools/personal_guard.py`) for the values only you know. It refuses a push that contains a property or account id from your own property snapshot, or any line of `~/.config/ga-mcp/personal-guard.txt` (your organization's name, colleagues' names, your Cloud project id). That list stays on your computer. Turn the hook on once per clone:

  ```
  git config core.hooksPath tools/hooks
  ```

  With neither list present it says so on every push and checks nothing.

"Google Analytics" and "Google Search Console" are trademarks of Google LLC. This project is not affiliated with or endorsed by Google.

## Licence

MIT. See [`ga-mcp-dist/LICENSE`](ga-mcp-dist/LICENSE).
