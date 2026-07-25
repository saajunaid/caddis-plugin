#!/usr/bin/env sh
set -eu

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "$repo_root" ]; then
  echo "Not inside a git repository."
  exit 1
fi

cd "$repo_root"

if [ ! -d ".github/hooks" ]; then
  echo "Hooks source folder not found: .github/hooks"
  exit 1
fi

if [ ! -d ".git/hooks" ]; then
  echo "Git hooks target folder not found: .git/hooks"
  exit 1
fi

cat > .git/hooks/pre-commit <<'EOF'
#!/usr/bin/env sh
set -eu

if command -v pwsh >/dev/null 2>&1; then
  pwsh -NoProfile -ExecutionPolicy Bypass -File ".github/hooks/pre-commit-quality-gate.ps1"
else
  sh ".github/hooks/pre-commit-quality-gate.sh"
fi
EOF

cat > .git/hooks/commit-msg <<'EOF'
#!/usr/bin/env sh
set -eu

sh ".github/hooks/commit-msg-conventional.sh" "$1"
EOF

cat > .git/hooks/pre-push <<'EOF'
#!/usr/bin/env sh
set -eu

if command -v pwsh >/dev/null 2>&1; then
  pwsh -NoProfile -ExecutionPolicy Bypass -File ".github/hooks/pre-push-quality-gate.ps1"
else
  sh ".github/hooks/pre-push-quality-gate.sh"
fi
EOF

chmod +x .git/hooks/pre-commit .git/hooks/commit-msg .git/hooks/pre-push

echo "Installed hooks:"
echo "- .git/hooks/pre-commit"
echo "- .git/hooks/commit-msg"
echo "- .git/hooks/pre-push"
