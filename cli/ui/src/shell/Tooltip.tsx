import { cloneElement, useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import type { FocusEvent, PointerEvent, ReactElement, ReactNode } from 'react';
import { createPortal } from 'react-dom';

/** Hover information (plan D12). WCAG 1.4.13: dismissable (Escape), hoverable, persistent while the pointer is on it. */
export const SHOW_DELAY_MS = 150;
export const HIDE_DELAY_MS = 100;
const GAP = 8;
const MARGIN = 8;

interface Box {
  top: number;
  left: number;
  right: number;
  bottom: number;
}
export interface TipPlace {
  top: number;
  left: number;
  placement: 'above' | 'below';
}

/** Where a fixed bubble goes: below the trigger, above when there is no room below, always inside the viewport. */
export function tipPosition(
  rect: Box,
  bubble: { width: number; height: number },
  viewport: { width: number; height: number },
): TipPlace {
  const fitsBelow = rect.bottom + GAP + bubble.height <= viewport.height - MARGIN;
  const fitsAbove = rect.top - GAP - bubble.height >= MARGIN;
  const placement = fitsBelow || !fitsAbove ? 'below' : 'above';
  const rawTop = placement === 'below' ? rect.bottom + GAP : rect.top - GAP - bubble.height;
  const top = Math.max(0, Math.min(rawTop, viewport.height - bubble.height));
  const maxLeft = Math.max(0, viewport.width - bubble.width - MARGIN);
  const left = Math.max(MARGIN, Math.min(rect.left, maxLeft));
  return { top, left: Math.min(left, maxLeft), placement };
}

const isEmpty = (c: ReactNode): boolean => c === null || c === undefined || c === false || c === '';

type Handlers = {
  onPointerEnter?: (e: PointerEvent<HTMLElement>) => void;
  onPointerLeave?: (e: PointerEvent<HTMLElement>) => void;
  onFocus?: (e: FocusEvent<HTMLElement>) => void;
  onBlur?: (e: FocusEvent<HTMLElement>) => void;
  'aria-describedby'?: string;
};

export function Tooltip({ content, children }: { content: ReactNode; children: ReactElement }): JSX.Element {
  const id = useId();
  const empty = isEmpty(content);
  const [shown, setShown] = useState(false);
  const [place, setPlace] = useState<TipPlace | null>(null);
  const anchor = useRef<HTMLElement | null>(null);
  const bubble = useRef<HTMLDivElement | null>(null);
  const timer = useRef<number | undefined>(undefined);

  const clear = useCallback((): void => {
    window.clearTimeout(timer.current);
    timer.current = undefined;
  }, []);
  const open = useCallback(
    (el?: HTMLElement): void => {
      if (el) anchor.current = el;
      clear();
      timer.current = window.setTimeout(() => setShown(true), SHOW_DELAY_MS);
    },
    [clear],
  );
  const close = useCallback((): void => {
    clear();
    timer.current = window.setTimeout(() => setShown(false), HIDE_DELAY_MS);
  }, [clear]);
  // A pointer that reached the bubble, or a focus that stayed, cancels the pending hide.
  const keep = useCallback((): void => {
    clear();
    setShown(true);
  }, [clear]);

  const visible = shown && !empty;

  useEffect(() => clear, [clear]);
  // Content that goes away while the bubble is open closes it at once.
  useEffect(() => {
    if (empty) {
      clear();
      setShown(false);
    }
  }, [empty, clear]);

  useEffect(() => {
    if (!visible) return;
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') {
        clear();
        setShown(false);
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [visible, clear]);

  const reposition = useCallback((): void => {
    const a = anchor.current;
    const b = bubble.current;
    if (!a || !b) return;
    const br = b.getBoundingClientRect();
    setPlace(
      tipPosition(a.getBoundingClientRect(), { width: br.width, height: br.height }, { width: window.innerWidth, height: window.innerHeight }),
    );
  }, []);

  useLayoutEffect(() => {
    if (!visible) {
      setPlace(null);
      return;
    }
    reposition();
    window.addEventListener('resize', reposition);
    window.addEventListener('scroll', reposition, true);
    return () => {
      window.removeEventListener('resize', reposition);
      window.removeEventListener('scroll', reposition, true);
    };
  }, [visible, content, reposition]);

  if (empty) return children;

  const own = children.props as Handlers;
  const trigger = cloneElement(children as ReactElement<Handlers>, {
    onPointerEnter: (e: PointerEvent<HTMLElement>) => {
      own.onPointerEnter?.(e);
      if (shown) keep();
      else open(e.currentTarget);
    },
    onPointerLeave: (e: PointerEvent<HTMLElement>) => {
      own.onPointerLeave?.(e);
      close();
    },
    onFocus: (e: FocusEvent<HTMLElement>) => {
      own.onFocus?.(e);
      if (shown) keep();
      else open(e.currentTarget);
    },
    onBlur: (e: FocusEvent<HTMLElement>) => {
      own.onBlur?.(e);
      close();
    },
    'aria-describedby': visible ? id : own['aria-describedby'],
  });

  return (
    <>
      {trigger}
      {visible &&
        createPortal(
          <div
            ref={bubble}
            id={id}
            role="tooltip"
            className="tip"
            data-testid="tip"
            data-placement={place?.placement}
            style={{ position: 'fixed', top: place?.top ?? 0, left: place?.left ?? 0, visibility: place ? 'visible' : 'hidden' }}
            onPointerEnter={keep}
            onPointerLeave={close}
          >
            {content}
          </div>,
          document.body,
        )}
    </>
  );
}
