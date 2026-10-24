import { existsSync, mkdtempSync, readdirSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { DEFAULT_ASSETS, buildFonts } from '../../scripts/build-ui-fonts.mjs';

let tmp: string;
beforeEach(() => {
  tmp = mkdtempSync(path.join(tmpdir(), 'caddis-hub-fonts-'));
});
afterEach(() => rmSync(tmp, { recursive: true, force: true }));

describe('build-ui-fonts (R27)', () => {
  it('writes woff2 files and a CSS file with no data: URL', () => {
    const cssOut = path.join(tmp, 'fonts.generated.css');
    const names = buildFonts({ publicDir: tmp, cssOut });
    expect(names.length).toBeGreaterThanOrEqual(3);
    const files = readdirSync(path.join(tmp, 'fonts'));
    expect(files.filter((f) => f.endsWith('.woff2')).length).toBe(names.length);
    for (const n of names) {
      const head = readFileSync(path.join(tmp, 'fonts', n)).subarray(0, 4).toString('latin1');
      expect(head).toBe('wOF2');
    }
    const css = readFileSync(cssOut, 'utf8');
    expect(css).not.toContain('data:');
    expect(css).toContain('url(/fonts/');
    expect(css).toContain('Atkinson Hyperlegible Next');
    expect(css).toContain('Maple Mono');
  });
});

// The mirror has no repo-root scripts/roadmap_assets/, so cli/ keeps its own copy. In a source checkout the
// two must stay byte-identical. In the mirror this test skips.
const ROOT_ASSETS = path.resolve(DEFAULT_ASSETS, '..', '..', '..', 'scripts', 'roadmap_assets');
describe.skipIf(!existsSync(path.join(ROOT_ASSETS, 'fonts.css')))('ui/fonts-src copy', () => {
  it.each(['fonts.css', 'OFL-Atkinson.txt', 'OFL-MapleMono.txt'])('%s is byte-identical to scripts/roadmap_assets', (f) => {
    const copy = readFileSync(path.join(DEFAULT_ASSETS, f));
    const source = readFileSync(path.join(ROOT_ASSETS, f));
    expect(copy.equals(source), `${f} drifted: copy scripts/roadmap_assets/${f} to cli/ui/fonts-src/`).toBe(true);
  });
});

describe('fonts source lives inside cli/', () => {
  it('DEFAULT_ASSETS is under cli/ui', () => {
    const cliRoot = path.resolve(DEFAULT_ASSETS, '..', '..');
    expect(path.relative(cliRoot, DEFAULT_ASSETS)).toBe(path.join('ui', 'fonts-src'));
    expect(existsSync(path.join(DEFAULT_ASSETS, 'fonts.css'))).toBe(true);
  });
});
