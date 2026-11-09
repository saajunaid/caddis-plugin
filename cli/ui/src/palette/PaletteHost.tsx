import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react';
import type { InboxItem } from '../inbox/derive';
import type { HubState } from '../types';

// The palette code and CSS load on the first open, so the first bundle does not grow (budget.test.ts).
const Palette = lazy(() => import('./Palette'));

/** Ctrl+K or Meta+K, without Alt. It opens the palette even while the owner types: it is not a text key. */
export const isPaletteKey = (e: Pick<KeyboardEvent, 'key' | 'ctrlKey' | 'metaKey' | 'altKey'>): boolean =>
  (e.ctrlKey || e.metaKey) && !e.altKey && (e.key === 'k' || e.key === 'K');

export interface PaletteApi {
  open: boolean;
  /** Open the palette. Focus goes back to `returnTo` (else the element that has focus now) when it closes. */
  show: (returnTo?: HTMLElement | null) => void;
  hide: () => void;
}

/** The palette's open state, the Ctrl+K listener and the focus to give back. */
export function usePalette(): PaletteApi {
  const [open, setOpen] = useState(false);
  const isOpen = useRef(false);
  const back = useRef<HTMLElement | null>(null);

  const show = useCallback((returnTo?: HTMLElement | null) => {
    if (isOpen.current) return;
    const active = document.activeElement;
    back.current = returnTo ?? (active instanceof HTMLElement ? active : null);
    isOpen.current = true;
    setOpen(true);
  }, []);

  const hide = useCallback(() => {
    if (!isOpen.current) return;
    isOpen.current = false;
    setOpen(false);
    const el = back.current;
    back.current = null;
    if (el?.isConnected) el.focus();
  }, []);

  useEffect(() => {
    const on = (e: KeyboardEvent): void => {
      if (!isPaletteKey(e)) return;
      e.preventDefault();
      show();
    };
    window.addEventListener('keydown', on);
    return () => window.removeEventListener('keydown', on);
  }, [show]);

  return { open, show, hide };
}

export function PaletteHost({ pal, state, inbox, nowMs }: { pal: PaletteApi; state: HubState | null; inbox: InboxItem[]; nowMs: number }): JSX.Element | null {
  if (!pal.open || !state) return null;
  return (
    <Suspense fallback={null}>
      <Palette state={state} inbox={inbox} nowMs={nowMs} onClose={pal.hide} />
    </Suspense>
  );
}
