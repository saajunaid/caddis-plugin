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

/** The spend level that triggers an advice note when the slot has none (owner rule: advise at EUR 300). */
export const ADVISE_EUR_DEFAULT = 300;

export interface SpendView {
  committedEur: number;
  adviseEur: number;
  /** True when the collector flags the spend, or the spend reaches the advise level. */
  advisory: boolean;
  /** 0-100, the spend as a share of the advise level. */
  pct: number;
}

/** Read the collector's spend slot. It is untyped on the server (a plain record). There is no cap any more
    (removed 1 Nov 2026): `cap_eur` is ignored, and a slot without a valid `advise_eur` uses 300. */
export function spendView(slot: Record<string, unknown> | null | undefined): SpendView {
  const advise = Number(slot?.advise_eur);
  const used = Number(slot?.committed_eur);
  const adviseEur = Number.isFinite(advise) && advise > 0 ? advise : ADVISE_EUR_DEFAULT;
  const committedEur = Number.isFinite(used) ? used : 0;
  return {
    committedEur,
    adviseEur,
    advisory: slot?.advisory === true || committedEur >= adviseEur,
    pct: Math.min(100, Math.max(0, (committedEur / adviseEur) * 100)),
  };
}

/** "300" for a whole number, "2.50" otherwise. */
export const formatEur = (n: number): string => (Number.isInteger(n) ? String(n) : n.toFixed(2));

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
