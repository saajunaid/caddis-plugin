import http from 'node:http';
import { randomBytes } from 'node:crypto';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { startServer, SESSION_COOKIE, MAX_BODY_BYTES } from '../../src/hub/server.js';

const CSP =
  "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; " +
  "frame-ancestors 'none'; base-uri 'none'; form-action 'self'";

interface Res {
  status: number;
  headers: http.IncomingHttpHeaders;
  body: string;
}

let srv: { port: number; address: string; close: () => Promise<void> };
let key: string;
let t: number;
let stops: number;
const INSTANCE = '0123456789abcdef0123456789abcdef';
const versions = { cli: '0.0.0-test', caddis: '0.0.0-test' };
const state = { schema: 1, repos: [{ name: 'acme/shop' }] };

function req(
  method: string,
  path: string,
  headers: Record<string, string> = {},
  body?: string,
): Promise<Res> {
  return new Promise((resolve, reject) => {
    const r = http.request(
      {
        host: '127.0.0.1',
        port: srv.port,
        method,
        path,
        headers: { host: `127.0.0.1:${srv.port}`, ...headers },
        agent: false,
      },
      (res) => {
        const chunks: Buffer[] = [];
        res.on('data', (c: Buffer) => chunks.push(c));
        res.on('end', () =>
          resolve({ status: res.statusCode ?? 0, headers: res.headers, body: Buffer.concat(chunks).toString('utf8') }),
        );
      },
    );
    r.on('error', reject);
    if (body !== undefined) r.write(body);
    r.end();
  });
}

const origin = (): string => `http://127.0.0.1:${srv.port}`;
const keyHdr = (): Record<string, string> => ({ 'x-caddis-hub-key': key });

async function mintCode(): Promise<string> {
  const r = await req('POST', '/api/hub/code', keyHdr());
  expect(r.status).toBe(200);
  return JSON.parse(r.body).code as string;
}

function cookieFrom(r: Res): string {
  const sc = r.headers['set-cookie'];
  expect(sc).toBeDefined();
  const first = (sc as string[])[0]!;
  return first.split(';')[0]!;
}

/** The tab token from a /login redirect: `Location: /#tab=<token>`. */
function tabFrom(r: Res): string {
  const m = /^\/#tab=([A-Za-z0-9_-]{43})$/.exec(String(r.headers.location));
  expect(m).not.toBeNull();
  return m![1]!;
}

interface Login {
  cookie: string;
  tab: string;
  csrf: string;
  /** The cookie and the tab header: what the page sends on /api/session and /api/state. */
  hdr: Record<string, string>;
}
async function login(): Promise<Login> {
  const code = await mintCode();
  const r = await req('GET', `/login?code=${encodeURIComponent(code)}`);
  expect(r.status).toBe(303);
  const cookie = cookieFrom(r);
  const tab = tabFrom(r);
  const hdr = { cookie, 'x-caddis-hub-tab': tab };
  const s = await req('GET', '/api/session', hdr);
  expect(s.status).toBe(200);
  return { cookie, tab, csrf: JSON.parse(s.body).csrf_token as string, hdr };
}

beforeEach(async () => {
  key = randomBytes(32).toString('hex');
  t = 5_000_000;
  stops = 0;
  srv = await startServer({
    host: '127.0.0.1',
    port: 0,
    key,
    getState: () => state,
    versions,
    now: () => t,
    instance: INSTANCE,
    onStop: () => {
      stops++;
    },
  });
});
afterEach(async () => {
  await srv.close();
});

describe('listen address', () => {
  it('listens on 127.0.0.1 only, on an OS-picked port', async () => {
    expect(srv.port).toBeGreaterThan(0);
    expect(srv.address).toBe('127.0.0.1');
    const r = await req('GET', '/api/health', keyHdr());
    expect(r.status).toBe(200);
  });

  it('refuses any host other than 127.0.0.1', async () => {
    await expect(
      // @ts-expect-error: the type allows only 127.0.0.1
      startServer({ host: '0.0.0.0', port: 0, key, getState: () => state, versions }),
    ).rejects.toThrow(/127\.0\.0\.1/);
  });
});

