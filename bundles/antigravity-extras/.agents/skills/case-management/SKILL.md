---
name: case-management
description: >-
  Pointer to the org's case-management blueprint. Use for "add case management".
---

# case-management (pointer)

The blueprint is drawn from a live, organisation-specific implementation, so it lives in the
organisation's private platform repo:

    <PLATFORM_REPO>/.claude/skills/case-management/SKILL.md

**Find it, read it in full, and follow it.** This pointer only makes it findable from a session
opened in another repo. Case management needs RBAC first: see the sibling **adopt-rbac** skill.

1. If `.github/project-config.md` sets `<PLATFORM_REPO>`, use that checkout.
2. Otherwise look in the folders next to the current project for one that contains
   `.claude/skills/case-management/SKILL.md`.
3. If the repo is only on the remote, read the file with `gh api` from the platform repo.
4. If none of these works, stop and ask the user where it is.

It is a blueprint, not a package yet. When a second app adopts case management, the blueprint
says to extract the generic half into a `case-kit` package with that app as the first consumer.
