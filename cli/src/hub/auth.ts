import { createHash, randomBytes, timingSafeEqual } from 'node:crypto';
import { mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import path from 'node:path';

/** A one-time login code lives 60 s (R19). */
export const CODE_TTL_MS = 60_000;
/** Caps, so a loop of requests cannot grow memory. The oldest entry drops out. */
export const MAX_CODES = 20;
export const MAX_SESSIONS = 20;
/** A session ends after 7 days without use, or 30 days after login, whichever comes first (owner, 2026-10-26). */
export const SESSION_IDLE_MS = 7 * 24 * 60 * 60 * 1000;
export const SESSION_MAX_MS = 30 * 24 * 60 * 60 * 1000;
/** The page polls every 5 s; the saved "last used" time is written at most this often. */
export const SEEN_WRITE_MS = 5 * 60 * 1000;

export interface Session {
  /** The cookie value. Known only for a session made in this run; '' for one read from the file. */
  id: string;
  /** SHA-256 of the cookie value. Lookups compare this, so a saved session works after a restart. */
  idHash: string;
  csrf: string;
  /**
   * The per-tab token (final review I2). `/login` puts it in the URL fragment, which a browser never sends to a
   * server, and the page sends it back in a header. A cookie replayed from another localhost port lacks it.
   */
  tab: string;
  /** SHA-256 of the tab token. */
  tabHash: string;
  createdAt: number;
  lastSeenAt: number;
  /** The lastSeenAt value last written to the file. */
  savedSeenAt: number;
}

interface Code {
  value: string;
  mintedAt: number;
}

/** SHA-256 hex of a secret: what the session file keeps instead of the secret. */
export const hashToken = (v: string): string => createHash('sha256').update(v, 'utf8').digest('hex');

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
 * One-time codes (memory only) and sessions. With `file`, sessions are also saved there, so a hub restart does
 * not log the browser out. The file keeps SHA-256 hashes of the session id and tab token, never the values, plus
 * the CSRF token (it is only useful with a live session). Write: temp file, then rename. Mode 0600.
 * Lookups compare every stored hash with `safeEqual`, not a map key, so the check is constant time.
 */
export class AuthStore {
  private codes: Code[] = [];
  private sessions: Session[] = [];

  constructor(
    private readonly now: () => number = Date.now,
    private readonly file?: string,
  ) {
    this.sessions = this.load();
  }

  private load(): Session[] {
    if (!this.file) return [];
    let raw: unknown;
    try {
      raw = JSON.parse(readFileSync(this.file, 'utf8'));
    } catch {
      return [];
    }
    const list = (raw as { sessions?: unknown })?.sessions;
    if (!Array.isArray(list)) return [];
    const t = this.now();
    const out: Session[] = [];
    for (const e of list) {
      if (!e || typeof e !== 'object') continue;
      const r = e as Record<string, unknown>;
      const ok = (v: unknown): v is string => typeof v === 'string' && v.length > 0;
      const num = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
      if (!ok(r.id_hash) || !ok(r.tab_hash) || !ok(r.csrf) || !num(r.created_at) || !num(r.last_seen_at)) continue;
      const s: Session = {
        id: '',
        idHash: r.id_hash,
        csrf: r.csrf,
        tab: '',
        tabHash: r.tab_hash,
        createdAt: r.created_at,
        lastSeenAt: r.last_seen_at,
        savedSeenAt: r.last_seen_at,
      };
      if (!this.expired(s, t)) out.push(s);
    }
    return out.slice(-MAX_SESSIONS);
  }

  /** Write the sessions. A write that fails is ignored: the hub keeps working, the login is lost on restart. */
  private save(): void {
    if (!this.file) return;
    const body = {
      schema: 1,
      sessions: this.sessions.map((s) => ({
        id_hash: s.idHash,
        tab_hash: s.tabHash,
        csrf: s.csrf,
        created_at: s.createdAt,
        last_seen_at: s.lastSeenAt,
      })),
    };
    const tmp = `${this.file}.${process.pid}.tmp`;
    try {
      mkdirSync(path.dirname(this.file), { recursive: true });
      writeFileSync(tmp, JSON.stringify(body), { mode: 0o600 });
      renameSync(tmp, this.file);
      for (const s of this.sessions) s.savedSeenAt = s.lastSeenAt;
    } catch {
      /* ignore */
    }
  }

  private expired(s: Session, t: number): boolean {
    return t - s.lastSeenAt >= SESSION_IDLE_MS || t - s.createdAt >= SESSION_MAX_MS;
  }

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
    const id = randomToken();
    const tab = randomToken();
    const s: Session = {
      id,
      idHash: hashToken(id),
      csrf: randomToken(),
      tab,
      tabHash: hashToken(tab),
      createdAt: t,
      lastSeenAt: t,
      savedSeenAt: t,
    };
    this.sessions.push(s);
    while (this.sessions.length > MAX_SESSIONS) this.sessions.shift();
    this.save();
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
    const idHash = hashToken(id);
    let found: Session | null = null;
    for (const s of this.sessions) if (safeEqual(s.idHash, idHash)) found = s;
    if (!found) return null;
    if (tab !== null && !safeEqual(found.tabHash, hashToken(tab))) return null;
    const t = this.now();
    if (this.expired(found, t)) {
      this.sessions = this.sessions.filter((x) => x !== found);
      this.save();
      return null;
    }
    found.lastSeenAt = t;
    if (t - found.savedSeenAt >= SEEN_WRITE_MS) this.save();
    return found;
  }

  deleteSession(id: string): void {
    const s = this.getSession(id);
    if (!s) return;
    this.sessions = this.sessions.filter((x) => x !== s);
    this.save();
  }

  codeCount(): number {
    return this.codes.length;
  }

  sessionCount(): number {
    return this.sessions.length;
  }
}