describe('server key', () => {
  for (const bad of ['', 'short', 'x'.repeat(31)]) {
    it(`refuses to start with a key of ${bad.length} bytes`, async () => {
      await expect(startServer({ host: '127.0.0.1', port: 0, key: bad, getState: () => state, versions })).rejects.toThrow(
        /32 bytes/,
      );
    });
  }

  it('an empty key header gets 401', async () => {
    expect((await req('GET', '/api/health', { 'x-caddis-hub-key': '' })).status).toBe(401);
  });
});

describe('session TTL over HTTP', () => {
  it('an idle session past 12 h gets 401', async () => {
    const { hdr } = await login();
    t += 12 * 60 * 60 * 1000;
    expect((await req('GET', '/api/state', hdr)).status).toBe(401);
  });

  it('a session past 24 h gets 401 even when used each hour', async () => {
    const { hdr } = await login();
    for (let h = 0; h < 23; h++) {
      t += 60 * 60 * 1000;
      expect((await req('GET', '/api/state', hdr)).status).toBe(200);
    }
    t += 60 * 60 * 1000;
    expect((await req('GET', '/api/state', hdr)).status).toBe(401);
  });
});

describe('Host check (every request)', () => {
  for (const [method, path] of [
    ['GET', '/'],
    ['GET', '/api/health'],
    ['POST', '/api/hub/code'],
    ['GET', '/api/state'],
    ['GET', '/login?code=x'],
    ['POST', '/api/logout'],
    ['POST', '/api/hub/stop'],
    ['GET', '/api/hub/whoami'],
  ] as const) {
    it(`${method} ${path} with Host evil.test:<port> gets 403`, async () => {
      const r = await req(method, path, { ...keyHdr(), host: `evil.test:${srv.port}`, origin: origin() });
      expect(r.status).toBe(403);
    });
  }

  it('accepts localhost:<port>', async () => {
    const r = await req('GET', '/api/health', { ...keyHdr(), host: `localhost:${srv.port}` });
    expect(r.status).toBe(200);
  });

  it('refuses localhost. with a trailing dot', async () => {
    const r = await req('GET', '/api/health', { ...keyHdr(), host: `localhost.:${srv.port}` });
    expect(r.status).toBe(403);
  });

  it('refuses the right name with the wrong port', async () => {
    const r = await req('GET', '/api/health', { ...keyHdr(), host: `127.0.0.1:${srv.port + 1}` });
    expect(r.status).toBe(403);
  });
});

describe('key-header routes', () => {
  it('GET /api/health needs the key header', async () => {
    expect((await req('GET', '/api/health')).status).toBe(401);
    expect((await req('GET', '/api/health', { 'x-caddis-hub-key': 'wrong' })).status).toBe(401);
    const ok = await req('GET', '/api/health', keyHdr());
    expect(ok.status).toBe(200);
    expect(JSON.parse(ok.body)).toMatchObject({ schema: 1, ok: true });
  });

  it('GET /api/health does not accept a session cookie instead of the key', async () => {
    const { cookie } = await login();
    expect((await req('GET', '/api/health', { cookie })).status).toBe(401);
  });

  it('POST /api/hub/code: no key gets 401, wrong key gets 401', async () => {
    expect((await req('POST', '/api/hub/code')).status).toBe(401);
    expect((await req('POST', '/api/hub/code', { 'x-caddis-hub-key': 'wrong' })).status).toBe(401);
    expect((await req('POST', '/api/hub/code', { 'x-caddis-hub-key': key + 'x' })).status).toBe(401);
  });

  it('POST /api/hub/code is exempt from the Origin/CSRF rule (a local CLI call)', async () => {
    const r = await req('POST', '/api/hub/code', keyHdr());
    expect(r.status).toBe(200);
    const j = JSON.parse(r.body);
    expect(j.schema).toBe(1);
    expect(typeof j.code).toBe('string');
    expect(j.expires_at).toMatch(/Z$/);
  });

  it('POST /api/hub/code does not accept a session cookie instead of the key', async () => {
    const { cookie, csrf } = await login();
    const r = await req('POST', '/api/hub/code', { cookie, 'x-csrf-token': csrf, origin: origin() });
    expect(r.status).toBe(401);
  });
});

