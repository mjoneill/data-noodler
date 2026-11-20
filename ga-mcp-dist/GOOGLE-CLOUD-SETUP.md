# Setting up your own Google sign-in (OAuth client)

**Who this is for:** whoever deploys these tools for an institution or team
that does *not* get its sign-in file from an existing maintainer. You do this
once. Everyone you deploy to then uses the file you make here.

**What you end up with:** one file, `ga-mcp-client.json`, that lets each person
sign in with their *own* Google account and grant read-only access to the
Google Analytics and Search Console data *they already have*. The file gives
nobody access to anything by itself. Each person's access still comes from
the permissions they hold in Google Analytics and Search Console.

**Time:** about 20 minutes. **Cost:** none. The APIs below don't need a
billing account (true at the time of writing).

Google renames things in the Cloud console fairly often. If a label below has
moved, the step is still there under a nearby name. Please tell your
maintainer, or whoever gave you this package, so the guide can be updated.

---

## Before you start: one decision that shapes everything

**Internal or External?** This is the most important choice in this guide.

| | **Internal** | **External, in Testing** |
|---|---|---|
| Who can sign in | Only accounts in your Google Workspace organization | Only accounts you list as test users (max 100) |
| Credential lifetime | Long-lived | **Expires every 7 days**, so each person re-signs in weekly |
| "Google hasn't verified this app" screen | No | Yes, every time (click **Advanced → Continue**) |
| Google verification needed | No | No, as long as you stay in Testing |
| Available when | The Cloud project belongs to your Workspace organization | Always, including for personal Gmail accounts |

- **Choose Internal if you can.** It's available when your institution uses
  Google Workspace, the Cloud project is created inside your institution's
  Google Cloud organization, and the people using these tools sign into
  Google Analytics with their institutional accounts. It avoids the weekly
  renewal, the 100-person cap and the warning screen.
- **Choose External (Testing) otherwise**, for example when people use personal
  Gmail accounts for GA, or you can't create projects in your institution's
  organization. Everything works. Each person just renews weekly with one
  command (`credential_status` tells them which).
- **Publishing an External app "to production"** removes the 7-day expiry and
  the 100-user cap. But `analytics.readonly` is a *sensitive* scope, so Google
  may require its app-verification review first. That's beyond this guide.
  Testing is the practical choice for a team-sized deployment.

**Check your institution's rules first.** Two things can stop you before you
start:

- **Creating Cloud projects may be restricted.** Many institutions only let
  certain staff create projects in their Google Cloud organization. If
  **New project** is greyed out, or your organization isn't offered, ask your
  Google Cloud or Workspace administrator to create the project for you, or to
  grant you the *Project Creator* role.
- **Third-party app access may be restricted.** Google Workspace
  administrators can block apps they haven't explicitly trusted (Admin console →
  **Security → Access and data control → API controls**). An Internal app in
  your own organization is usually allowed. An External one may be blocked for
  your users until an administrator marks its **client ID** as trusted. If
  people get "This app is blocked" or "Access blocked: your institution's
  policy", that's this setting, and only an administrator can change it.

---

## 1. Create the project

1. Go to **console.cloud.google.com**. This is the Cloud console, a different
   site from analytics.google.com, which you won't use during setup.
2. Use the project picker at the top → **New project**.
   - **Name:** something you'll recognize later, for example
     `ga-mcp` or `analytics-ai-tools`.
   - **Organization / Location:** your institution's organization if you're
     going **Internal**. This is what makes Internal possible.
3. **Write down the project ID.** Google adds digits when a name is taken, so
   it looks like `ga-mcp-483921` rather than what you typed. Every link below
   uses it.

## 2. Turn on the three APIs

Open each link with your project ID in place of `PROJECT_ID`, and click
**Enable**. The project is pinned in the URL, so you can't accidentally enable
it on another project.

- Google Analytics **Data** API:
  `https://console.cloud.google.com/apis/library/analyticsdata.googleapis.com?project=PROJECT_ID`
- Google Analytics **Admin** API:
  `https://console.cloud.google.com/apis/library/analyticsadmin.googleapis.com?project=PROJECT_ID`
