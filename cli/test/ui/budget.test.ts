import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { gzipSync } from 'node:zlib';
import { describe, expect, it } from 'vitest';

// R30: initial JS <= 180 KB gzip, CSS <= 30 KB gzip, dist/ui without fonts <= 1 MB.
const BUDGET = { jsGzip: 180 * 1024, cssGzip: 30 * 1024, totalNoFonts: 1024 * 1024 };

const dist = fileURLToPath(new URL('../../dist/ui', import.meta.url));
const built = existsSync(path.join(dist, 'index.html'));

function walk(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => (e.isDirectory() ? walk(path.join(dir, e.name)) : [path.join(dir, e.name)]));
}
const gz = (file: string): number => gzipSync(readFileSync(file)).length;

/** Files the page loads at start: script and stylesheet tags of index.html (plus modulepreload). */
function initial(html: string, ext: string): string[] {
  const out: string[] = [];
  for (const m of html.matchAll(/(?:src|href)="(\/assets\/[^"]+)"/g)) {
    if (m[1]!.endsWith(ext)) out.push(path.join(dist, m[1]!));
  }
  return out;
}

// The dist/ui folder exists after `npm run build:ui` (CI runs it before the tests). Without a build, skip.
describe.skipIf(!built)('bundle budget (R30)', () => {
  const html = built ? readFileSync(path.join(dist, 'index.html'), 'utf8') : '';

  it('initial JS is within the gzip budget', () => {
    const files = initial(html, '.js');
    expect(files.length).toBeGreaterThan(0);
    const total = files.reduce((n, f) => n + gz(f), 0);
    expect(total).toBeLessThanOrEqual(BUDGET.jsGzip);
  });

  it('CSS is within the gzip budget', () => {
    const files = initial(html, '.css');
    expect(files.length).toBeGreaterThan(0);
    const total = files.reduce((n, f) => n + gz(f), 0);
    expect(total).toBeLessThanOrEqual(BUDGET.cssGzip);
  });

  it('dist/ui without fonts is within 1 MB', () => {
    const fonts = path.join(dist, 'fonts') + path.sep;
    const total = walk(dist)
      .filter((f) => !f.startsWith(fonts))
      .reduce((n, f) => n + statSync(f).size, 0);
    expect(total).toBeLessThanOrEqual(BUDGET.totalNoFonts);
  });
});

describe('bundle budget limits', () => {
  it('match R30', () => {
    expect(BUDGET).toEqual({ jsGzip: 184320, cssGzip: 30720, totalNoFonts: 1048576 });
  });
});
