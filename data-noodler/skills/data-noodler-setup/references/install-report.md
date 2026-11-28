# Install report template

[Data Noodler](../../../../README.md) › [Start here](../../../START-HERE.md) › [Setup skill](../SKILL.md) › Install report template

Step 10 of SKILL.md. Fill this in at the end of every install and every upgrade, and save it as `~/.config/data-noodler/install-reports/<YYYY-MM-DD>-<fresh|upgrade>.md`. The user sends it to the maintainer named in `deployment.json`.

The template follows the best report received so far (Windows, 2026-10-09). Every fix made after that install came out of it. This report is a chance to improve installing and upgrading Data Noodler for everyone. Keep that report's habits:

- **Evidence over adjectives.** Give the exact error text, the log lines and event IDs, and the command that produced them. "It failed" cannot be fixed; `exit 3, MSI 2203 ... path not found` can.
- **Workarounds are findings.** Anything you did that SKILL.md or `references/windows.md` did not say to do goes in the step log and in "Issues". That includes any helper files you created and where they are.
- **Record who ran each step.** A step the user had to run by hand, such as an installer or the Desktop registration, is information.

## Privacy: what never goes in

These are hard rules.

- The contents of `data-noodler-client.json` or of the credential file. No tokens, no client secret. File paths and `client_id` are fine.
- Any Google Analytics or Search Console data, including the answers to the test question. Say that a query worked, and give its row count if useful.
- The user's account name. In paths, write `<user>`: `C:\Users\<user>\...`, `/Users/<user>/...`.
- Other personal or identifying details: the user's Google account email, the computer's name, and the name of their organization or network domain. Write `managed` or `personal` instead.

Show the user the finished report before they send it.

---

```markdown
# Data Noodler install report: <OS> (<fresh install | upgrade from DATE/VERSION>)

<YYYY-MM-DD> · written by <Claude Code | Codex> at the end of the install

## Summary

<Two or three sentences: did it work, where, and what it took.>
verify.py: <Claude Code: exit N, analytics-mcp = N tools, data-noodler = N>;
<Claude Desktop: ...>; <Codex: ...>.
Workarounds needed: <none | one line each>.

## Machine and context

| Item | Value |
|---|---|
| OS | <name, version and build; managed/domain-joined or personal> |
| Administrator rights | <yes / no> |
| Python at start | <none / Store stub only / version and path> |
| Python used | <version, where it came from, who installed it> |
| Claude Desktop | <not installed / standard / Microsoft Store (MSIX)>; config path used |
| Codex / ChatGPT.app | <not installed / version> |
| Codex registration | <`codex mcp add` / the plugin / adapted at install time: exactly what was changed>. On Windows this is still unmeasured, so record it |
| Security software | <Windows: Defender ASR rule IDs and actions from Get-MpPreference, if readable> |
| Package | <zip name, file count, newest file date> unpacked to <path> |
| Driver | <Claude Code in a terminal / Claude Code in Desktop's Code tab / Codex> |
| Other MCP servers present before | <none / names only> |
| Server's launch folder | <what `start_session` said chose the place: declared roots / the folder the app started it in / none (sessions folder)>. On Windows this is still unmeasured, so record it |
| Upgrade | <upgrade.py output: "Upgrade complete" or "UPGRADE FAILED" + the step; old venv deleted or kept> |

On Windows, the Defender line comes from:

    Get-MpPreference | Select-Object AttackSurfaceReductionRules_Ids, AttackSurfaceReductionRules_Actions

Rule `01443614-CD74-433A-B99E-2ECDC07BFC25` with action `1` means "block
low-prevalence executables" is enforced. If the command is refused, say so.
That is an answer too.

## Step log

| # | Step | Who ran it | Result | Deviation from the docs |
|---|---|---|---|---|
| 1 | probe.py | | | |
| ... | | | | |

## Issues, with evidence

<One subsection per issue: what happened, the exact error, the evidence, the
cause if you established it (and how), and what you did about it. Mark each as
blocking or minor.>

## Clean-up (Step 9)

<Loose client-file copies found, and where. Leftovers from an earlier install.
What you offered, and what the user chose.>

## Suggested changes

<Concrete changes to the package that would have avoided each issue.>

## What worked well

<Steps that went exactly as documented. Confirmations of things the docs list
as unproven are especially useful.>

## Open questions for the maintainer
```
