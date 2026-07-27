---
name: version
description: Report the installed caddis version (baked in at build time — works in any host)
---

# /version — what caddis am I running?

Report the caddis toolchain version to the user, plainly:

> **caddis 1.3.34**

This string is substituted into this command at **build/export time**, so it reflects the exact
version of the installed plugin/bundle — no file reading, no host CLI needed, and it works identically
in Claude Code, agy (Antigravity), and any other agent the pool is exported to.

If the user asks how to update:
- **Claude Code:** `claude plugin update caddis@caddis` (then restart the session).
- **agy (Antigravity):** re-import the bundle — `agy plugin install <caddis-plugin-checkout>/bundles/antigravity-plugin` (then restart the agy session). agy has no version-gated auto-update yet.

Do not guess or infer the version from anything else — the value above is authoritative.
