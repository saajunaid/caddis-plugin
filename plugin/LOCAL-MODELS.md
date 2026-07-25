---
Original Author: Claude Code
Creation Date: 2026-06-08T09:16:59Z
Creating Model: claude-opus-4-8
---

# Running the caddis harness on local models

Status: **supported in principle, unproven in our harness.** The seam is wired and the models are known;
the live validation (below) runs once the vLLM endpoint exists. This file is the enablement checklist —
when vLLM is up, it should be ~15 minutes, not a research task.

## The models (served by vLLM)
| LiteLLM name | Model | Maps to | Role |
|---|---|---|---|
| `qwen2.5-vl-32b` | Qwen2.5-VL-32B-Instruct | `opus` tier | planning / verification (strongest + vision) |
| `qwen2.5-coder-14b` | Qwen2.5-Coder-14B-Instruct | `sonnet` tier | coding / review |
| `mistral-7b` | Mistral-7B-Instruct-v0.3 | `haiku` tier | bulk / fast |
| `deepseek-coder-v2-lite` | DeepSeek-Coder-V2-Lite | alt coder | swap into sonnet for speed |
| `gemma-4-12b-qat` | Gemma-4-12B-QAT | alt mid | constrained GPU |
| `gemma-4-e4b` | Gemma-4-E4B | alt tiny | classification |
| `nomic-embed` | Nomic-Embed-Text-v1.5 | — | embeddings/RAG only (NOT a chat tier) |

## Tier → model mapping (this is the whole mapping; there is no separate config file)

Subagent `model:` frontmatter is a **logical tier** (`opus`/`sonnet`/`haiku`), not a hard model ID.
Routing is resolved at the **gateway** (Claude Code's `ANTHROPIC_BASE_URL` → your LiteLLM proxy), not by
any file in this repo — so the table below is documentation of intent, and the proxy config
(`litellm.config.example.yaml`) is what actually executes.

| Tier | `default` (Anthropic, out-of-the-box) | `hybrid` (recommended) | `local` (all on-prem) |
|---|---|---|---|
| `opus` (plan/verify) | `claude-opus-4-8` | `claude-opus-4-8` (remote) | `qwen2.5-vl-32b` |
| `sonnet` (code/review) | `claude-sonnet-4-6` | `qwen2.5-coder-14b` (local) | `qwen2.5-coder-14b` |
| `haiku` (bulk/fast) | `claude-haiku-4-5` | `mistral-7b` (local) | `mistral-7b` |

**Role → tier** (intent, independent of which concrete model fills the tier): planner/verify → `opus`;
coder/reviewer → `sonnet`; bulk → `haiku`.

**Alternates** (documented, swap in via the proxy as your GPU allows): `deepseek-coder-v2-lite` (fast MoE
coder → sonnet for speed), `gemma-4-12b-qat` (efficient quantized mid, constrained GPU), `gemma-4-e4b`
(tiny/ultra-fast → haiku for classification). `nomic-embed` is embeddings/RAG only — never a chat tier.

> There is intentionally **no `model-aliases.json`**: nothing consumed it, and the gateway already owns
> resolution. Keep this table + `litellm.config.example.yaml` as the single source of truth.

## Enablement checklist
1. **vLLM up** — confirm the endpoint serves the models; note its base URL.
2. **LiteLLM proxy** — `pip install 'litellm[proxy]'`; copy `litellm.config.example.yaml`; set
   `VLLM_BASE_URL` (and `ANTHROPIC_API_KEY` for the hybrid profile); `litellm --config <file>`.
3. **Point Claude Code at it** (PowerShell):
   ```powershell
   $env:ANTHROPIC_BASE_URL = "http://localhost:4000"
   $env:ANTHROPIC_AUTH_TOKEN = "<litellm master key>"
   $env:CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY = "1"
   ```
4. **Pick a profile** (the tier→model table above):
   - `hybrid` (recommended first) — Opus plans/verifies (remote), local model codes. Lowest risk:
     the strong model owns the plan, the local model only executes it.
   - `local` — everything local. Use once the hybrid path is proven.
5. **In-session model switch** — `/model` swaps the **main-thread** model anytime (plan on Opus, then
   `/model` to a local coder to implement). Note: dispatched subagents keep their `model:` tier — under
   the gateway that tier resolves to whatever the proxy maps it to, not to the main thread's choice.

## Validation spike (run this FIRST, once vLLM is live)
This tests the one real unknown — **can a local coder execute our plan files?** (the planner→coder risk).
1. Pick a small, explicit plan (e.g. a `/feature-plan` output with the local-coder gate passed).
2. `/model` to `qwen2.5-coder-14b`; implement Phase 1 from the plan **only** (no extra reasoning).
3. Dispatch `tester` + `code-reviewer` (these can stay on Opus/remote) to judge the result.
4. **Pass = the plan was explicit enough.** Fail = note exactly where the coder needed reasoning the
   plan didn't supply, and tighten the `/feature-plan` gate. Record findings; this calibrates how much
   scaffolding our plans need for weak coders (see backlog §K — scaffolding is a function of model capability).

## Troubleshooting
- **`invalid beta flag` / 400s** — Claude Code sends `anthropic-beta` headers local backends reject.
  Strip them at the proxy (LiteLLM header transform) or disable the offending Claude Code beta.
- **Model not in `/model` picker** — set `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1` and confirm the
  proxy's `/v1/models` lists them.
- **Param errors from local models** — `drop_params: true` is set in the example config.
- **Subagent ran on the wrong model** — subagents use their frontmatter tier, not the main `/model`.
  Check the tier→model mapping the proxy applies.
