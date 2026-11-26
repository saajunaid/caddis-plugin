---
name: confluence-hla
description: "Deprecated: use /hla. Redirects to the /hla skill, which publishes through caddis_confluence.py"
---

# confluence-hla (deprecated): use /hla

This skill is deprecated and will be removed in the next release. Use `/hla` instead. `/hla` writes the High-Level Architecture as Markdown in Git (`docs/<app>/<app>-hla.md`) and publishes it with `python "<home>/.caddis/bin/caddis_run.py" caddis_confluence.py publish --page-id <ID> --slug hla --input docs/<app>/<app>-hla.md`, which renders each Mermaid figure to a 2x PNG attachment. On agy and Codex, `/hla` is the `hla` skill. Run `/hla` now with the same request.
