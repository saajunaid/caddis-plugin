import http from 'node:http';
import { randomBytes } from 'node:crypto';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { CSP, resolveStatic, startServer } from '../../src/hub/server.js';

interface Res {
  status: number;
  headers: http.IncomingHttpHeaders;
  body: string;
}

let tmp: string;
let srv: { port: number; close: () => Promise<void> } | undefined;

function get(port: number, p: string): Promise<Res> {
  return new Promise((resolve, reject) => {
    const r = http.request(
      { host: '127.0.0.1', port, method: 'GET', path: p, headers: { host: `127.0.0.1:${port}` }, agent: false },
      (res) => {
        const chunks: Buffer[] = [];
        res.on('data', (c: Buffer) => chunks.push(c));
        res.on('end', () =>
          resolve({ status: res.statusCode ?? 0, headers: res.headers, body: Buffer.concat(chunks).toString('utf8') }),
        );
      },
    );
    r.on('error', reject);
    r.end();
  });
}

async function start(uiDir: string): Promise<number> {
  srv = await startServer({
    port: 0,
    key: randomBytes(32).toString('hex'),
    getState: () => ({ schema: 1 }),
    versions: { cli: '0.0.0-test' },
    uiDir,
  });
  return srv.port;
}

beforeEach(() => {
  tmp = mkdtempSync(path.join(tmpdir(), 'caddis-hub-static-'));
});
afterEach(async () => {
  await srv?.close();
  srv = undefined;
  rmSync(tmp, { recursive: true, force: true });
});

function fixtureUi(): string {
  const ui = path.join(tmp, 'ui');
  mkdirSync(path.join(ui, 'assets'), { recursive: true });
  mkdirSync(path.join(ui, 'fonts'), { recursive: true });
  writeFileSync(path.join(ui, 'index.html'), '<!doctype html><title>t</title><script type="module" src="/assets/x.js"></script>');
  writeFileSync(path.join(ui, 'assets', 'x.js'), 'export {};');
  writeFileSync(path.join(ui, 'assets', 'x.css'), 'body{}');
  writeFileSync(path.join(ui, 'assets', 'mark.webp'), 'RIFF');
  writeFileSync(path.join(ui, 'fonts', 'a.woff2'), 'wOF2');
  writeFileSync(path.join(tmp, 'key'), 'SECRET');
  return ui;
}

describe('static UI (R26)', () => {
  it('serves index.html at / with the CSP, no-store and no session', async () => {
    const port = await start(fixtureUi());
    const r = await get(port, '/');
    expect(r.status).toBe(200);
    expect(r.headers['content-type']).toBe('text/html; charset=utf-8');
    expect(r.headers['content-security-policy']).toBe(CSP);
    expect(r.headers['cache-control']).toBe('no-store');
    expect(r.body).toContain('/assets/x.js');
  });

  it('serves assets and fonts as immutable with the right type', async () => {
    const port = await start(fixtureUi());
    const js = await get(port, '/assets/x.js');
    expect(js.status).toBe(200);
    expect(js.headers['content-type']).toBe('text/javascript; charset=utf-8');
    expect(js.headers['cache-control']).toBe('public, max-age=31536000, immutable');
    expect((await get(port, '/assets/x.css')).headers['content-type']).toBe('text/css; charset=utf-8');
    expect((await get(port, '/assets/mark.webp')).headers['content-type']).toBe('image/webp'); // the animated logo
    const font = await get(port, '/fonts/a.woff2');
    expect(font.headers['content-type']).toBe('font/woff2');
    expect(font.headers['cache-control']).toContain('immutable');
  });

  it('refuses path traversal in every encoding', async () => {
    const port = await start(fixtureUi());
    for (const p of [
      '/assets/../key',
      '/assets/%2e%2e/key',
      '/assets/%2E%2E/key',
      '/assets/..%2fkey',
      '/assets/..%5ckey',
      '/assets/%00',
      '/assets/..%2F..%2Fkey',
    ]) {
      const r = await get(port, p);
      expect(r.status, p).toBe(404);
      expect(r.body, p).not.toContain('SECRET');
    }
    expect((await get(port, '/assets/missing.js')).status).toBe(404);
    expect((await get(port, '/assets/')).status).toBe(404);
  });

  it('gives a one-line page when the UI is not built', async () => {
    const port = await start(path.join(tmp, 'nothing'));
    const r = await get(port, '/');
    expect(r.status).toBe(503);
    expect(r.body).toContain('UI not built: run npm run build');
    expect(r.headers['content-security-policy']).toBe(CSP);
  });

  it('keeps the API behind the session', async () => {
    const port = await start(fixtureUi());
    expect((await get(port, '/api/state')).status).toBe(401);
  });

  it('resolveStatic stays inside the root', () => {
    const root = path.join(tmp, 'ui');
    expect(resolveStatic(root, '/assets/x.js')).toBe(path.join(root, 'assets', 'x.js'));
    expect(resolveStatic(root, '/../key')).toBeNull();
    expect(resolveStatic(root, '/%E0%A4%A')).toBeNull();
    // Review minor 1: a decoded `..` that stays inside the root is refused too.
    expect(resolveStatic(root, '/assets/..%2findex.html')).toBeNull();
    expect(resolveStatic(root, '/assets/%2e%2e/index.html')).toBeNull();
  });
});

describe('built dist/ui', () => {
  const index = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'dist', 'ui', 'index.html');
  it.skipIf(!existsSync(index))('has no inline script and no style tag (the CSP forbids both)', () => {
    const html = readFileSync(index, 'utf8');
    const scripts = [...html.matchAll(/<script\b[^>]*>/gi)].map((m) => m[0]);
    expect(scripts.length).toBeGreaterThan(0);
    for (const s of scripts) expect(s).toMatch(/\bsrc=/);
    expect(html).not.toMatch(/<style\b/i);
    expect(html).not.toMatch(/\son[a-z]+=/i);
  });
});
