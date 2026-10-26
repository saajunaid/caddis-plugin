import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { DEFAULT_ASSETS, LICENCES, buildFonts } from '../../scripts/build-ui-fonts.mjs';

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

  it('ships the three licences in licenses/, not in fonts/ (dist/ui/licenses, R61)', () => {
    buildFonts({ publicDir: tmp, cssOut: path.join(tmp, 'f.css') });
    for (const f of LICENCES) {
      expect(readFileSync(path.join(tmp, 'licenses', f)).equals(readFileSync(path.join(DEFAULT_ASSETS, f))), f).toBe(true);
      expect(existsSync(path.join(tmp, 'fonts', f)), f).toBe(false);
    }
  });

  it('fails when a licence is missing from the source', () => {
    const src = path.join(tmp, 'src');
    mkdirSync(src);
    copyFileSync(path.join(DEFAULT_ASSETS, 'fonts.css'), path.join(src, 'fonts.css'));
    for (const f of LICENCES.slice(0, 2)) copyFileSync(path.join(DEFAULT_ASSETS, f), path.join(src, f));
    expect(() => buildFonts({ assetsDir: src, publicDir: path.join(tmp, 'out'), cssOut: path.join(tmp, 'f.css') })).toThrow(LICENCES[2]);
  });
});

describe('fonts source lives inside cli/', () => {
  it('DEFAULT_ASSETS is under cli/ui', () => {
    const cliRoot = path.resolve(DEFAULT_ASSETS, '..', '..');
    expect(path.relative(cliRoot, DEFAULT_ASSETS)).toBe(path.join('ui', 'fonts-src'));
    expect(existsSync(path.join(DEFAULT_ASSETS, 'fonts.css'))).toBe(true);
  });
});
