import { afterEach, describe, expect, it, vi } from 'vitest';
import { PALETTE } from '../ui/src/brand/palette.js';

const palette = new Set(Object.values(PALETTE).map((h) => h.toLowerCase()));

function captureBanner(): Promise<string> {
  // picocolors reads FORCE_COLOR at import time, so reload the modules with colour on.
  vi.resetModules();
  process.env.FORCE_COLOR = '1';
  const chunks: string[] = [];
  vi.spyOn(process.stdout, 'write').mockImplementation((c: string | Uint8Array) => {
    chunks.push(String(c));
    return true;
  });
  return import('../src/util/banner.js').then((m) => {
    m.renderBanner({ cliVersion: '1.2.3', poolVersion: '4.5.6' });
    return chunks.join('');
  });
}

describe('banner palette', () => {
  const oldForce = process.env.FORCE_COLOR;
  afterEach(() => {
    if (oldForce === undefined) delete process.env.FORCE_COLOR;
    else process.env.FORCE_COLOR = oldForce;
  });

  it('uses only brand palette colours', async () => {
    const out = await captureBanner();
    const used = [...out.matchAll(/\x1b\[38;2;(\d+);(\d+);(\d+)m/g)].map(
      (m) => '#' + [m[1], m[2], m[3]].map((n) => Number(n).toString(16).padStart(2, '0')).join(''),
    );
    expect(used.length).toBeGreaterThan(0);
    for (const c of used) expect(palette.has(c)).toBe(true);
  });

  it('prints the wordmark and the versions', async () => {
    const out = await captureBanner();
    expect(out).toContain('1.2.3');
    expect(out).toContain('4.5.6');
    expect(out).toContain('██████╗');
  });
});
