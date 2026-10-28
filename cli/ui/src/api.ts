import type { ActionBody } from './actions/model';
import type { HubState } from './types';

export const TAB_KEY = 'caddis-hub-tab';
export const TAB_HEADER = 'X-Caddis-Hub-Tab';
export const CSRF_HEADER = 'X-CSRF-Token';

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export interface SessionInfo {
  schema: number;
  csrf_token: string;
  versions: Record<string, string>;
}

type StorageLike = Pick<Storage, 'getItem' | 'setItem'>;
interface LocLike {
  hash: string;
  pathname: string;
  search: string;
}
interface HistLike {
  replaceState(data: unknown, unused: string, url?: string | URL | null): void;
}

function safeStorage(): StorageLike | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

let memoryTab: string | null = null;

/**
 * Run once at start. The login redirect sends `/#tab=<token>`. Read the token, keep it in localStorage: the origin is 127.0.0.1:<port>, so the token stays port-scoped; a new tab needs no new login.
 * (and in memory, in case storage is blocked), then remove the hash so it stays out of history and screenshots.
 */
export function captureTab(
  loc: LocLike = window.location,
  hist: HistLike = window.history,
  storage: StorageLike | null = safeStorage(),
): void {
  const m = /(?:^#|&)tab=([^&]+)/.exec(loc.hash);
  if (!m?.[1]) return;
  let token: string;
  try {
    token = decodeURIComponent(m[1]);
  } catch {
    return; // a malformed `%` gives no token; the page shows the sign-in notice
  }
  memoryTab = token;
  try {
    storage?.setItem(TAB_KEY, token);
  } catch {
    /* the in-memory copy still works */
  }
  hist.replaceState(null, '', loc.pathname + loc.search);
}

export function getTab(storage: StorageLike | null = safeStorage()): string | null {
  try {
    return storage?.getItem(TAB_KEY) || memoryTab;
  } catch {
    return memoryTab;
  }
}

/** Headers for every /api request. Later tasks add the CSRF header with `csrf`. */
export function apiHeaders(tab: string | null, csrf?: string): Record<string, string> {
  const h: Record<string, string> = { Accept: 'application/json' };
  if (tab) h[TAB_HEADER] = tab;
  if (csrf) h[CSRF_HEADER] = csrf;
  return h;
}

async function getJson<T>(path: string): Promise<T> {
  const tab = getTab();
  // No token: do not call the API. The page shows the sign-in text.
  if (!tab) throw new ApiError(401, 'no tab token');
  const res = await fetch(path, { headers: apiHeaders(tab), credentials: 'same-origin', cache: 'no-store' });
  if (!res.ok) throw new ApiError(res.status, `${path} answered ${res.status}`);
  return (await res.json()) as T;
}

export const getSession = (): Promise<SessionInfo> => getJson<SessionInfo>('/api/session');
export const getState = (): Promise<HubState> => getJson<HubState>('/api/state');

export interface PlanPhaseSection {
  schema: number;
  title: string;
  text: string;
}

export const getPlanPhase = (repo: string, plan: string, key: string): Promise<PlanPhaseSection> =>
  getJson<PlanPhaseSection>(
    '/api/plan-phase?repo=' +
      encodeURIComponent(repo) +
      '&plan=' +
      encodeURIComponent(plan) +
      '&key=' +
      encodeURIComponent(key),
  );

let csrfCache: string | null = null;

/** The session's CSRF token, read once from `/api/session` and kept for this page. */
async function csrfToken(): Promise<string> {
  if (!csrfCache) csrfCache = (await getSession()).csrf_token;
  return csrfCache;
}

export interface ActionAccepted {
  ok: true;
  request: { id: string; created_at: string };
}
export interface ActionRefused {
  ok: false;
  status: number;
  error: string;
  reason: string;
}

/**
 * Send one owner action (R32). The browser adds Origin; the page adds the CSRF and tab headers. A 403 can mean the
 * CSRF token is old (a hub restart): the page reads a new one and tries once more. Never throws.
 */
export async function postAction(body: ActionBody): Promise<ActionAccepted | ActionRefused> {
  const tab = getTab();
  if (!tab) return { ok: false, status: 401, error: 'unauthorized', reason: 'Signed out. Run caddis hub open.' };
  const send = async (): Promise<Response> =>
    fetch('/api/actions', {
      method: 'POST',
      headers: { ...apiHeaders(tab, await csrfToken()), 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      credentials: 'same-origin',
      cache: 'no-store',
    });
  try {
    let res = await send();
    if (res.status === 403) {
      csrfCache = null;
      res = await send();
    }
    const data = (await res.json().catch(() => ({}))) as Record<string, unknown>;
    if (res.status === 202 && data.request && typeof data.request === 'object') {
      return { ok: true, request: data.request as ActionAccepted['request'] };
    }
    return {
      ok: false,
      status: res.status,
      error: typeof data.error === 'string' ? data.error : 'failed',
      reason: typeof data.reason === 'string' ? data.reason : `The hub answered ${res.status}.`,
    };
  } catch {
    return { ok: false, status: 0, error: 'network', reason: 'The hub did not answer.' };
  }
}