- Google **Search Console** API:
  `https://console.cloud.google.com/apis/library/searchconsole.googleapis.com?project=PROJECT_ID`

There is no Save button: **Enable** takes effect at once, and the page then
shows "API enabled". If you skip one, the tools fail later with "…API has not
been used in project … before or it is disabled". That error means sign-in
*worked*. It's this step that was missed, not a credential problem.

## 3. Configure the sign-in screen (Google Auth Platform)

Open `https://console.cloud.google.com/auth/overview?project=PROJECT_ID`. This
area was called the "OAuth consent screen" until recently. If it asks you to
**Get started**, do that. It walks through the same settings as below.

- **Branding**
  - **App name:** something people will recognize months later in their
    Google account's [permissions list](https://myaccount.google.com/permissions),
    for example `GA tools for Claude & Codex (read-only)`. It also appears on the
    sign-in screen, which is how people confirm it's yours and not someone
    phishing them. Google rejects names containing "Google".
  - **User support email** and **developer contact:** an address your users
    can actually reach.
- **Audience:** **Internal** or **External**, as decided above.
  - **External:** under **Test users**, add the Google account of *every*
    person who will use the tools, including yourself. In Testing, Google
    refuses everyone not on the list, even the project owner, with
    `Error 403: access_denied`. Keep this list current as people join. The cap
    is 100.
- **Data access:** **leave it empty.** The tools ask for exactly two read-only
  permissions when each person signs in: `analytics.readonly` and
  `webmasters.readonly`. Declaring scopes here is what starts Google's
  verification requirements, and an empty list costs nothing.

## 4. Create the client and download the file

1. Go to **Clients → Create client** (in the same Google Auth Platform area).
2. **Application type: Desktop app.** This matters: it gives the
   `http://localhost` sign-in flow the tools use. A "Web application" client
   will not work.
3. **Name:** anything, for example `ga-mcp desktop`.
4. **Create**, then **Download JSON**. Google may not show the secret again
   later, but you can always create another client.
5. Rename the file to **`ga-mcp-client.json`**.

**Check the file** before handing it out. Open it in a text editor:

- the top-level key is `"installed"`. If it says `"web"`, you created the
  wrong client type; go back to step 4.2.
- `"redirect_uris"` contains `"http://localhost"`.

## 5. Where the file goes

On every machine that uses the tools, the installer looks for it here:

| | |
|---|---|
| macOS | `~/.config/gcloud/ga-mcp-client.json` |
| Windows | `%USERPROFILE%\.config\gcloud\ga-mcp-client.json` |

The installing agent (Claude or Codex) looks for the file in Downloads,
Desktop and Documents and copies it into place. It then offers to delete the
loose copy.

**About keeping it private.** For a Desktop client, the OAuth standard for
desktop apps (RFC 8252, which Google follows) treats the "client secret" in
this file as something that can't truly be kept secret, and Google designs
for that. The file can't read anyone's data
without that person signing in and approving. Even so:

- **Never commit it to git.** This package's `.gitignore` already excludes it.
- **Hand it over directly**: a password manager, a shared drive only your team
  can open, or in person. Don't send it over a public chat channel or a
  mailing list.
- If it leaks, delete the client in **Clients** and create a new one. Everyone
  then needs the new file and signs in once more.

## The two files, and which one actually matters

There are two JSON files in this system, and they are not alike.

