---
name: adopt-rbac
description: >-
  Pointer to the org's RBAC adoption skill. Use for "add RBAC to this app" or "adopt rbac-kit".
---

# adopt-rbac (pointer)

RBAC adoption depends on organisation-specific things: the shared package and its pin, the auth
proxy that supplies identity, prod paths, the rollout order. So the real skill lives in the
organisation's private platform repo, next to the package it describes:

    <PLATFORM_REPO>/.claude/skills/adopt-rbac/SKILL.md

**Find it, read it in full, and follow it.** This pointer only makes it findable from a session
opened in another repo.

1. If `.github/project-config.md` sets `<PLATFORM_REPO>`, use that checkout.
2. Otherwise look in the folders next to the current project for one that contains
   `.claude/skills/adopt-rbac/SKILL.md`.
3. If the repo is only on the remote, read the file with `gh api` from the platform repo.
4. If none of these works, stop and ask the user where it is. Do not improvise RBAC from memory:
   improvised copies drift, and a drifted copy is how a privilege escalation ships.

The skill and the package live in one repo on purpose, so a package change and its skill update
land in the same PR.
