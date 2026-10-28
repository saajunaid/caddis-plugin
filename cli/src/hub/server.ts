import http from 'node:http';
import { existsSync } from 'node:fs';
import { readFile, stat } from 'node:fs/promises';
import type { AddressInfo } from 'node:net';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';
import { gzip } from 'node:zlib';
import type { Actions } from './actions.js';
import { MAX_ACTION_BODY_BYTES } from './actions.js';
import { AuthStore, SESSION_MAX_MS, hostAllowed, originAllowed, parseCookies, safeEqual } from './auth.js';
import { findPhaseSection, stripPhaseText } from './phaseText.js';

export const SESSION_COOKIE = 'caddis_hub_session';
export const KEY_HEADER = 'x-caddis-hub-key';
export const CSRF_HEADER = 'x-csrf-token';
/** The per-tab token header (final review I2). Needed with the cookie on /api/session and /api/state. */
export const TAB_HEADER = 'x-caddis-hub-tab';
/** Largest POST body the server reads. H1 needs no body at all. */
export const MAX_BODY_BYTES = 16 * 1024;
/** The server key must be at least this long (R19: 32 random bytes). */
export const MIN_KEY_BYTES = 32;

/** R19, verbatim. */
export const CSP =
  "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; " +
  "frame-ancestors 'none'; base-uri 'none'; form-action 'self'";

const NOT_BUILT_HTML =
  '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>caddis hub</title></head>' +
  '<body>UI not built: run npm run build</body></html>';

const MIME: Record<string, string> = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.webp': 'image/webp',
  '.ico': 'image/x-icon',
  '.woff2': 'font/woff2',
  '.txt': 'text/plain; charset=utf-8',
  '.map': 'application/json; charset=utf-8',
};

/**
 * The built UI folder. The bundled CLI (`dist/cli.js`) finds it beside itself (`dist/ui`).
 * Running from source (`src/hub/server.ts`), it is `dist/ui` of the package.
 */
export function defaultUiDir(): string {
  const here = path.dirname(fileURLToPath(import.meta.url));
  const beside = path.join(here, 'ui');
  return existsSync(beside) ? beside : path.resolve(here, '..', '..', 'dist', 'ui');
}

/**
 * Resolve a URL path under `root`. Returns null when the path escapes `root` or holds a bad byte (R26).
 */
export function resolveStatic(root: string, urlPath: string): string | null {
  let decoded: string;
  try {
    decoded = decodeURIComponent(urlPath);
  } catch {
    return null;
  }
  if (decoded.includes(String.fromCharCode(0)) || decoded.includes(String.fromCharCode(92))) return null;
  // A decoded `..` (from `%2e%2e` or `..%2f`) is refused, so `/assets/..%2findex.html` cannot reach index.html.
  if (decoded.split('/').includes('..')) return null;
  const base = path.resolve(root);
  const file = path.resolve(base, '.' + decoded);
  return file.startsWith(base + path.sep) ? file : null;
}

export interface ServerOptions {
  /** The server binds loopback only. Any other value is refused. */
  host?: '127.0.0.1';
  /** 0 lets the OS pick a port (tests). */
  port: number;
  /** The server key (R19). It never goes into a URL, a log or a response. */
  key: string;
  getState: () => unknown | Promise<unknown>;
  versions: Record<string, string>;
  /** Clock in ms, for tests. */
  now?: () => number;
  /**
   * A random id for this server run, also in `hub.lock`. `GET /api/hub/whoami` returns it with no auth, so the
   * CLI can check that the port really is this hub before it sends the key. Not set: the route answers 404.
   */
  instance?: string;
  /** The built UI folder (R26). Default: `dist/ui` of this package. Tests pass a fixture folder. */
  uiDir?: string;
  /** Called once after `POST /api/hub/stop` has sent its reply (`caddis hub stop`). */
  onStop?: () => void;
  /** The owner actions (R32). Not set: `POST /api/actions` answers 404. */
  actions?: Actions;
  /** Where logins are saved (hashed). Not set: memory only (tests). */
  sessionsFile?: string;
}

export interface HubServer {
  port: number;
  address: string;
  close: () => Promise<void>;
}

const gzipAsync = promisify(gzip);

class BodyTooLarge extends Error {}

function send(res: http.ServerResponse, status: number, body: unknown, extra: http.OutgoingHttpHeaders = {}): void {
  const text = JSON.stringify(body);
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(text),
    ...extra,
  });
  res.end(text);
}

