import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import {
  AuthStore,
  CODE_TTL_MS,
  MAX_CODES,
  MAX_SESSIONS,
  SESSION_IDLE_MS,
  SESSION_MAX_MS,
  SEEN_WRITE_MS,
  hostAllowed,
  originAllowed,
  parseCookies,
  safeEqual,
} from '../../src/hub/auth.js';

function clock(start = 1_000_000): { now: () => number; advance: (ms: number) => void } {
  let t = start;
  return { now: () => t, advance: (ms) => (t += ms) };
}

describe('safeEqual', () => {
  it('compares strings in constant time and handles length mismatch', () => {
    expect(safeEqual('abc', 'abc')).toBe(true);
    expect(safeEqual('abc', 'abd')).toBe(false);
    expect(safeEqual('abc', 'abcd')).toBe(false);
    expect(safeEqual('', 'x')).toBe(false);
  });
});

describe('hostAllowed', () => {
  it('accepts only 127.0.0.1:<port> and localhost:<port>', () => {
    expect(hostAllowed('127.0.0.1:5000', 5000)).toBe(true);
    expect(hostAllowed('localhost:5000', 5000)).toBe(true);
    expect(hostAllowed('LOCALHOST:5000', 5000)).toBe(true);
    expect(hostAllowed('evil.test:5000', 5000)).toBe(false);
    expect(hostAllowed('127.0.0.1:5001', 5000)).toBe(false);
    expect(hostAllowed('127.0.0.1', 5000)).toBe(false);
    expect(hostAllowed('localhost', 5000)).toBe(false);
    expect(hostAllowed('[::1]:5000', 5000)).toBe(false);
    expect(hostAllowed(undefined, 5000)).toBe(false);
    expect(hostAllowed('', 5000)).toBe(false);
  });
});

describe('originAllowed', () => {
  it('accepts exactly http://127.0.0.1:<port> or http://localhost:<port>', () => {
    expect(originAllowed('http://127.0.0.1:5000', 5000)).toBe(true);
    expect(originAllowed('http://localhost:5000', 5000)).toBe(true);
  });
  it('refuses missing, null and every other origin', () => {
    for (const o of [
      undefined,
      '',
      'null',
      'https://127.0.0.1:5000',
      'http://127.0.0.1:5001',
      'http://127.0.0.1:5000/',
      'http://evil.test:5000',
      'http://localhost.evil.test:5000',
      'http://127.0.0.1',
    ]) {
      expect(originAllowed(o, 5000), String(o)).toBe(false);
    }
  });
});

describe('parseCookies', () => {
  it('parses a cookie header', () => {
    expect(parseCookies('a=1; caddis_hub_session=xyz;b=2')).toEqual({ a: '1', caddis_hub_session: 'xyz', b: '2' });
    expect(parseCookies(undefined)).toEqual({});
  });
});

describe('AuthStore codes', () => {
  it('mints a 32-byte random code that works once', () => {
    const s = new AuthStore();
    const code = s.mintCode();
    expect(Buffer.from(code, 'base64url').length).toBe(32);
    expect(s.mintCode()).not.toBe(code);
    const session = s.redeemCode(code);
    expect(session).not.toBeNull();
    expect(s.redeemCode(code)).toBeNull();
  });

  it('refuses a code older than 60 s and consumes it', () => {
    const c = clock();
    const s = new AuthStore(c.now);
    const code = s.mintCode();
    c.advance(CODE_TTL_MS + 1);
    expect(s.redeemCode(code)).toBeNull();
    c.advance(-CODE_TTL_MS); // even back inside the window, the code is gone
    expect(s.redeemCode(code)).toBeNull();
  });

  it('accepts a code just inside 60 s', () => {
    const c = clock();
    const s = new AuthStore(c.now);
    const code = s.mintCode();
    c.advance(CODE_TTL_MS - 1);
    expect(s.redeemCode(code)).not.toBeNull();
  });

  it('refuses an unknown or empty code', () => {
    const s = new AuthStore();
    s.mintCode();
    expect(s.redeemCode('nope')).toBeNull();
    expect(s.redeemCode('')).toBeNull();
  });

  it('caps stored codes: the oldest drops out', () => {
    const s = new AuthStore();
    const first = s.mintCode();
    for (let i = 0; i < MAX_CODES; i++) s.mintCode();
    expect(s.codeCount()).toBe(MAX_CODES);
    expect(s.redeemCode(first)).toBeNull();
  });
});

