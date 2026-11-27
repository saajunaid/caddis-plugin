import { useCallback, useRef, useState } from 'react';
import { postSync, type SyncOutcome } from '../api';

export interface SyncApi {
  syncing: boolean;
  /** The text of the last failed sync, or null. A new sync clears it. */
  error: string | null;
  run: () => void;
}

/** "Sync now": one request at a time. After it ends, ask for a fresh state at once, so the page shows the result. */
export function useSync(refresh: () => void): SyncApi {
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const busy = useRef(false);
  const run = useCallback(() => {
    if (busy.current) return;
    busy.current = true;
    setSyncing(true);
    setError(null);
    void postSync()
      .catch((): SyncOutcome => ({ ok: false, error: 'Sync failed.' }))
      .then((r) => {
        busy.current = false;
        setSyncing(false);
        setError(r.ok ? null : (r.error ?? 'Sync failed.'));
        refresh();
      });
  }, [refresh]);
  return { syncing, error, run };
}
