import { emptyHistory, sanitizeHistory, type History } from './derive';

export interface Store {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

export const HISTORY_KEY = 'caddis-hub-inbox-history';
export const READ_KEY = 'caddis-hub-inbox-read';
export const NOTIFIED_KEY = 'caddis-hub-inbox-notified';
export const NOTIFY_ON_KEY = 'caddis-hub-inbox-notify';
export const FOLDED_KEY = 'caddis-hub-lanes-folded';

/** localStorage, or null when the browser blocks it. Every read and write is guarded. */
export function browserStore(): Store | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export function readJson(key: string, store: Store | null): unknown {
  try {
    const t = store?.getItem(key);
    return t ? JSON.parse(t) : null;
  } catch {
    return null;
  }
}
export function writeJson(key: string, value: unknown, store: Store | null): void {
  try {
    store?.setItem(key, JSON.stringify(value));
  } catch {
    /* the page works without storage */
  }
}

export const loadHistory = (store: Store | null = browserStore()): History => {
  const raw = readJson(HISTORY_KEY, store);
  return raw ? sanitizeHistory(raw) : emptyHistory();
};
export const saveHistory = (h: History, store: Store | null = browserStore()): void => writeJson(HISTORY_KEY, h, store);

/** A set of ids kept in storage (read ids, notified ids). Capped so it never grows without bound. */
export function loadIdSet(key: string, store: Store | null = browserStore()): Set<string> {
  const raw = readJson(key, store);
  return new Set(Array.isArray(raw) ? raw.filter((x): x is string => typeof x === 'string') : []);
}
export function saveIdSet(key: string, ids: Set<string>, store: Store | null = browserStore()): void {
  writeJson(key, [...ids].slice(-500), store);
}
