import { useCallback, useState } from 'react';
import { postAction } from '../api';
import type { ActionSpec } from './model';

/** The page's own view of a click, until the server state shows the request (R38). */
export interface LocalAction {
  status: 'sending' | 'sent' | 'refused';
  reason: string | null;
  requestId: string | null;
  at: number;
}

export interface ActApi {
  local: Record<string, LocalAction>;
  run: (spec: ActionSpec) => void;
}

/** One hook for every action button. After a send it asks for a fresh state at once. */
export function useActions(refresh: () => void): ActApi {
  const [local, setLocal] = useState<Record<string, LocalAction>>({});
  const put = (key: string, v: LocalAction): void => setLocal((prev) => ({ ...prev, [key]: v }));

  const run = useCallback(
    (spec: ActionSpec) => {
      put(spec.key, { status: 'sending', reason: null, requestId: null, at: Date.now() });
      void postAction(spec.body).then((r) => {
        if (r.ok) put(spec.key, { status: 'sent', reason: null, requestId: r.request.id, at: Date.now() });
        else put(spec.key, { status: 'refused', reason: r.reason, requestId: null, at: Date.now() });
        refresh();
      });
    },
    [refresh],
  );
  return { local, run };
}
