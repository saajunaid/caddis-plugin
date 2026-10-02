# caddis for Codex CLI

Codex reads the Claude plugin format verbatim, so this installs from the same marketplace:

```
codex plugin marketplace add https://github.com/saajunaid/caddis-plugin
codex plugin add caddis-codex@caddis
```

**Install `caddis-codex`, not `caddis`.** The plain `caddis` plugin installs cleanly in Codex and
its skills work — but Codex has **no command concept**, so all 41 `/caddis:*` commands are inert
there. This bundle reshapes every one of them into a skill, which is the form Codex loads.

Nothing to set: the skills find their scripts in the installed plugin folder.

## What is here

| | |
|---|---|
| `skills/` | the caddis skill pool, plus all 41 commands reshaped into skills |
| `scripts/` | the scripts those skills call |
| `agents/` | agent definitions |

Skills are flat — `skills/<name>/SKILL.md` — which is what Codex loads. Measured in a live
install: 134 flat versus 6 nested.
