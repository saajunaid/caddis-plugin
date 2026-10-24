import type { HubState } from '../types';

export const APP_NAME = 'caddis hub';

/** Tab title: `(<n>) caddis hub` when the inbox holds items. */
export function titleFor(count: number): string {
  return count > 0 ? `(${count}) ${APP_NAME}` : APP_NAME;
}

/** "just now", "12 s ago", "3 min ago", "2 h ago", "3 d ago". Null or a bad date gives "unknown". */
export function ageText(iso: string | null | undefined, nowMs: number): string {
  if (!iso) return 'unknown';
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return 'unknown';
  const s = Math.max(0, Math.round((nowMs - t) / 1000));
  if (s < 5) return 'just now';
  if (s < 60) return `${s} s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} h ago`;
  return `${Math.floor(h / 24)} d ago`;
}

export const dataAgeText = (generatedAt: string | null | undefined, nowMs: number): string =>
  `Updated ${ageText(generatedAt, nowMs)}`;

/** Local clock time "HH:MM" of an ISO time, or "unknown". */
export function clockText(iso: string | null | undefined): string {
  if (!iso) return 'unknown';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return 'unknown';
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export interface SpendView {
  configured: boolean;
  capEur: number;
  committedEur: number;
  /** 0-100 */
  pct: number;
}

/** Read the collector's spend slot. It is untyped on the server (a plain record). */
export function spendView(slot: Record<string, unknown> | null | undefined): SpendView {
  const cap = Number(slot?.cap_eur);
  const used = Number(slot?.committed_eur);
  const configured = slot?.configured === true && Number.isFinite(cap) && cap > 0;
  const committedEur = Number.isFinite(used) ? used : 0;
  return {
    configured,
    capEur: configured ? cap : 0,
    committedEur,
    pct: configured ? Math.min(100, Math.max(0, (committedEur / cap) * 100)) : 0,
  };
}

/** True when any source fails or is stale: the numbers on the page are then greyed. */
export const anySourceDown = (state: HubState): boolean =>
  Object.values(state.sources ?? {}).some((x) => !x.ok || x.stale);

export const QUOTA_LOW = 500;
export interface QuotaView {
  account: string;
  remaining: number;
  resetAt: string | null;
}

/** The lowest GitHub quota of any account, from `github_rate` (R40), or null before the first GitHub call. */
export function quotaLowest(state: HubState | null): QuotaView | null {
  const rate = (state as { github_rate?: unknown } | null)?.github_rate;
  if (!rate || typeof rate !== 'object') return null;
  let worst: QuotaView | null = null;
  for (const [account, v] of Object.entries(rate as Record<string, unknown>)) {
    const o = v as { remaining?: unknown; reset_at?: unknown } | null;
    const remaining = typeof o?.remaining === 'number' && Number.isFinite(o.remaining) ? o.remaining : NaN;
    if (Number.isNaN(remaining)) continue;
    if (!worst || remaining < worst.remaining) worst = { account, remaining, resetAt: typeof o?.reset_at === 'string' ? o.reset_at : null };
  }
  return worst;
}

/** The lowest GitHub quota when it is below the reserve (L10), or null. */
export function quotaLow(state: HubState | null): QuotaView | null {
  const q = quotaLowest(state);
  return q && q.remaining < QUOTA_LOW ? q : null;
}
