# Setting up your own Google App (OAuth client)

To give your AI agent read-only access to your Google Analytics and Search Console data, Google requires an app of your own, which we call a "Google App". This page explains what that is, what you'll create, and walks you (or your agent) through it.

## What it's called

In Google's own terms, the component we call the **Google App** is an **OAuth client** inside a **Google Cloud project**. The steps below use those names, because they are the names you will see on Google's screens as you proceed with setup.

## Who needs to set this up

You only need to set up the OAuth client inside a Google Cloud project if:

* You're setting it up just for yourself.

* You're setting it up for a team or organization.

You do this once. If others will use Data Noodler, everyone you deploy to uses the file you make here.

You do NOT need to set up the OAuth client inside a Google Cloud project if:

* You are upgrading an existing (and working) Data Noodler installation.

* You are part of a group of users supported by someone else who maintains the OAuth client inside the Google Cloud project.

**If you do not need to set this up, you can skip the remainder of this document.**

## What you'll end up with

- **In Google Cloud:** a project with three APIs turned on, a sign-in screen, and an OAuth client.
- **On your machine:** one file, `data-noodler-client.json`, downloaded from the OAuth client inside the Google Cloud project. You will use this file yourself, and if you support others who use Data Noodler, you will distribute this to them as well (step 8).

**Time:** about 20 minutes. **Cost:** none. The APIs this uses don't need a billing account (true at the time of writing).

## What this shares, and what it doesn't

Everyone you deploy to gets the same `data-noodler-client.json`. This file tells Google which app is requesting permission to connect. On its own, it can't open anyone's data: each person still signs in with their own Google account.

When each person signs in, Google gives *them* their own credential: a token saved on their own machine, in `data-noodler-credential.json`. It grants read-only access to the Google Analytics and Search Console data that person can already see, and nothing more.

- **People in the same group don't share access.** Each has their own credential, limited to their own permissions.
- **Whoever manages Data Noodler for a group can't see their users' data or credentials.** They can see which accounts they listed as test users, and how much the APIs are used overall (request counts and errors in the Cloud console), but not what anyone asked or what came back.
- **What your AI agent reads** becomes part of your conversation with your AI app (Claude, ChatGPT), and is handled the same way as anything else you share there.

---

