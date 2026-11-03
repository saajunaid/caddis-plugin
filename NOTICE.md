# Third-party notices

The following skill files contain third-party terms or were identified as derived skills. The upstream and licence fields reflect each file itself.

- `.github/skills/coding/backend-development/SKILL.md` | wshobson/agents | MIT
- `.github/skills/coding/code-review/SKILL.md` | anthropics/claude-code | Apache-2.0
- `.github/skills/coding/javascript-typescript/SKILL.md` | wshobson/agents | MIT
- `.github/skills/coding/llm-application-dev/SKILL.md` | wshobson/agents | MIT
- `.github/skills/coding/mcp-builder/SKILL.md` | anthropics/skills | Apache-2.0
- `.github/skills/coding/python/SKILL.md` | wshobson/agents | MIT
- `.github/skills/data/database-design/SKILL.md` | wshobson/agents | MIT
- `.github/skills/devops/port-to-github/SKILL.md` | upstream not stated in the file | licence not stated in the file
- `.github/skills/devops/using-git-worktrees/SKILL.md` | obra/superpowers (derived; named in the R1 plan, not in the file; first copy before Feb 2026). No text was taken from `using-git-worktrees` 7.0.2, but it is recorded in `.github/upstream-sources.json` so a change upstream shows as drift | MIT
- `.github/skills/docs/code-documentation/SKILL.md` | wshobson/agents | MIT
- `.github/skills/docs/document-skills/docx/SKILL.md` | upstream not stated in the file | Proprietary. LICENSE.txt has complete terms
- `.github/skills/docs/document-skills/pdf/SKILL.md` | upstream not stated in the file | Proprietary. LICENSE.txt has complete terms
- `.github/skills/docs/document-skills/pptx/SKILL.md` | upstream not stated in the file | Proprietary. LICENSE.txt has complete terms
- `.github/skills/docs/document-skills/xlsx/SKILL.md` | upstream not stated in the file | Proprietary. LICENSE.txt has complete terms
- `.github/skills/docs/writing-plans/SKILL.md` | obra/superpowers `writing-plans` (the first copy predates Feb 2026; the skill is now a pointer to `/caddis:feature-plan`). Ideas from `writing-plans` 7.0.0 are adapted in `claude-harness/commands/feature-plan.md`, and from `subagent-driven-development` 7.0.2 in `claude-harness/commands/implement.md`; both are tracked in `.github/upstream-sources.json` | MIT
- `.github/skills/frontend/artifacts-builder/SKILL.md` | upstream not stated in the file | Complete terms in LICENSE.txt
- `.github/skills/frontend/banner-design/SKILL.md` | upstream not stated in the file | MIT
- `.github/skills/frontend/brand-design/SKILL.md` | upstream not stated in the file | MIT
- `.github/skills/frontend/brand-guidelines/SKILL.md` | upstream not stated in the file | Apache-2.0
- `.github/skills/frontend/canvas-design/SKILL.md` | upstream not stated in the file | Apache-2.0
- `.github/skills/frontend/design-md/SKILL.md` | NousResearch/hermes-agent | licence not stated in the file
- `.github/skills/frontend/design-system-tokens/SKILL.md` | upstream not stated in the file | MIT
- `.github/skills/frontend/theme-factory/SKILL.md` | upstream not stated in the file | Complete terms in LICENSE.txt
- `.github/skills/frontend/ui-styling-patterns/SKILL.md` | upstream not stated in the file | MIT
- `.github/skills/productivity/internal-comms/SKILL.md` | anthropics/skills | Apache-2.0
- `.github/skills/productivity/jira-issues/SKILL.md` | upstream not stated in the file | MIT
- `.github/skills/testing/tdd-workflow/SKILL.md` | obra/superpowers (derived; named in the R1 plan, not in the file; upstream version not recorded, copied before Feb 2026) | MIT
- `.github/skills/testing/webapp-testing/SKILL.md` | upstream not stated in the file | Complete terms in LICENSE.txt
- `.github/skills/workflow/agent-md-refactor/SKILL.md` | upstream not stated in the file | MIT
- `.github/skills/workflow/brainstorming/SKILL.md` | obra/superpowers `brainstorming` 7.0.2 (the first copy was before Feb 2026). `builder-check-prompt.md` is adapted from the same version; both are tracked in `.github/upstream-sources.json` | MIT

caddis owns only the routing-critical superpowers skills (`brainstorming`, `writing-plans`, `executing-plans`, `subagent-driven-development`, `using-git-worktrees`) and blocks their superpowers twins with deny rules. The other superpowers skills (`systematic-debugging`, `verification-before-completion`, `test-driven-development`, `receiving-code-review`, `writing-skills` and the rest) are used directly from the superpowers plugin and are not copied.
