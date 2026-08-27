import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { afterAll, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../src/util/which.js', () => ({ findBin: vi.fn() }));

import { createStubAdapter, NOT_YET_SUPPORTED } from '../src/agents/stub.js';
import { codexAdapter } from '../src/agents/codex.js';
import { copilotAdapter } from '../src/agents/copilot.js';
import { findBin } from '../src/util/which.js';

const mockWhich = vi.mocked(findBin);
const scratch = mkdtempSync(path.join(tmpdir(), 'caddis-stub-'));
afterAll(() => rmSync(scratch, { recursive: true, force: true }));

beforeEach(() => mockWhich.mockReset());

describe('stub adapters', () => {
  // Codex graduated to a real adapter on 2026-08-27, after its export target was
  // live-fired. Copilot is the last remaining stub — this file keeps covering the stub
  // MACHINERY through it, so retiring the final stub stays a deliberate act.
  it('copilot is the only adapter still unsupported', () => {
    expect(copilotAdapter.supported).toBe(false);
    expect(codexAdapter.supported).toBe(true);
  });

  it('detect via the binary and say why they are not driven', async () => {
    mockWhich.mockResolvedValue('C:\\bin\\copilot.CMD');
    const detected = await copilotAdapter.detect();
    expect(detected).toMatchObject({ present: true, path: 'C:\\bin\\copilot.CMD', note: NOT_YET_SUPPORTED });
  });

  it('detect via a config path when no binary exists', async () => {
    mockWhich.mockResolvedValue(null);
    const configFile = path.join(scratch, 'config-marker');
    writeFileSync(configFile, 'x');
    const adapter = createStubAdapter({
      id: 'codex',
      name: 'Codex',
      bins: ['nope-not-a-real-binary'],
      configPaths: [configFile],
      summary: 's',
    });
    expect(await adapter.detect()).toMatchObject({ present: true, path: configFile });
  });

  it('report absent when neither binary nor config exists', async () => {
    mockWhich.mockResolvedValue(null);
    const adapter = createStubAdapter({
      id: 'copilot',
      name: 'GitHub Copilot',
      bins: ['nope'],
      configPaths: [path.join(scratch, 'does-not-exist')],
      summary: 's',
    });
    expect((await adapter.detect()).present).toBe(false);
  });

  it('NEVER drive anything, even when detected', async () => {
    mockWhich.mockResolvedValue('/bin/copilot');
    const result = await copilotAdapter.drive('update', { dryRun: false });
    expect(result).toMatchObject({ ok: true, skipped: true, steps: [] });
    expect(result.message).toContain(NOT_YET_SUPPORTED);
  });

  it('report status as not-installed with the v0.2 note', async () => {
    mockWhich.mockResolvedValue('/bin/copilot');
    expect(await copilotAdapter.status()).toMatchObject({ installed: false, note: NOT_YET_SUPPORTED });
  });
});
