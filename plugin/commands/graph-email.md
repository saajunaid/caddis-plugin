---
description: Send a Markdown file as an email through Microsoft Graph or SMTP, as set in ~/.caddis/email.toml. Default recipient is the owner.
argument-hint: <file.md> [subject words] [--to address] [--attach file]
stage: ship
---

Use the `send-email` skill to send an email.

Arguments: $ARGUMENTS

1. Read the skill `send-email` first and follow it.
2. If `~/.caddis/email.toml` is missing, or `--check` fails, tell the owner to type `! caddis email setup` in the prompt, then stop. The `!` runs it in their own terminal, so the secret never enters the chat. Name what is missing (setting names only, never values). Do not guess values and do not ask for a secret in the chat.
3. The first argument is the Markdown file. If there is none, ask which file, or offer to write one in the project's `comms/` folder.
4. Body: write it for its final reader, ready to forward with no edits (`Hi,` or `Hi DBA team,`, never `Hi <owner>, below is...`). Keep it short: the answer, one small table or a few bullets, the ask. Long detail goes in an attachment.
5. Subject: for a note to the owner alone, `caddis-<app-name> <subject>` (app name from the project folder). For a note to forward to another team, a plain subject with no prefix. If the owner gave subject words, use them.
6. Sign-off: `Thanks,` on one line, then the `signature` value from `~/.caddis/email.toml` (when unset, the first word of `git config user.name`) on the next line. Never sign as Claude, an agent, a session name or the mailbox.
7. Recipient: the owner's own address unless `--to` is given. If `--to` is any other address, confirm with the owner before sending.
8. Run a dry run, check the preview, then send. Report the provider, status, recipient and subject. Keep a copy of the file in `comms/`.
