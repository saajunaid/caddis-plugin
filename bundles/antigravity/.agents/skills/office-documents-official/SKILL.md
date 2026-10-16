---
name: office-documents-official
description: Hint for Office and PDF file work. Use when the user asks to create, edit, read or convert a Word .docx, PDF, PowerPoint .pptx or Excel .xlsx file. caddis does not ship these skills; points to Anthropic's official document-skills plugin.
---

# Office and PDF files: use Anthropic's document-skills

caddis does not include skills for Word (.docx), PDF, PowerPoint (.pptx) or Excel (.xlsx) files.
These skills belong to Anthropic. Anthropic publishes them as the `document-skills` plugin.

## Install (Claude Code)

```
/plugin marketplace add anthropics/skills
/plugin install document-skills@anthropic-agent-skills
```

Source: https://github.com/anthropics/skills (see its README, section "Claude Code").

## What to do

1. If the plugin is installed, use its `docx`, `pdf`, `pptx` or `xlsx` skill for the file type. Do not work from this note.
2. If the plugin is not installed, tell the user the two commands above. Then ask if they want to install it first.
3. If the user cannot install it, say what you can do without it. For example, write the content as Markdown and let the user convert it.