| | `ga-mcp-client.json` (this guide) | `adc-ga-personal.json` (the credential) |
|---|---|---|
| What it is | Your *app's* identity with Google: "this is <your app name>, from Cloud project X" | One *person's* access: a refresh token for their Google account, limited to the two read-only permissions |
| Gives access to data? | No. By itself it can't read anything | Yes: everything that person's account can see in GA and Search Console |
| Who makes it | You, once, in this guide | Each person, on their own machine, during install |
| How | Download from the Cloud console | The install's consent step: `mint_adc.py` opens the browser, the person signs in and approves the two permissions, and the script writes the file, readable only by that user |
| Where it lives | `~/.config/gcloud/ga-mcp-client.json` on every machine | `~/.config/gcloud/adc-ga-personal.json`, on that person's machine only |
| Copies | One per deployment, handed to each person directly | Never copied, never shared, never in a zip or a repository |
| Lifetime | Until you delete the client in the Cloud console | External/Testing: **7 days**, then the person re-runs the renewal command (`credential_status` prints it) and fully quits and reopens their apps. Internal: long-lived |
| If it leaks | Someone could show a consent screen wearing your app's name, or use your project's quota. Fix: delete the client in **Clients**, create a new one, re-issue the file | Someone could read that person's analytics data until it expires. Fix: the person revokes the app at [myaccount.google.com/permissions](https://myaccount.google.com/permissions), which kills the token at once, then signs in again |

So: treat the client file like a building key card (keep it off public channels, re-issue if lost) and the credential like a password (it never moves). The install does the credential part for you; `INSTALL.md` step 4 ("Run consent") and the setup skill's Step 5 are where it happens, and `credential_status` is how anyone checks theirs afterwards.

## 6. Give people access to the data (in GA and Search Console, not here)

Nothing in the Cloud project grants access to analytics data. Each person sees
exactly what their own Google account can already see:

- **Google Analytics:** Admin → Property (or Account) **access management**, at
  least the **Viewer** role. Access granted at the *account* level covers all
  its properties.
- **Search Console:** Settings → **Users and permissions** for each property
  (Restricted is enough).

If someone signs in fine but sees no properties, this step is what's missing
for that person.

## 7. Try it yourself first

Install the tools on your own machine. Follow `INSTALL.md`, or point Claude
Code or Codex at `skills/ga-mcp-setup/SKILL.md`. At the sign-in step:

1. A browser opens with your app name. **External/Testing:** expect
   "Google hasn't verified this app". Click **Advanced → Go to … (unsafe)**,
   which is expected for a Testing app. **Internal:** no warning.
2. Approve the two permissions: viewing Google Analytics data and viewing
   Search Console data. Nothing else should be listed. If anything else is,
   stop and check you're using the right file.
3. The script prints the permissions it actually received. Both should be
   there.

Then ask your AI app a question such as "Is my Google Analytics credential
still valid?" and "What's the property ID for <one of your sites>?". When both
answer, your file is ready to hand out.

## 8. What to give the people you deploy to

- `ga-mcp-client.json` (from step 4), handed over directly.
- **External:** confirmation that you've added their Google account as a test
  user. Do this *before* they install, or sign-in fails with `access_denied`.
- The package (zip or repository).
- A name to send their install report to (the installer writes one). That's
  you.

---

## Troubleshooting

| What they see | What it means | Fix |
|---|---|---|
| `Error 403: access_denied` at sign-in | External/Testing, and this Google account isn't a test user | Add the exact account under **Audience → Test users**, then they sign in again |
| "This app is blocked" / "your institution's policy" | A Workspace administrator restricts third-party apps | An administrator trusts the client ID (Admin console → Security → API controls), or switch to an Internal app in your organization |
| "…API has not been used in project … or it is disabled" | Step 2 missed for that API | Enable it on the **same** project as the client |
| `invalid_grant` / "token expired" weekly | Expected for External/Testing: the 7-day credential (`adc-ga-personal.json`) has expired | They run the renewal command `credential_status` gives them, then fully quit and reopen the app. Internal avoids this |
| Someone's credential may have been exposed | `adc-ga-personal.json` left their machine | They revoke the app at myaccount.google.com/permissions (immediate), then sign in again at the next use |
| Signs in, but no properties | Their Google account has no GA/Search Console access | Step 6 |
| `redirect_uri_mismatch` | The client isn't a **Desktop app** | Create a Desktop app client (step 4) and replace the file |
| "Google hasn't verified this app" | Normal for External/Testing | **Advanced → Continue**. Only publishing and verification remove it |

---

*For maintainers of this package: your own project's notes, such as which
project ID and who is on the test-user list, belong in your private deployment
records, not here.*