export function acceptsGzip(header: string | string[] | undefined): boolean {
  if (!header) return false;
  const raw = Array.isArray(header) ? header.join(',') : header;
  for (const token of raw.split(',')) {
    const parts = token.split(';').map((p) => p.trim());
    const name = (parts[0] ?? '').toLowerCase();
    if (name !== 'gzip') continue;
    const qPart = parts.slice(1).find((p) => p.startsWith('q='));
    const q = qPart !== undefined ? Number(qPart.slice(2)) : 1;
    if (q > 0) return true;
  }
  return false;
}

async function sendState(req: http.IncomingMessage, res: http.ServerResponse, state: unknown): Promise<void> {
  const text = JSON.stringify(state);
  if (acceptsGzip(req.headers['accept-encoding'])) {
    const zipped = await gzipAsync(text);
    res.writeHead(200, {
      'Content-Type': 'application/json; charset=utf-8',
      'Content-Encoding': 'gzip',
      'Content-Length': zipped.length,
      Vary: 'Accept-Encoding',
    });
    res.end(zipped);
    return;
  }
  return send(res, 200, state, { Vary: 'Accept-Encoding' });
}

const fail = (res: http.ServerResponse, status: number, error: string): void => send(res, status, { schema: 1, error });

/** Read the body up to `limit` bytes (default MAX_BODY_BYTES). Throws BodyTooLarge past the limit. */
function readBody(req: http.IncomingMessage, limit = MAX_BODY_BYTES): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    const declared = Number(req.headers['content-length'] ?? 0);
    if (declared > limit) {
      reject(new BodyTooLarge());
      return;
    }
    const chunks: Buffer[] = [];
    let size = 0;
    let done = false;
    req.on('data', (c: Buffer) => {
      if (done) return;
      size += c.length;
      if (size > limit) {
        done = true;
        reject(new BodyTooLarge());
        return;
      }
      chunks.push(c);
    });
    req.on('end', () => {
      if (!done) resolve(Buffer.concat(chunks));
    });
    req.on('error', (e) => {
      if (!done) reject(e);
    });
  });
}

function tooLarge(req: http.IncomingMessage, res: http.ServerResponse): void {
  // Close the connection after the reply, so the rest of the body is not read.
  res.on('finish', () => req.socket.destroy());
  fail(res, 413, 'body_too_large');
}

/**
 * Serve one file of the built UI (R26). `/` is `index.html` (no-store). `assets/` and `fonts/` files are
 * hashed or fixed, so they are immutable. No session is needed: these files hold no data.
 */
async function serveStatic(res: http.ServerResponse, uiDir: string, urlPath: string): Promise<void> {
  const rel = urlPath === '/' ? '/index.html' : urlPath;
  const file = resolveStatic(uiDir, rel);
  if (!file) return fail(res, 404, 'not_found');
  let body: Buffer;
  try {
    if (!(await stat(file)).isFile()) return fail(res, 404, 'not_found');
    body = await readFile(file);
  } catch {
    if (urlPath === '/') {
      res.writeHead(503, {
        'Content-Type': 'text/html; charset=utf-8',
        'Content-Length': Buffer.byteLength(NOT_BUILT_HTML),
        'Cache-Control': 'no-store',
      });
      res.end(NOT_BUILT_HTML);
      return;
    }
    return fail(res, 404, 'not_found');
  }
  res.writeHead(200, {
    'Content-Type': MIME[path.extname(file).toLowerCase()] ?? 'application/octet-stream',
    'Content-Length': body.length,
    'Cache-Control': urlPath === '/' ? 'no-store' : 'public, max-age=31536000, immutable',
  });
  res.end(body);
}

function keyOk(req: http.IncomingMessage, key: string): boolean {
  const v = req.headers[KEY_HEADER];
  return typeof v === 'string' && safeEqual(v, key);
}

/**
 * Start the hub HTTP server on 127.0.0.1 (R18, R19, R20).
 * Every request passes the Host check first. Then:
 * - `GET /api/health`, `POST /api/hub/code`, `POST /api/hub/stop`: the key header only (no cookie).
 * - every other non-GET: Origin, then session, then CSRF token.
 * - `GET /api/session`, `GET /api/state`: a session cookie AND its tab token in `X-Caddis-Hub-Tab`.
 * - `GET /api/plan-phase`: one plan phase section, with the same session cookie AND tab token check.
 */
