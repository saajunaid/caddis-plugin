#!/bin/sh
# caddis-run — start an agent session inside a capped scope (see docs/guide/resource-protection.md in the caddis source repo).
# Always goes through the governor: an environment variable is not proof of a cap.
[ "$#" -eq 0 ] && { echo "usage: caddis-run <command> [args...]" >&2; exit 2; }
here=$(dirname "$0")
gov="$here/caddis_governor.py"
[ -f /etc/caddis/caddis_governor.py ] && gov=/etc/caddis/caddis_governor.py
py=$(command -v python3 || command -v python) || { echo "caddis-run: python not found; refusing to start ungoverned" >&2; exit 3; }
exec "$py" "$gov" exec --scope session -- "$@"
