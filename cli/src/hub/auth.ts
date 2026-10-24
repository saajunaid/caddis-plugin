import { createHash, randomBytes, timingSafeEqual } from 'node:crypto';

/** A one-time login code lives 60 s (R19). */
export const CODE_TTL_MS = 60_000;
/** Caps, so a loop of requests cannot grow memory. The oldest entry drops out. */
export const MAX_CODES = 20;
export const MAX_SESSIONS = 20;
/** A session ends after 12 h without use, or 24 h after login, whichever comes first. */
export const SESSION_IDLE_MS = 12 * 60 * 60 * 1000;
export const SESSION_MAX_MS = 24 * 60 * 60 * 1000;

export interface Session {
  id: string;
  csrf: string;
  /**
   * The per-tab token (final review I2). `/login` puts it in the URL fragment, which a browser never sends to a
   * server, and the page sends it back in a header. A cookie replayed from another localhost port lacks it.
   */
  tab: string;
  createdAt: number;
  lastSeenAt: number;
}

interface Code {
  value: string;
  mintedAt: number;
}

/** 32 random bytes as base64url (43 characters). */
export function randomToken(): string {
  return randomBytes(32).toString('base64url');
}

/**
 * Compare two secrets in constant time.
 * Both sides are hashed first, so the length of the secret does not leak and
 * `timingSafeEqual` always gets two buffers of the same length.
 */
export function safeEqual(a: string, b: string): boolean {
  const ha = createHash('sha256').update(a, 'utf8').digest();
  const hb = createHash('sha256').update(b, 'utf8').digest();
  return timingSafeEqual(ha, hb) && a.length === b.length;
}

/** R19: Host must be `127.0.0.1:<port>` or `localhost:<port>`. Host names are case-insensitive. */
export function hostAllowed(host: string | undefined, port: number): boolean {
  if (!host) return false;
  const h = host.toLowerCase();
  return h === `127.0.0.1:${port}` || h === `localhost:${port}`;
}

/**
 * R19: on every non-GET, Origin must be exactly `http://127.0.0.1:<port>` or `http://localhost:<port>`.
 * A missing Origin or `null` is refused.
 */
export function originAllowed(origin: string | undefined, port: number): boolean {
  if (!origin) return false;
  return origin === `http://127.0.0.1:${port}` || origin === `http://localhost:${port}`;
}

/** Parse a Cookie header. The first value of a name wins. */
export function parseCookies(header: string | undefined): Record<string, string> {
  const out: Record<string, string> = {};
  if (!header) return out;
  for (const part of header.split(';')) {
    const i = part.indexOf('=');
    if (i < 1) continue;
    const name = part.slice(0, i).trim();
    if (name && !(name in out)) out[name] = part.slice(i + 1).trim();
  }
  return out;
}

/**
 * One-time codes and sessions, in memory only. A restart logs the browser out.
 * Lookups compare every stored value with `safeEqual`, not a map key, so the check is constant time.
 */
export class AuthStore {
  private codes: Code[] = [];
  private sessions: Session[] = [];

  constructor(private readonly now: () => number = Date.now) {}

  /** Mint a single-use code. Expired codes are dropped first; then the oldest goes past the cap. */
  mintCode(): string {
    const t = this.now();
    this.codes = this.codes.filter((c) => t - c.mintedAt < CODE_TTL_MS);
    const value = randomToken();
    this.codes.push({ value, mintedAt: t });
    while (this.codes.length > MAX_CODES) this.codes.shift();
    return value;
  }

  /** Expiry time of a code minted now, as UTC ISO 8601. */
  codeExpiresAt(): string {
    return new Date(this.now() + CODE_TTL_MS).toISOString();
  }

  /**
   * Swap a code for a new session id. The code is removed before the age check,
   * so a code is consumed even when this call fails. Returns null on failure.
   */
  redeemCode(code: string): string | null {
    if (!code) return null;
    let found: Code | undefined;
    for (const c of this.codes) if (safeEqual(c.value, code)) found = c;
    if (!found) return null;
    this.codes = this.codes.filter((c) => c !== found);
    const age = this.now() - found.mintedAt;
    if (age < 0 || age >= CODE_TTL_MS) return null;
    const t = this.now();
    const s: Session = { id: randomToken(), csrf: randomToken(), tab: randomToken(), createdAt: t, lastSeenAt: t };
    this.sessions.push(s);
    while (this.sessions.length > MAX_SESSIONS) this.sessions.shift();
    return s.id;
  }

  /** Remove a code without making a session (a refused /login still uses up its code). */
  discardCode(code: string): void {
    if (!code) return;
    this.codes = this.codes.filter((c) => !safeEqual(c.value, code));
  }

  /**
   * Find a live session and mark it used. A session past the idle TTL or the absolute TTL
   * is removed and the call returns null.
   */
  getSession(id: string | undefined): Session | null {
    return this.findSession(id, null);
  }

  /**
   * As getSession, but the session's tab token must match too (constant time). A wrong or missing token
   * returns null and does not mark the session used.
   */
  getTabSession(id: string | undefined, tab: string | undefined): Session | null {
    return this.findSession(id, tab ?? '');
  }

  private findSession(id: string | undefined, tab: string | null): Session | null {
    if (!id) return null;
    let found: Session | null = null;
    for (const s of this.sessions) if (safeEqual(s.id, id)) found = s;
    if (!found) return null;
    if (tab !== null && !safeEqual(found.tab, tab)) return null;
    const t = this.now();
    if (t - found.lastSeenAt >= SESSION_IDLE_MS || t - found.createdAt >= SESSION_MAX_MS) {
      this.sessions = this.sessions.filter((x) => x !== found);
      return null;
    }
    found.lastSeenAt = t;
    return found;
  }

  deleteSession(id: string): void {
    const s = this.getSession(id);
    if (s) this.sessions = this.sessions.filter((x) => x !== s);
  }

  codeCount(): number {
    return this.codes.length;
  }

  sessionCount(): number {
    return this.sessions.length;
  }
}