Google renames things in the Cloud console fairly often. If a label below has moved, the step is still there under a nearby name. Please [let us know](../README.md#feedback) so the guide can be updated.

## 1. Create the project

1. Go to **console.cloud.google.com**. This is the Google Cloud console.
2. Use the project picker at the top → **New project**.
   - **Name:** something you'll recognize later, for example
     `data-noodler` or `analytics-ai-tools`.
   - **Organization / Location:** leave it as Google suggests ("No organization" on a personal account).
3. **Write down the project ID.** Google adds digits when a name is taken, so
   it looks like `data-noodler-483921` rather than what you typed. Every link below
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
    sign-in screen, which is how people confirm the request really comes from you. Google rejects names containing "Google".
  - **User support email** and **developer contact:** an address your users
    can actually reach.
- **Audience:** **External**, and leave it in **Testing**.
  - Under **Test users**, add the Google account of *every*
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
3. **Name:** anything, for example `data-noodler desktop`.
4. **Create**, then **Download JSON**. Google may not show the secret again
   later, but you can always create another client.
5. Rename the file to **`data-noodler-client.json`**.

**Check the file** before handing it out. Open it in a text editor:

- the top-level key is `"installed"`. If it says `"web"`, you created the
  wrong client type; go back to step 4.2.
- `"redirect_uris"` contains `"http://localhost"`.

## 5. Where the file goes

On every machine that uses the tools, the installer looks for it here:

| | |
|---|---|
| macOS | `~/.config/gcloud/data-noodler-client.json` |
| Windows | `%USERPROFILE%\.config\gcloud\data-noodler-client.json` |

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

| | `data-noodler-client.json` (this guide) | `data-noodler-credential.json` (the credential) |
|---|---|---|
| What it is | Your *app's* identity with Google: "this is <your app name>, from Cloud project X" | One *person's* access: a refresh token for their Google account, limited to the two read-only permissions |
| Gives access to data? | No. By itself it can't read anything | Yes: everything that person's account can see in GA and Search Console |
| Who makes it | You, once, in this guide | Each person, on their own machine, during install |
| How | Download from the Cloud console | The install's consent step: `mint_adc.py` opens the browser, the person signs in and approves the two permissions, and the script writes the file, readable only by that user |
| Where it lives | `~/.config/gcloud/data-noodler-client.json` on every machine | `~/.config/gcloud/data-noodler-credential.json`, on that person's machine only |
| Copies | One per deployment, handed to each person directly | Never copied, never shared, never in a zip or a repository |
| Lifetime | Until you delete the client in the Cloud console | **7 days**, then the person runs the renewal command (their AI agent can give it to them) and fully quits and reopens their apps |
| If it leaks | Someone could show a consent screen wearing your app's name, or use your project's quota. Fix: delete the client in **Clients**, create a new one, re-issue the file | Someone could read that person's analytics data until it expires. Fix: the person revokes the app at [myaccount.google.com/permissions](https://myaccount.google.com/permissions), which kills the token at once, then signs in again |

So: treat the client file like a building key card (keep it off public channels, re-issue if lost) and the credential like a password (it never moves). The install does the credential part for you; `INSTALL.md` step 4 ("Run consent") and the setup skill's Step 5 are where it happens, and anyone can ask their AI agent to check theirs afterwards (the agent uses its `credential_status` tool).

## 6. If others will use it: give them access in Google Analytics and Search Console

Nothing in the Cloud project grants access to analytics data. Each person sees
exactly what their own Google account can already see. Therefore, if you are managing a group of users, make sure you have given each of them access to the right Google Analytics and Search Console properties.

## 7. Try it yourself first

Install the tools on your own machine. Follow `INSTALL.md`, or point Claude
Code or Codex at `skills/data-noodler-setup/SKILL.md`. At the sign-in step:

1. A browser opens with your app name. Expect "Google hasn't verified this app". Click **Advanced → Go to … (unsafe)**, which is expected for a Testing app.
2. Approve the two permissions: viewing Google Analytics data and viewing
   Search Console data. Nothing else should be listed. If anything else is,
   stop and check you're using the right file.
3. The script prints the permissions it actually received. Both should be
   there.

Then ask your AI app a question such as "Is my Google Analytics credential
still valid?" and "What's the property ID for <one of your sites>?". When both
answer, your file is ready to hand out.

## 8. What to give the people you deploy to

- `data-noodler-client.json` (from step 4), handed over directly.
- Confirmation that you've added their Google account as a test
  user. Do this *before* they install, or sign-in fails with `access_denied`.
- The package (zip or repository).
- A name to send their install report to (the installer writes one). That's
  you.

---

## Troubleshooting

| What they see | What it means | Fix |
|---|---|---|
| `Error 403: access_denied` at sign-in | This Google account isn't a test user in the OAuth app in Google Cloud console | Add the exact account under **Audience → Test users** in your app in Google Cloud console. Users can sign in again afterwards |
| "This app is blocked" / "your institution's policy" | Your Google Workspace administrator restricts third-party apps | Ask your administrator to allow the app |
| "…API has not been used in project … or it is disabled" | Step 2 missed for that API | Enable it on the **same** project as the client |
| `invalid_grant` / "token expired" weekly | Expected: the 7-day credential (`data-noodler-credential.json`) has expired | They ask their AI agent for the renewal command, run it, then fully quit and reopen the app |
| Someone's credential may have been exposed | `data-noodler-credential.json` left their machine | They revoke the app at [myaccount.google.com/permissions](https://myaccount.google.com/permissions), which cuts it off at once, then sign in again at the next use |
| Signs in, but no properties | Their Google account has no GA/Search Console access | Step 6 |
| `redirect_uri_mismatch` | The OAuth client isn't a **Desktop app** | Create a Desktop app client (step 4) in Google Cloud console and replace the file |
| "Google hasn't verified this app" | Normal for an app in Testing | **Advanced → Continue**. Only publishing and verification remove it |

**Note:** Some organizations use Google Workspace, which may let you create the OAuth client as an **Internal** app. If that's an option for you, follow your organization's own policies and approach for creating new apps. This guide covers External apps in Testing only.

---

*For maintainers of this package: your own project's notes, such as which
project ID and who is on the test-user list, belong in your private deployment
records, not here.*
