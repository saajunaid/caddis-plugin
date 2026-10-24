import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, getState } from './api';
import type { HubState } from './types';

export const POLL_MS = 10_000;

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

  const load = useCallback(async () => {
    try {
      const s = await getState();
      if (!alive.current) return;
      setState(s);
      setError(null);
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
