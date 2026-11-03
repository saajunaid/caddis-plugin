---
name: graph-email
description: Send a Markdown file as an email through Microsoft Graph or SMTP, as set in ~/.caddis/email.toml. Default recipient is the owner.
---

Use the `graph-email` skill to send an email.

Arguments: $ARGUMENTS

1. Read the skill `graph-email` first and follow it.
2. If `~/.caddis/email.toml` is missing, or `--check` fails, tell the owner what is missing and stop. Do not guess values.
3. The first argument is the Markdown file. If there is none, ask which file, or offer to write one in the project's `comms/` folder.
4. Subject: `caddis-<app-name> <subject>`. Take the app name from the project folder. If the owner gave subject words, use them.
5. Recipient: the owner's own address unless `--to` is given. If `--to` is any other address, confirm with the owner before sending.
6. Run a dry run, check the preview, then send. Report the provider, status, recipient and subject. Keep a copy of the file in `comms/`.
