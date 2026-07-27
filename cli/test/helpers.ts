import { vi } from 'vitest';
import type { AgentAdapter, AgentStatus, Detection, DriveResult } from '../src/agents/types.js';

/** Capture everything a command writes to stdout, with colour stripped. */
export function captureStdout(): { output: () => string; restore: () => void } {
  const chunks: string[] = [];
  const spy = vi.spyOn(process.stdout, 'write').mockImplementation((chunk: unknown) => {
    chunks.push(String(chunk));
    return true;
  });
  return {
    // eslint-disable-next-line no-control-regex
    output: () => chunks.join('').replace(/\[[0-9;]*m/g, ''),
    restore: () => spy.mockRestore(),
  };
}

/** A fully controllable adapter, for exercising the report/render layers. */
export function fakeAdapter(overrides: Partial<AgentAdapter> & { id: AgentAdapter['id'] } & {
  detection?: Detection;
  agentStatus?: AgentStatus;
  driveResult?: DriveResult;
}): AgentAdapter {
  const detection: Detection = overrides.detection ?? { present: true };
  const agentStatus: AgentStatus = overrides.agentStatus ?? { installed: true, version: '1.0.0' };
  const driveResult: DriveResult = overrides.driveResult ?? { ok: true, skipped: false, steps: [] };

  return {
    id: overrides.id,
    name: overrides.name ?? overrides.id,
    supported: overrides.supported ?? true,
    summary: overrides.summary ?? 'do the thing',
    detect: vi.fn(async () => detection),
    status: vi.fn(async () => agentStatus),
    drive: vi.fn(async () => driveResult),
  };
}
