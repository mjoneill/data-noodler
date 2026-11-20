# Security

## Reporting a vulnerability

Please report security problems privately, not in a public issue: use
**Report a vulnerability** on this repository's **Security** tab. That opens a
private advisory that only the maintainers can see.

Include what you found, how to reproduce it, and what it could expose. This
project is shared as-is with no support commitment (see README.md's Status),
but security reports are read.

## What this package is designed to protect

- **Read-only by construction.** Each person signs in with their own Google
  account and grants two read-only permissions (`analytics.readonly`,
  `webmasters.readonly`). Google's server's optional write tools are switched
  off in every configuration the installer writes.
- **Credentials stay on the machine.** The sign-in token is written to the
  user's own config folder and is never copied, shared or committed.
- **Exports go only to approved folders.** Text inside analytics data can
  steer a model, so a file is only ever written inside the approved folders,
  wherever the model asks.
- **Pinned and scanned dependencies.** Every package version is pinned and
  checked against published advisories in CI; a known vulnerability fails
  the build.

`ga-mcp-dist/ARCHITECTURE.md` describes the security posture in full.
