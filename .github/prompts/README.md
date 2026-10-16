# Prompts Library

Prompts are reusable templates for common AI interactions. They provide structured ways to request specific outputs from AI assistants. **Use them in any IDE**: paste the template (or the file content) into your AI chat; some prompts mention Cursor commands (e.g. `/plan`)—in other IDEs, use the equivalent (e.g. paste the plan template) as described in each prompt.

## When to Use Prompts

- Repetitive tasks with consistent output format
- Quick interactions that don't require multi-phase workflows
- Templated outputs (READMEs, documentation, messages)
- One-shot generations

## Prompts vs Skills vs Agents

| Type | Purpose | Example |
|------|---------|---------|
| **Prompt** | Single-turn template | Generate a README |
| **Skill** | Multi-phase workflow | Build from PRD |
| **Agent** | Persona with expertise | Code reviewer |

## Available Prompts

### Documentation Prompts

| Prompt | Purpose |
|--------|---------|
| [create-readme.prompt.md](create-readme.prompt.md) | Generate project README files |
| [api-documentation.prompt.md](api-documentation.prompt.md) | Generate API docs |
| [documentation-writer.prompt.md](documentation-writer.prompt.md) | Diátaxis framework documentation |

### Code & Development Prompts

| Prompt | Purpose |
|--------|---------|
| [sql-review.prompt.md](sql-review.prompt.md) | Review SQL code |
| [debug-help.prompt.md](debug-help.prompt.md) | Structure debugging requests |
| [conventional-commit.prompt.md](conventional-commit.prompt.md) | Generate conventional commit messages |
| [mcp-development.prompt.md](mcp-development.prompt.md) | Create/modify MCP servers |
| [performance-optimization.prompt.md](performance-optimization.prompt.md) | Optimize code for performance |

### Project Understanding Prompts

| Prompt | Purpose |
|--------|---------|
| [first-ask.prompt.md](first-ask.prompt.md) | Initial project understanding |
| [project-setup.prompt.md](project-setup.prompt.md) | Set up new projects |
| [migrate-project.prompt.md](migrate-project.prompt.md) | Migrate projects between frameworks/versions |

### Session Management Prompts

| Prompt | Purpose |
|--------|---------|
| [plan.prompt.md](plan.prompt.md) | **Create phased execution plans** for multi-session work |
| [relay.prompt.md](relay.prompt.md) | Create or update root `relay.md` for session continuation |

> 💡 **Workflow Guidance**:
> - **For planned large work**: Create a phased plan at `plans/<feature>.md` (in Cursor: `/plan`; in other IDEs: paste the template from [plan.prompt.md](plan.prompt.md)).
> - **For session continuation**: Use Relay (in Cursor: `/relay`; in other IDEs: paste [relay.prompt.md](relay.prompt.md) and follow the skill). Relay writes `relay.md` at the repository root by default.
> - **For planned multi-session work**: use a plan document as the execution source of truth, then use Relay to capture the latest resume context when needed.

## Prompt Structure

Each prompt follows this format:

```markdown
# [Prompt Name]

## Purpose
What this prompt is for

## Input Required
What information to provide

## Template
The actual prompt template with placeholders

## Example
A filled-in example

## Expected Output
What to expect back
```

## Using Prompts

1. **Read the prompt** to understand required inputs
2. **Gather the information** specified in "Input Required"
3. **Fill in the template** with your specific context
4. **Use the prompt** with your AI assistant
5. **Refine if needed** based on output

## Creating New Prompts

When creating a new prompt:

1. **Identify the pattern**: What repeated task needs templating?
2. **Define inputs clearly**: What does the AI need to know?
3. **Structure the request**: Be specific about desired output
4. **Provide examples**: Show what good output looks like
5. **Test and iterate**: Refine based on actual outputs
