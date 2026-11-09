import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { ApiError, getState } from './api';
import type { HubState } from './types';

export const POLL_MS = 10_000;
/** How long the "hub updated" notice shows before the tab reloads. */
export const RELOAD_AFTER_MS = 2_000;

/**
 * The new hub version when this tab should reload, else null.
 * `first` is the first `versions.hub` this tab saw. A missing or empty version never reloads.
 */
export function hubUpdatedTo(first: string | null, current: string | undefined): string | null {
  return first && current && current !== first ? current : null;
}

// The version the hub was updated to, shown by `Banners` until the reload. One per tab.
let updatedTo: string | null = null;
const listeners = new Set<() => void>();
const subscribe = (fn: () => void): (() => void) => {
  listeners.add(fn);
  return () => listeners.delete(fn);
};

/** The version the hub was updated to while this tab was open, or null. */
export function useHubUpdatedTo(): string | null {
  return useSyncExternalStore(subscribe, () => updatedTo);
}

export interface HubStateResult {
  state: HubState | null;
  /** 'unauthorized': no tab token or a 401. 'network': the hub did not answer. */
  error: 'unauthorized' | 'network' | null;
  loading: boolean;
  refresh: () => void;
}

/** Poll `GET /api/state` every 10 s. Pause while the tab is hidden, and refresh when it shows again. */
export function useHubState(): HubStateResult {
  const [state, setState] = useState<HubState | null>(null);
  const [error, setError] = useState<HubStateResult['error']>(null);
  const [loading, setLoading] = useState(true);
  const timer = useRef<number | undefined>(undefined);
  const alive = useRef(true);
  const firstVersion = useRef<string | null>(null);

  const load = useCallback(async () => {
    try {
      const s = await getState();
      if (!alive.current) return;
      setState(s);
      setError(null);
      // The hub restarted on a new version: reload once, so the tab runs the new UI.
      firstVersion.current ??= s.versions?.hub || null;
      const next = hubUpdatedTo(firstVersion.current, s.versions?.hub);
      if (next && updatedTo === null) {
        updatedTo = next;
        listeners.forEach((fn) => fn());
        window.setTimeout(() => window.location.reload(), RELOAD_AFTER_MS);
      }
    } catch (e) {
      if (!alive.current) return;
      setError(e instanceof ApiError && e.status === 401 ? 'unauthorized' : 'network');
    } finally {
      if (alive.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    const stop = (): void => window.clearInterval(timer.current);
    const start = (): void => {
      stop();
      timer.current = window.setInterval(() => void load(), POLL_MS);
    };
    const onVis = (): void => {
      if (document.hidden) stop();
      else {
        void load();
        start();
      }
    };
    void load();
    if (!document.hidden) start();
    document.addEventListener('visibilitychange', onVis);
    return () => {
      alive.current = false;
      stop();
      document.removeEventListener('visibilitychange', onVis);
    };
  }, [load]);

  const refresh = useCallback(() => void load(), [load]);
  return { state, error, loading, refresh };
}
