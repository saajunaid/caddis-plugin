import { useEffect, useRef, type RefObject } from 'react';

const FOCUSABLE = 'a[href], button';

/** The next index in a focus loop of `count` items: back from the first goes to the last, forward from the last to the first. */
export function trapIndex(count: number, index: number, back: boolean): number {
  if (back) return index <= 0 ? count - 1 : index - 1;
  return index >= count - 1 ? 0 : index + 1;
}

/** The phone drawer as a modal dialog: focus moves in, Tab stays inside, Escape closes, and focus goes back to the
    button that opened it. */
export function useDrawer(open: boolean, close: () => void, panel: RefObject<HTMLElement>, opener: RefObject<HTMLButtonElement>): void {
  const wasOpen = useRef(false);
  const closeRef = useRef(close);
  closeRef.current = close;

  useEffect(() => {
    if (!open) {
      if (wasOpen.current) opener.current?.focus();
      wasOpen.current = false;
      return;
    }
    wasOpen.current = true;
    const items = (): HTMLElement[] => [...(panel.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [])];
    items()[0]?.focus();
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') {
        closeRef.current();
        return;
      }
      if (e.key !== 'Tab') return;
      const all = items();
      if (all.length === 0) return;
      e.preventDefault();
      const at = all.indexOf(document.activeElement as HTMLElement);
      all[trapIndex(all.length, at, e.shiftKey)]?.focus();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, panel, opener]);
}
