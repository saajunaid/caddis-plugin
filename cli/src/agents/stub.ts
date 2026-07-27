/**
 * Detected-but-not-yet-driven agents.
 *
 * Codex and Copilot are FILE-configured — there is no plugin install to drive,
 * so supporting them means parse-merging their config/pool files in place. That
 * is the highest-risk operation in the whole tool (plan risk #2: clobbering a
 * user's config), and it is not shipping half-done. v0.1 detects them, says so
 * plainly, and touches nothing.
 */
import { existsSync } from 'node:fs';
import type { AgentAdapter, AgentId, AgentStatus, Detection, DriveOptions, DriveResult } from './types.js';
import { findBin } from '../util/which.js';

export interface StubSpec {
  id: AgentId;
  name: string;
  /** Binaries that indicate the agent is present. */
  bins: string[];
  /** Absolute config paths that indicate the agent is present. */
  configPaths: string[];
  summary: string;
}

export const NOT_YET_SUPPORTED = 'not yet supported (v0.2)';

export function createStubAdapter(spec: StubSpec): AgentAdapter {
  async function detect(): Promise<Detection> {
    for (const bin of spec.bins) {
      const found = await findBin(bin);
      if (found) return { present: true, path: found, note: NOT_YET_SUPPORTED };
    }
    for (const configPath of spec.configPaths) {
      if (existsSync(configPath)) return { present: true, path: configPath, note: NOT_YET_SUPPORTED };
    }
    return { present: false, note: `no ${spec.bins.map((b) => `\`${b}\``).join(' / ')} binary or config found` };
  }

  async function status(): Promise<AgentStatus> {
    const detected = await detect();
    return {
      installed: false,
      note: detected.present ? NOT_YET_SUPPORTED : 'agent not installed',
    };
  }

  async function drive(_action: unknown, _options: DriveOptions): Promise<DriveResult> {
    const detected = await detect();
    return {
      ok: true,
      skipped: true,
      steps: [],
      message: detected.present
        ? `${spec.name} detected — ${NOT_YET_SUPPORTED}, nothing changed`
        : `${spec.name} not installed — skipped`,
    };
  }

  return {
    id: spec.id,
    name: spec.name,
    supported: false,
    summary: spec.summary,
    detect,
    drive: drive as AgentAdapter['drive'],
    status,
  };
}
