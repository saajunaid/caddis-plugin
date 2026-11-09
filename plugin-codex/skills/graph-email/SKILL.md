---
name: graph-email
description: Send a Markdown file as an email through Microsoft Graph or SMTP, as set in ~/.caddis/email.toml. Default recipient is the owner.
---

Use the `send-email` skill to send an email.

Arguments: $ARGUMENTS

1. Read the skill `send-email` first and follow it.
2. If `~/.caddis/email.toml` is missing, or `--check` fails, tell the owner to type `! caddis email setup` in the prompt, then stop. The `!` runs it in their own terminal, so the secret never enters the chat. Name what is missing (setting names only, never values). Do not guess values and do not ask for a secret in the chat.
3. The first argument is the Markdown file. If there is none, ask which file, or offer to write one in the project's `comms/` folder.
4. Subject: `caddis-<app-name> <subject>`. Take the app name from the project folder. If the owner gave subject words, use them.
5. Recipient: the owner's own address unless `--to` is given. If `--to` is any other address, confirm with the owner before sending.
6. Run a dry run, check the preview, then send. Report the provider, status, recipient and subject. Keep a copy of the file in `comms/`.
