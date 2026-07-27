import type { AgentAdapter, AgentId } from './types.js';
import { claudeAdapter } from './claude.js';
import { agyAdapter } from './agy.js';
import { codexAdapter } from './codex.js';
import { copilotAdapter } from './copilot.js';

/** Registration order == display order everywhere. Supported agents first. */
export const ADAPTERS: AgentAdapter[] = [claudeAdapter, agyAdapter, codexAdapter, copilotAdapter];

export const AGENT_IDS: AgentId[] = ADAPTERS.map((adapter) => adapter.id);

/**
 * Resolve the --agent filter. Returns every adapter when unset.
 * Throws on an unknown id so a typo is not silently a no-op run.
 */
export function selectAdapters(filter?: string[]): AgentAdapter[] {
  if (!filter || filter.length === 0) return ADAPTERS;
  const wanted = filter.flatMap((value) => value.split(',')).map((value) => value.trim().toLowerCase()).filter(Boolean);
  const unknown = wanted.filter((value) => !AGENT_IDS.includes(value as AgentId));
  if (unknown.length > 0) {
    throw new Error(`unknown agent: ${unknown.join(', ')} (known: ${AGENT_IDS.join(', ')})`);
  }
  return ADAPTERS.filter((adapter) => wanted.includes(adapter.id));
}

export type { AgentAdapter, AgentId } from './types.js';