export async function startServer(opts: ServerOptions): Promise<HubServer> {
  const host = opts.host ?? '127.0.0.1';
  if (host !== '127.0.0.1') throw new Error('the hub server binds 127.0.0.1 only');
  if (typeof opts.key !== 'string' || Buffer.byteLength(opts.key, 'utf8') < MIN_KEY_BYTES) {
    throw new Error(`the hub server key must be at least ${MIN_KEY_BYTES} bytes`);
  }
  const auth = new AuthStore(opts.now ?? Date.now, opts.sessionsFile);
  const { key, versions } = opts;
  const uiDir = opts.uiDir ?? defaultUiDir();
  let port = opts.port;

  const sessionOf = (req: http.IncomingMessage) => auth.getSession(parseCookies(req.headers.cookie)[SESSION_COOKIE]);
  const tabSessionOf = (req: http.IncomingMessage) => {
    const tab = req.headers[TAB_HEADER];
    return auth.getTabSession(parseCookies(req.headers.cookie)[SESSION_COOKIE], typeof tab === 'string' ? tab : '');
  };

  async function handle(req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
    res.setHeader('Content-Security-Policy', CSP);
    res.setHeader('X-Content-Type-Options', 'nosniff');
    res.setHeader('Referrer-Policy', 'no-referrer');

    let url: URL;
    try {
      url = new URL(req.url ?? '/', 'http://127.0.0.1');
    } catch {
      fail(res, 400, 'bad_url');
      return;
    }
    const path = url.pathname;
    const method = req.method ?? 'GET';
    if (path.startsWith('/api/') || path === '/login') res.setHeader('Cache-Control', 'no-store');

    // Host check on every request, before anything else (DNS rebinding).
    if (!hostAllowed(req.headers.host, port)) {
      // A refused /login still uses up its code: the code is consumed even when the request fails.
      if (path === '/login') auth.discardCode(url.searchParams.get('code') ?? '');
      fail(res, 403, 'bad_host');
      return;
    }

    // Identity probe: no key, no cookie. It reveals the instance id only (not a secret).
    if (path === '/api/hub/whoami' && method === 'GET') {
      if (!opts.instance) return fail(res, 404, 'not_found');
      return send(res, 200, { instance: opts.instance });
    }

    // Key-header routes. They never accept a session cookie.
    if (path === '/api/health' && method === 'GET') {
      if (!keyOk(req, key)) return fail(res, 401, 'unauthorized');
      return send(res, 200, { schema: 1, ok: true, versions });
    }
    if (path === '/api/hub/code' && method === 'POST') {
      // Exemption: this is a local CLI call (`caddis hub open`), not a browser call.
      // It skips the Origin and CSRF checks, but NOT the Host check above and NOT the key check here.
      // A browser page cannot read the key, so it cannot pass this check.
      if (!keyOk(req, key)) return fail(res, 401, 'unauthorized');
      try {
        await readBody(req);
      } catch (e) {
        if (e instanceof BodyTooLarge) return tooLarge(req, res);
        throw e;
      }
      const code = auth.mintCode();
      return send(res, 200, { schema: 1, code, expires_at: auth.codeExpiresAt() });
    }
    if (path === '/api/hub/stop' && method === 'POST') {
      // Same exemption as /api/hub/code: a local CLI call (`caddis hub stop`), key header only.
      // The Host check above still applies.
      if (!keyOk(req, key)) return fail(res, 401, 'unauthorized');
      try {
        await readBody(req);
      } catch (e) {
        if (e instanceof BodyTooLarge) return tooLarge(req, res);
        throw e;
      }
      // Stop only after the reply is out, so the CLI sees the 200.
      res.on('finish', () => opts.onStop?.());
      return send(res, 200, { schema: 1, ok: true });
    }

    if (method !== 'GET') {
      // Every non-GET: exact Origin, then a session, then the session's CSRF token.
      const origin = req.headers.origin;
      if (!originAllowed(typeof origin === 'string' ? origin : undefined, port)) return fail(res, 403, 'bad_origin');
      const session = sessionOf(req);
      if (!session) return fail(res, 401, 'unauthorized');
      const token = req.headers[CSRF_HEADER];
      if (typeof token !== 'string' || !safeEqual(token, session.csrf)) return fail(res, 403, 'bad_csrf');
      if (path === '/api/actions' && method === 'POST' && opts.actions) {
        // R32: an action also needs the per-tab token, so a cookie replayed from another localhost port cannot act.
        if (!tabSessionOf(req)) return fail(res, 401, 'unauthorized');
        const type = String(req.headers['content-type'] ?? '').split(';')[0]?.trim().toLowerCase();
        if (type !== 'application/json') return fail(res, 415, 'json_only');
        let raw: Buffer;
        try {
          raw = await readBody(req, MAX_ACTION_BODY_BYTES);
        } catch (e) {
          if (e instanceof BodyTooLarge) return tooLarge(req, res);
          throw e;
        }
        let body: unknown;
        try {
          body = JSON.parse(raw.toString('utf8'));
        } catch {
          return fail(res, 400, 'bad_json');
        }
        const reply = await opts.actions.submit(body);
        return send(res, reply.status, reply.body);
      }
      try {
        await readBody(req);
      } catch (e) {
        if (e instanceof BodyTooLarge) return tooLarge(req, res);
        throw e;
      }
      // R20 (H1): logout. R32 (H3): /api/actions, above.
      if (path === '/api/logout' && method === 'POST') {
        auth.deleteSession(parseCookies(req.headers.cookie)[SESSION_COOKIE] ?? '');
        return send(res, 200, { schema: 1, ok: true }, {
          'Set-Cookie': `${SESSION_COOKIE}=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0`,
        });
      }
      return fail(res, 404, 'not_found');
    }

    if (path === '/' || path.startsWith('/assets/') || path.startsWith('/fonts/')) {
      await serveStatic(res, uiDir, path);
      return;
    }
    if (path === '/login') {
      // The store consumes the code before it checks the age, so a failed try still uses it up.
      const id = auth.redeemCode(url.searchParams.get('code') ?? '');
      const session = id ? auth.getSession(id) : null;
      if (!id || !session) return fail(res, 401, 'bad_code');
      // Browsers share cookies across ports on localhost, so another local service can receive this cookie and
      // replay it (final review I2). The tab token goes in the fragment: a browser never sends a fragment to any
      // server, and only a page on this origin can read it. The page keeps it in sessionStorage and sends it in
      // X-Caddis-Hub-Tab. A cookie alone opens nothing. The server never logs the token.
      res.writeHead(303, {
        Location: `/#tab=${session.tab}`,
        'Set-Cookie': `${SESSION_COOKIE}=${id}; HttpOnly; SameSite=Strict; Path=/; Max-Age=${Math.floor(SESSION_MAX_MS / 1000)}`,
        'Content-Length': 0,
      });
      res.end();
      return;
    }
    if (path === '/api/session') {
      const session = tabSessionOf(req);
      if (!session) return fail(res, 401, 'unauthorized');
      return send(res, 200, { schema: 1, csrf_token: session.csrf, versions });
    }
    if (path === '/api/state') {
      if (!tabSessionOf(req)) return fail(res, 401, 'unauthorized');
      let state: unknown;
      try {
        state = await opts.getState();
      } catch {
        return fail(res, 500, 'state_failed');
      }
      return sendState(req, res, stripPhaseText(state));
    }
    if (path === '/api/plan-phase') {
      if (!tabSessionOf(req)) return fail(res, 401, 'unauthorized');
      const repo = url.searchParams.get('repo') ?? '';
      const plan = url.searchParams.get('plan') ?? '';
      const phaseKey = url.searchParams.get('key') ?? '';
      if (!repo || !plan || !phaseKey) return fail(res, 400, 'bad_request');
      let state: unknown;
      try {
        state = await opts.getState();
      } catch {
        return fail(res, 500, 'state_failed');
      }
      const sec = findPhaseSection(state, repo, plan, phaseKey);
      return sec ? send(res, 200, { schema: 1, ...sec }) : fail(res, 404, 'not_found');
    }
    return fail(res, 404, 'not_found');
  }

  const server = http.createServer((req, res) => {
    handle(req, res).catch(() => {
      if (!res.headersSent) fail(res, 500, 'internal');
      else res.destroy();
    });
  });
  server.headersTimeout = 10_000;
  server.requestTimeout = 15_000;

  await new Promise<void>((resolve, reject) => {
    const onError = (e: Error): void => reject(e);
    server.once('error', onError);
    server.listen(opts.port, host, () => {
      server.off('error', onError);
      resolve();
    });
  });
  const addr = server.address() as AddressInfo;
  port = addr.port;

  return {
    port,
    address: addr.address,
    close: () =>
      new Promise<void>((resolve) => {
        server.close(() => resolve());
        server.closeAllConnections();
      }),
  };
}