describe('GET /api/hub/whoami (no auth)', () => {
  it('answers {instance} with no key and no cookie, and nothing else', async () => {
    const r = await req('GET', '/api/hub/whoami');
    expect(r.status).toBe(200);
    expect(JSON.parse(r.body)).toEqual({ instance: INSTANCE });
    expect(r.headers['cache-control']).toBe('no-store');
    expect(r.headers['set-cookie']).toBeUndefined();
  });

  it('a server without an instance answers 404', async () => {
    const other = await startServer({ host: '127.0.0.1', port: 0, key, getState: () => state, versions });
    try {
      const r = await new Promise<number>((resolve, reject) => {
        const q = http.request(
          { host: '127.0.0.1', port: other.port, path: '/api/hub/whoami', headers: { host: `127.0.0.1:${other.port}` }, agent: false },
          (res) => {
            res.resume();
            resolve(res.statusCode ?? 0);
          },
        );
        q.on('error', reject);
        q.end();
      });
      expect(r).toBe(404);
    } finally {
      await other.close();
    }
  });
});

describe('POST /api/hub/stop (key header only)', () => {
  it('no key or a wrong key gets 401 and does not stop', async () => {
    expect((await req('POST', '/api/hub/stop')).status).toBe(401);
    expect((await req('POST', '/api/hub/stop', { 'x-caddis-hub-key': 'wrong' })).status).toBe(401);
    expect(stops).toBe(0);
  });

  it('a session cookie with Origin and CSRF does not replace the key', async () => {
    const { cookie, csrf } = await login();
    const r = await req('POST', '/api/hub/stop', { cookie, 'x-csrf-token': csrf, origin: origin() });
    expect(r.status).toBe(401);
    expect(stops).toBe(0);
  });

  it('the key alone (no Origin, no CSRF) answers 200, then calls onStop once', async () => {
    const r = await req('POST', '/api/hub/stop', keyHdr());
    expect(r.status).toBe(200);
    expect(JSON.parse(r.body)).toEqual({ schema: 1, ok: true });
    expect(r.headers['cache-control']).toBe('no-store');
    await new Promise((res) => setTimeout(res, 20));
    expect(stops).toBe(1);
    expect(r.body.includes(key)).toBe(false);
  });

  it('a wrong Host gets 403 and does not stop', async () => {
    const r = await req('POST', '/api/hub/stop', { ...keyHdr(), host: `evil.test:${srv.port}` });
    expect(r.status).toBe(403);
    expect(stops).toBe(0);
  });
});

