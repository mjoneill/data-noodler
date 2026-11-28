# Security

[Data Noodler](README.md) › Security

## Reporting a vulnerability

Please report security problems privately, using **Report a vulnerability** on this repository's **Security** tab. That opens a private advisory that only the maintainers can see.

Include what you found, how to reproduce it, and what it could expose. This project is shared as-is with no support commitment (see the README's [Feedback](README.md#feedback) section), but security reports are read.

## What this package is designed to protect

- **Read-only by construction.** Each person signs in with their own Google account and grants two read-only permissions (`analytics.readonly`, `webmasters.readonly`). Google's server's optional write tools are switched off in every configuration the installer writes.
- **Credentials stay on the machine.** The sign-in token is written to the user's own config folder and is never copied, shared or committed.
- **Whoever manages Data Noodler for a group can't see their users' data or credentials.** Each person has their own credential, limited to their own permissions. See [What this shares, and what it doesn't](data-noodler/GOOGLE-CLOUD-SETUP.md#what-this-shares-and-what-it-doesnt).
- **What your AI agent reads** from Google Analytics and Search Console becomes part of your conversation with your AI app (Claude, ChatGPT), and is handled the same way as anything else you share there.
- **Exports go only to approved folders.** Text inside analytics data can steer a model, so a file is written only inside the approved folders, whatever path the model asks for.
- **Pinned and scanned dependencies.** Every package version is pinned and checked against published advisories in CI; a known vulnerability fails the build.

[`data-noodler/ARCHITECTURE.md`](data-noodler/ARCHITECTURE.md) describes the security posture in full.
