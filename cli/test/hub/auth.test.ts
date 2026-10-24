import { describe, expect, it } from 'vitest';
import {
  AuthStore,
  CODE_TTL_MS,
  MAX_CODES,
  MAX_SESSIONS,
  SESSION_IDLE_MS,
  SESSION_MAX_MS,
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

  it('expires a session after 12 h idle and removes it', () => {
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

  it('expires a session 24 h after login even when it stays in use', () => {
    const c = clock();
    const s = new AuthStore(c.now);
    const id = s.redeemCode(s.mintCode())!;
    for (let h = 0; h < 23; h++) {
      c.advance(60 * 60 * 1000);
      expect(s.getSession(id), `hour ${h + 1}`).not.toBeNull();
    }
    c.advance(SESSION_MAX_MS - 23 * 60 * 60 * 1000);
    expect(s.getSession(id)).toBeNull();
    expect(s.sessionCount()).toBe(0);
  });

  it('uses a 12 h idle TTL and a 24 h absolute TTL', () => {
    expect(SESSION_IDLE_MS).toBe(12 * 60 * 60 * 1000);
    expect(SESSION_MAX_MS).toBe(24 * 60 * 60 * 1000);
  });

  it('discardCode consumes a code without making a session', () => {
    const s = new AuthStore();
    const code = s.mintCode();
    s.discardCode(code);
    expect(s.sessionCount()).toBe(0);
    expect(s.redeemCode(code)).toBeNull();
  });
});
