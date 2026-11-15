---
name: send-email
description: Email a Markdown file via Microsoft Graph or SMTP. Use to email a draft or note.
---

# send-email

Sends one email. The provider is `graph` (Microsoft Graph `sendMail`, client credentials) or `smtp`.
The body is a Markdown file. The script turns it into simple HTML. It never prints a secret or a token.

## One-time setup (per machine)

Run `caddis email setup` in a terminal. In a Claude Code session, type `! caddis email setup` in the prompt: the `!`
runs it in your terminal, so the secret never enters the chat. It asks for the provider, the sender mailbox and the
secrets (an env file you already have, or the values, which it saves to `~/.caddis/email.env`). It writes
`~/.caddis/email.toml`, then runs the check. `caddis email check` repeats the check at any time.

Manual setup, if the command is not available:

1. Copy `email.toml.example` from this skill folder to `~/.caddis/email.toml`.
2. Set `provider`, `sender` and `env_file`. For SMTP also set the `[smtp]` table.
3. Put the secrets in the env file, not in the config file:
   - graph: three keys. The default names are `ALERT_GRAPH_TENANT_ID`, `ALERT_GRAPH_CLIENT_ID`, `ALERT_GRAPH_CLIENT_SECRET`. Change the names in the `[graph]` table if your file uses other names.
   - smtp: one key. The default name is `EMAIL_SMTP_PASSWORD`. Change it with `password_key`.
4. Check the setup. This sends nothing and prints no secret:
   `python -I scripts/send_email.py --check`

Every setting can be overridden. The order is: command-line flag, then environment variable, then the config file.
The variables are `CADDIS_EMAIL_PROVIDER`, `CADDIS_EMAIL_SENDER`, `CADDIS_EMAIL_ENV_FILE`, `CADDIS_EMAIL_CONFIG`
and `CADDIS_EMAIL_SMTP_HOST`, `_PORT`, `_SECURITY`, `_USERNAME`, `_TIMEOUT`. The flags are `--provider`, `--sender`,
`--env-file`, `--config`, `--smtp-host`, `--smtp-port`, `--smtp-security` (`starttls`, `ssl` or `none`),
`--smtp-username`, `--smtp-timeout`. The old names `GRAPH_EMAIL_ENV_FILE` and `GRAPH_EMAIL_SENDER` still work.
Secrets can also be set as process environment variables. They win over the env file.
With smtp security `none`, the script refuses a username or password and exits with code 2. Use `starttls` or `ssl`.
For a local test relay only, set `allow_insecure_auth = true` (a boolean) in the `[smtp]` table.

## Steps

1. Write the email as a Markdown file in the project's `comms/` folder (a copy stays in the repo).
   - **Write it for its final reader, ready to forward with no edits.** The owner receives it, but a note meant
     for a team is written to that team: `Hi,` or `Hi DBA team,`, never `Hi <owner>, below is the note...`.
     Write to the owner only when the note is for the owner alone.
   - **Keep it short:** the answer first, then one small table or a few bullets, then the ask. Put long detail
     in an attachment (`--attach`), not in the body.
   - Put `<!-- email-start -->` before the greeting and `<!-- email-end -->` after the sign-off. Only that part is sent.
   - Write plain, short sentences. No em dashes, no arrows, no emoji, no check marks.
   - Sign off with `Thanks,` on one line and the owner's name on the next line. The name is the `signature` value
     in `~/.caddis/email.toml`; when it is not set, the first word of `git config user.name`. Never sign as
     Claude, an agent, a bot, a session name or the sender mailbox.
   - Write a list as `1.` or `-` lines, one item per line. Wrapped lines join into one paragraph. To force a new
     line inside a paragraph, end the line with `\`. The sign-off line keeps its break by itself.
   - A table needs a header row and a separator row (`|---|---|` or `--- | ---`). Outer pipes are optional.
     Raw HTML is escaped, so write tables in Markdown.
2. Subject line:
   - A note for the owner alone: `caddis-<app-name> <short subject>`, for example `caddis-myapp Weekly report check`.
   - A note to forward to another team: a plain subject with no prefix, for example `Data request for the weekly report`.
3. Dry run. It sends nothing, needs no credentials and writes `<file>.preview.html`:
   `python -I scripts/send_email.py --dry-run --to x@example.com --subject t --body-file <file.md>`
   Read the preview, then delete it.
4. Send:
   `python -I scripts/send_email.py --to <address> --subject '<subject>' --body-file <file.md> [--attach <file> ...]`
   `--to` can repeat. Graph HTTP 202 means Graph accepted the mail. An SMTP "accepted" means the server took it.
   Neither proves the inbox received it.
5. Tell the owner what was sent, to whom, and the subject.

## Rules

- **Default recipient is the owner's own address.** The owner forwards it, so the body is written for the final
  reader (Step 1). Send to a team only when the owner says so in this request. Sending to any other address is an
  outward action: confirm first.
- Never put personal data, secrets, payment data or customer text in the body.
- Errors show the provider, the HTTP or SMTP status code and the error name. Do not retry in a loop.
- Exit codes: 0 done, 1 provider error, 2 missing or invalid setting.

Script: `scripts/send_email.py` in this skill folder (Python 3.11 or later, standard library only).
