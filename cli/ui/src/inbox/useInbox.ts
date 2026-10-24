import { useCallback, useEffect, useMemo, useState } from 'react';
import type { HubState } from '../types';
import { deriveInbox, reconcile, withFrozen, type History, type InboxItem, type InboxModel } from './derive';
import {
  loadHistory,
  loadIdSet,
  NOTIFIED_KEY,
  NOTIFY_ON_KEY,
  READ_KEY,
  saveHistory,
  saveIdSet,
  browserStore,
} from './store';

export interface InboxApi {
  model: InboxModel;
  resolved: History['resolved'];
  read: Set<string>;
  markRead: (id: string) => void;
  notify: { supported: boolean; enabled: boolean; enable: () => void };
}

const EMPTY: InboxModel = {
  items: [],
  tiles: { waitingOnYou: 0, blockedMerges: 0, inQueue: 0, workingSessions: 0, lastDeploy: null },
};

const notificationsSupported = (): boolean => typeof window !== 'undefined' && 'Notification' in window;

/** One place for the derived items, the resolved history, read marks and opt-in notifications. */
export function useInbox(state: HubState | null, nowMs: number): InboxApi {
  const live = useMemo(() => (state ? deriveInbox(state, nowMs) : EMPTY), [state, nowMs]);
  const [history, setHistory] = useState<History>(() => loadHistory());
  // Items of a failing or stale source stay open (marked stale) until the source is back.
  const model = useMemo<InboxModel>(() => {
    if (!state) return live;
    const items = withFrozen(history.open, live.items, state);
    const count = (f: (i: InboxItem) => boolean): number => items.filter(f).length;
    return {
      items,
      tiles: {
        ...live.tiles,
        waitingOnYou: count((i) => i.folder === 'needs'),
        blockedMerges: count((i) => i.kind === 'blocked-merge'),
      },
    };
  }, [state, live, history.open]);
  const [read, setRead] = useState<Set<string>>(() => loadIdSet(READ_KEY));
  const [enabled, setEnabled] = useState<boolean>(() => {
    try {
      return notificationsSupported() && browserStore()?.getItem(NOTIFY_ON_KEY) === '1' && Notification.permission === 'granted';
    } catch {
      return false;
    }
  });

  // Only reconcile against real data: before the first state, an empty list would resolve nothing anyway.
  useEffect(() => {
    if (!state) return;
    setHistory((prev) => {
      const next = reconcile(prev, withFrozen(prev.open, live.items, state), Date.now());
      saveHistory(next);
      return next;
    });
  }, [state, live]);

  useEffect(() => {
    if (!enabled || !state) return;
    const notified = loadIdSet(NOTIFIED_KEY);
    let changed = false;
    for (const i of model.items) {
      if (notified.has(i.id)) continue;
      notified.add(i.id);
      changed = true;
      try {
        new Notification(`caddis hub: ${i.repo}`, { body: i.title, tag: i.id });
      } catch {
        /* a blocked notification is not an error */
      }
    }
    if (changed) saveIdSet(NOTIFIED_KEY, notified);
  }, [enabled, state, model]);

  const markRead = useCallback((id: string) => {
    setRead((prev) => {
      if (prev.has(id)) return prev;
      const next = new Set(prev).add(id);
      saveIdSet(READ_KEY, next);
      return next;
    });
  }, []);

  const enable = useCallback(() => {
    if (!notificationsSupported()) return;
    void Notification.requestPermission().then((p) => {
      if (p !== 'granted') return;
      try {
        browserStore()?.setItem(NOTIFY_ON_KEY, '1');
      } catch {
        /* works without storage */
      }
      // Items already open are not announced: mark them notified first.
      const notified = loadIdSet(NOTIFIED_KEY);
      for (const i of model.items) notified.add(i.id);
      saveIdSet(NOTIFIED_KEY, notified);
      setEnabled(true);
    });
  }, [model]);

  return {
    model,
    resolved: history.resolved,
    read,
    markRead,
    notify: { supported: notificationsSupported(), enabled, enable },
  };
}

export type { InboxItem };
