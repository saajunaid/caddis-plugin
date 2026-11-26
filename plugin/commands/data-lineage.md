---
description: "Deprecated: use /lld. Redirects to /lld, which publishes through caddis_confluence.py"
argument-hint: (no arguments, deprecated, use /lld)
stage: plan
---

# /data-lineage (deprecated): use /lld

This command is deprecated and will be removed in the next release. Use `/lld` instead. `/lld` step 7 writes the data lineage matrix (domain -> source -> staging -> SP -> mart -> API -> UI) as Markdown in Git (`docs/<app>/<app>-data-lineage.md`) and publishes it as the `data-lineage` section of the LLD page with `python "<home>/.caddis/bin/caddis_run.py" caddis_confluence.py publish --page-id <ID> --slug data-lineage --input docs/<app>/<app>-data-lineage.md`. On agy and Codex, `/lld` is the `lld` skill. Run `/lld` now with the same request.