describe('AuthStore sessions', () => {
  it('gives each session a CSRF token', () => {
    const s = new AuthStore();
    const id = s.redeemCode(s.mintCode())!;
    const sess = s.getSession(id)!;
    expect(sess.csrf).toMatch(/^[A-Za-z0-9_-]{43}$/);
    expect(sess.csrf).not.toBe(id);
    expect(s.getSession('wrong')).toBeNull();
    expect(s.getSession(undefined)).toBeNull();
  });

  it('deletes a session on logout', () => {
    const s = new AuthStore();
    const id = s.redeemCode(s.mintCode())!;
    s.deleteSession(id);
    expect(s.getSession(id)).toBeNull();
  });

  it('caps sessions: the oldest drops out', () => {
    const s = new AuthStore();
    const first = s.redeemCode(s.mintCode())!;
    for (let i = 0; i < MAX_SESSIONS; i++) s.redeemCode(s.mintCode());
    expect(s.sessionCount()).toBe(MAX_SESSIONS);
    expect(s.getSession(first)).toBeNull();
  });

  it('expires a session after the idle TTL and removes it', () => {
    const c = clock();
    const s = new AuthStore(c.now);
    const id = s.redeemCode(s.mintCode())!;
    c.advance(SESSION_IDLE_MS - 1);
    expect(s.getSession(id)).not.toBeNull(); // use resets the idle timer
    c.advance(SESSION_IDLE_MS - 1);
    expect(s.getSession(id)).not.toBeNull();
    c.advance(SESSION_IDLE_MS);
    expect(s.getSession(id)).toBeNull();
    expect(s.sessionCount()).toBe(0);
  });

  it('expires a session at the absolute TTL even when it stays in use', () => {
    const c = clock();
    const s = new AuthStore(c.now);
    const id = s.redeemCode(s.mintCode())!;
    const day = 24 * 60 * 60 * 1000;
    for (let d = 0; d < 29; d++) {
      c.advance(day);
      expect(s.getSession(id), `day ${d + 1}`).not.toBeNull();
    }
    c.advance(SESSION_MAX_MS - 29 * day);
    expect(s.getSession(id)).toBeNull();
    expect(s.sessionCount()).toBe(0);
  });

  it('uses a 7 day idle TTL and a 30 day absolute TTL (owner, 2026-10-26)', () => {
    expect(SESSION_IDLE_MS).toBe(7 * 24 * 60 * 60 * 1000);
    expect(SESSION_MAX_MS).toBe(30 * 24 * 60 * 60 * 1000);
  });

  it('discardCode consumes a code without making a session', () => {
    const s = new AuthStore();
    const code = s.mintCode();
    s.discardCode(code);
    expect(s.sessionCount()).toBe(0);
    expect(s.redeemCode(code)).toBeNull();
  });
});

describe('AuthStore saved sessions (a hub restart keeps the login)', () => {
  let dir = '';
  afterEach(() => {
    if (dir) rmSync(dir, { recursive: true, force: true });
    dir = '';
  });
  const fileIn = (): string => {
    dir = mkdtempSync(path.join(os.tmpdir(), 'caddis-auth-'));
    return path.join(dir, 'sessions.json');
  };
  const login = (s: AuthStore): { id: string; tab: string; csrf: string } => {
    const id = s.redeemCode(s.mintCode())!;
    const sess = s.getSession(id)!;
    return { id, tab: sess.tab, csrf: sess.csrf };
  };

  it('a new store on the same file knows the session, its tab token and its CSRF token', () => {
    const file = fileIn();
    const c = clock();
    const { id, tab, csrf } = login(new AuthStore(c.now, file));
    const after = new AuthStore(c.now, file);
    expect(after.getTabSession(id, tab)?.csrf).toBe(csrf);
    expect(after.getTabSession(id, 'wrong-tab')).toBeNull();
    expect(after.getSession('wrong')).toBeNull();
  });

  it('the file holds no session id and no tab token, only their hashes', () => {
    const file = fileIn();
    const { id, tab } = login(new AuthStore(Date.now, file));
    const text = readFileSync(file, 'utf8');
    expect(text).not.toContain(id);
    expect(text).not.toContain(tab);
  });

  it('a logout and an expiry reach the file', () => {
    const file = fileIn();
    const c = clock();
    const a = new AuthStore(c.now, file);
    const out = login(a);
    const stays = login(a);
    a.deleteSession(out.id);
    expect(new AuthStore(c.now, file).getSession(out.id)).toBeNull();
    c.advance(SESSION_IDLE_MS);
    expect(new AuthStore(c.now, file).getSession(stays.id)).toBeNull();
    expect(new AuthStore(c.now, file).sessionCount()).toBe(0);
  });

  it('use is saved at most once per SEEN_WRITE_MS, and saved use keeps the idle timer going across a restart', () => {
    const file = fileIn();
    const c = clock();
    const a = new AuthStore(c.now, file);
    const { id } = login(a);
    const before = readFileSync(file, 'utf8');
    c.advance(1000);
    a.getSession(id);
    expect(readFileSync(file, 'utf8')).toBe(before); // a poll every 5 s does not write the file
    c.advance(SEEN_WRITE_MS);
    a.getSession(id);
    expect(readFileSync(file, 'utf8')).not.toBe(before);
    c.advance(SESSION_IDLE_MS - 1);
    expect(new AuthStore(c.now, file).getSession(id)).not.toBeNull();
  });

  it('a missing, broken or odd file gives an empty store and no error', () => {
    const file = fileIn();
    expect(new AuthStore(Date.now, file).sessionCount()).toBe(0);
    writeFileSync(file, '{not json');
    expect(new AuthStore(Date.now, file).sessionCount()).toBe(0);
    writeFileSync(file, JSON.stringify({ schema: 1, sessions: [{ id_hash: 5 }, null, 'x'] }));
    expect(new AuthStore(Date.now, file).sessionCount()).toBe(0);
  });
});