describe('login with a one-time code', () => {
  it('a code works once, then 401', async () => {
    const code = await mintCode();
    const first = await req('GET', `/login?code=${encodeURIComponent(code)}`);
    expect(first.status).toBe(303);
    expect(first.headers.location).toMatch(/^\/#tab=[A-Za-z0-9_-]{43}$/);
    const again = await req('GET', `/login?code=${encodeURIComponent(code)}`);
    expect(again.status).toBe(401);
  });

  it('a code older than 60 s gets 401', async () => {
    const code = await mintCode();
    t += 60_001;
    const r = await req('GET', `/login?code=${encodeURIComponent(code)}`);
    expect(r.status).toBe(401);
    expect(r.headers['set-cookie']).toBeUndefined();
  });

  it('a bad-Host /login still consumes the code', async () => {
    const code = await mintCode();
    const bad = await req('GET', `/login?code=${encodeURIComponent(code)}`, { host: `evil.test:${srv.port}` });
    expect(bad.status).toBe(403);
    expect(bad.headers['set-cookie']).toBeUndefined();
    expect((await req('GET', `/login?code=${encodeURIComponent(code)}`)).status).toBe(401);
  });

  it('an expired try consumes the code', async () => {
    const code = await mintCode();
    t += 60_001;
    expect((await req('GET', `/login?code=${encodeURIComponent(code)}`)).status).toBe(401);
    t -= 60_001;
    expect((await req('GET', `/login?code=${encodeURIComponent(code)}`)).status).toBe(401);
  });

  it('a missing or unknown code gets 401', async () => {
    expect((await req('GET', '/login')).status).toBe(401);
    expect((await req('GET', '/login?code=nope')).status).toBe(401);
  });

  it('the cookie has HttpOnly, SameSite=Strict and Path=/, and no Secure', async () => {
    const code = await mintCode();
    const r = await req('GET', `/login?code=${encodeURIComponent(code)}`);
    const sc = (r.headers['set-cookie'] as string[])[0]!;
    expect(sc.startsWith(`${SESSION_COOKIE}=`)).toBe(true);
    const attrs = sc.split(';').map((s) => s.trim());
    expect(attrs).toContain('HttpOnly');
    expect(attrs).toContain('SameSite=Strict');
    expect(attrs).toContain('Path=/');
    expect(attrs.map((a) => a.toLowerCase())).not.toContain('secure');
  });
});

describe('session routes', () => {
  it('/api/state without a session gets 401', async () => {
    expect((await req('GET', '/api/state')).status).toBe(401);
    expect((await req('GET', '/api/state', { cookie: `${SESSION_COOKIE}=forged` })).status).toBe(401);
  });

  it('/api/state does not accept the key header instead of a session', async () => {
    expect((await req('GET', '/api/state', keyHdr())).status).toBe(401);
  });

  it('/api/state with a session returns getState() as JSON', async () => {
    const { hdr } = await login();
    const r = await req('GET', '/api/state', hdr);
    expect(r.status).toBe(200);
    expect(r.headers['content-type']).toMatch(/^application\/json/);
    expect(JSON.parse(r.body)).toEqual(state);
  });

  it('/api/session without a session gets 401', async () => {
    expect((await req('GET', '/api/session')).status).toBe(401);
  });

  it('/api/session returns the CSRF token and versions', async () => {
    const { hdr } = await login();
    const r = await req('GET', '/api/session', hdr);
    const j = JSON.parse(r.body);
    expect(j.schema).toBe(1);
    expect(j.csrf_token).toMatch(/^[A-Za-z0-9_-]{43}$/);
    expect(j.versions).toEqual(versions);
  });
});

describe('per-tab token (final review I2)', () => {
  it('the /login redirect carries the token in the fragment, not in the cookie', async () => {
    const code = await mintCode();
    const r = await req('GET', `/login?code=${encodeURIComponent(code)}`);
    expect(r.status).toBe(303);
    const tab = tabFrom(r);
    expect(String(r.headers.location)).toBe(`/#tab=${tab}`);
    expect(String(r.headers['set-cookie'])).not.toContain(tab);
  });

  for (const p of ['/api/session', '/api/state']) {
    it(`${p}: the cookie without the tab token gets 401 (a cookie replayed from another port)`, async () => {
      const { cookie } = await login();
      const r = await req('GET', p, { cookie });
      expect(r.status).toBe(401);
      expect(r.body).not.toContain('csrf_token');
    });

    it(`${p}: a wrong tab token gets 401`, async () => {
      const { cookie, tab } = await login();
      expect((await req('GET', p, { cookie, 'x-caddis-hub-tab': 'x'.repeat(43) })).status).toBe(401);
      expect((await req('GET', p, { cookie, 'x-caddis-hub-tab': tab.slice(0, -1) })).status).toBe(401);
      expect((await req('GET', p, { cookie, 'x-caddis-hub-tab': '' })).status).toBe(401);
    });

    it(`${p}: a tab token from another session gets 401`, async () => {
      const a = await login();
      const b = await login();
      expect((await req('GET', p, { cookie: a.cookie, 'x-caddis-hub-tab': b.tab })).status).toBe(401);
      expect((await req('GET', p, { cookie: b.cookie, 'x-caddis-hub-tab': a.tab })).status).toBe(401);
      expect((await req('GET', p, a.hdr)).status).toBe(200);
    });

    it(`${p}: the tab token alone (no cookie) gets 401`, async () => {
      const { tab } = await login();
      expect((await req('GET', p, { 'x-caddis-hub-tab': tab })).status).toBe(401);
    });
  }

  it('a refused tab token does not keep an idle session alive', async () => {
    const { cookie, hdr } = await login();
    t += 11 * 60 * 60 * 1000;
    expect((await req('GET', '/api/state', { cookie })).status).toBe(401);
    t += 60 * 60 * 1000;
    expect((await req('GET', '/api/state', hdr)).status).toBe(401);
  });

  it('the tab token never appears in a response body or in a log line', async () => {
    const out: string[] = [];
    const spies = [
      vi.spyOn(process.stdout, 'write').mockImplementation((c: string | Uint8Array) => (out.push(String(c)), true)),
      vi.spyOn(process.stderr, 'write').mockImplementation((c: string | Uint8Array) => (out.push(String(c)), true)),
      ...(['log', 'info', 'warn', 'error', 'debug'] as const).map((m) =>
        vi.spyOn(console, m).mockImplementation((...a: unknown[]) => void out.push(a.map(String).join(' '))),
      ),
    ];
    try {
      const { tab, hdr, cookie } = await login();
      const seen = [
        await req('GET', '/api/session', hdr),
        await req('GET', '/api/state', hdr),
        await req('GET', '/api/state', { cookie }),
        await req('GET', '/api/state', { cookie, 'x-caddis-hub-tab': 'bad' }),
      ].map((r) => r.body + JSON.stringify(r.headers));
      expect(seen.some((b) => b.includes(tab))).toBe(false);
      expect(out.join('\n')).not.toContain(tab);
    } finally {
      for (const s of spies) s.mockRestore();
    }
  });
});

describe('Origin and CSRF on every non-GET', () => {
  it('a POST with no Origin gets 403', async () => {
    const { cookie, csrf } = await login();
    const r = await req('POST', '/api/logout', { cookie, 'x-csrf-token': csrf });
    expect(r.status).toBe(403);
  });

  it('a POST with Origin: null gets 403', async () => {
    const { cookie, csrf } = await login();
    const r = await req('POST', '/api/logout', { cookie, 'x-csrf-token': csrf, origin: 'null' });
    expect(r.status).toBe(403);
  });

  it('a POST with another origin gets 403', async () => {
    const { cookie, csrf } = await login();
    for (const o of ['http://evil.test', `https://127.0.0.1:${srv.port}`, `http://127.0.0.1:${srv.port + 1}`]) {
      const r = await req('POST', '/api/logout', { cookie, 'x-csrf-token': csrf, origin: o });
      expect(r.status, o).toBe(403);
    }
  });

  it('a POST with no CSRF token gets 403', async () => {
    const { cookie } = await login();
    const r = await req('POST', '/api/logout', { cookie, origin: origin() });
    expect(r.status).toBe(403);
  });

  it('a POST with a wrong CSRF token gets 403', async () => {
    const { cookie, csrf } = await login();
    const other = await login();
    expect(other.csrf).not.toBe(csrf);
    const r = await req('POST', '/api/logout', { cookie, origin: origin(), 'x-csrf-token': other.csrf });
    expect(r.status).toBe(403);
    expect((await req('POST', '/api/logout', { cookie, origin: origin(), 'x-csrf-token': 'x' })).status).toBe(403);
  });

  it('a POST with no session gets 401', async () => {
    const r = await req('POST', '/api/logout', { origin: origin(), 'x-csrf-token': 'x' });
    expect(r.status).toBe(401);
  });

  it('a valid logout ends the session and clears the cookie', async () => {
    const { cookie, csrf, hdr } = await login();
    const r = await req('POST', '/api/logout', { cookie, origin: `http://localhost:${srv.port}`, 'x-csrf-token': csrf });
    expect(r.status).toBe(200);
    expect((r.headers['set-cookie'] as string[])[0]).toMatch(/Max-Age=0/);
    expect((await req('GET', '/api/state', hdr)).status).toBe(401);
  });

  it('other non-GET methods are refused without CORS (OPTIONS, PUT, DELETE)', async () => {
    for (const m of ['OPTIONS', 'PUT', 'DELETE', 'PATCH']) {
      const r = await req(m, '/api/state', { origin: 'http://evil.test' });
      expect(r.status, m).toBe(403);
      expect(Object.keys(r.headers).some((h) => h.startsWith('access-control-'))).toBe(false);
    }
  });

  it('H1 has no action routes: a valid POST to another path gets 404 (R20)', async () => {
    const { cookie, csrf } = await login();
    for (const p of ['/api/state', '/api/actions/merge', '/api/session']) {
      const r = await req('POST', p, { cookie, origin: origin(), 'x-csrf-token': csrf });
      expect(r.status, p).toBe(404);
    }
  });

  it('a POST body over the limit gets 413', async () => {
    const { cookie, csrf } = await login();
    const r = await req(
      'POST',
      '/api/logout',
      { cookie, origin: origin(), 'x-csrf-token': csrf, 'content-type': 'application/json' },
      'x'.repeat(MAX_BODY_BYTES + 1),
    );
    expect(r.status).toBe(413);
  });
});

describe('response headers', () => {
  async function allResponses(): Promise<Res[]> {
    const code = await mintCode();
    const loginRes = await req('GET', `/login?code=${encodeURIComponent(code)}`);
    const cookie = cookieFrom(loginRes);
    const hdr = { cookie, 'x-caddis-hub-tab': tabFrom(loginRes) };
    const sess = await req('GET', '/api/session', hdr);
    const csrf = JSON.parse(sess.body).csrf_token as string;
    return [
      await req('GET', '/'),
      await req('GET', '/api/health', keyHdr()),
      await req('GET', '/api/health'),
      await req('POST', '/api/hub/code', keyHdr()),
      await req('POST', '/api/hub/code'),
      loginRes,
      await req('GET', '/login?code=bad'),
      sess,
      await req('GET', '/api/state', hdr),
      await req('GET', '/api/state', { cookie }),
      await req('GET', '/api/state'),
      await req('GET', '/nope'),
      await req('GET', '/', { host: 'evil.test' }),
      await req('POST', '/api/logout', { cookie }),
      await req('POST', '/api/logout', { cookie, origin: origin(), 'x-csrf-token': csrf }),
    ];
  }

  it('every response carries the CSP, nosniff, no-referrer and no Access-Control-* header', async () => {
    for (const r of await allResponses()) {
      expect(r.headers['content-security-policy']).toBe(CSP);
      expect(r.headers['x-content-type-options']).toBe('nosniff');
      expect(r.headers['referrer-policy']).toBe('no-referrer');
      expect(r.headers['access-control-allow-origin']).toBeUndefined();
      expect(Object.keys(r.headers).filter((h) => h.startsWith('access-control-'))).toEqual([]);
    }
  });

  it('/api/* responses carry Cache-Control: no-store', async () => {
    const { hdr } = await login();
    for (const r of [
      await req('GET', '/api/health', keyHdr()),
      await req('GET', '/api/state', hdr),
      await req('GET', '/api/session', hdr),
      await req('POST', '/api/hub/code', keyHdr()),
      await req('GET', '/api/nope'),
    ]) {
      expect(r.headers['cache-control']).toBe('no-store');
    }
  });

  it('the key never appears in any response body or header', async () => {
    for (const r of await allResponses()) {
      expect(r.body.includes(key)).toBe(false);
      expect(JSON.stringify(r.headers).includes(key)).toBe(false);
    }
  });
});

describe('pages and unknown routes', () => {
  it('GET / serves the built UI page (or the not-built page) with no inline script or style', async () => {
    // Static serving has its own tests in static.test.ts. This one uses the default folder, built or not.
    const r = await req('GET', '/');
    expect([200, 503]).toContain(r.status);
    expect(r.headers['content-type']).toMatch(/^text\/html/);
    expect(r.body).toContain('caddis hub');
    for (const m of r.body.matchAll(/<script[^>]*>/gi)) expect(m[0]).toMatch(/src=/);
    expect(r.body).not.toMatch(/<style|style=/i);
  });

  it('an unknown route gets 404 JSON', async () => {
    const r = await req('GET', '/nope');
    expect(r.status).toBe(404);
    expect(r.headers['content-type']).toMatch(/^application\/json/);
    expect(JSON.parse(r.body)).toMatchObject({ schema: 1, error: 'not_found' });
  });
});
