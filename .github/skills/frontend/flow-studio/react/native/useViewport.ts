import { useCallback, useRef, useState, type KeyboardEventHandler, type PointerEventHandler } from "react";
import { clampPan, fitRect, zoomAt, type Rect, type Size, type View } from "../../src/viewport.ts";

export interface ViewportBind {
  /** Spread onto the viewport element. The hook owns this ref: it measures the element and listens here. */
  ref: (element: HTMLElement | null) => void;
  onPointerDown: PointerEventHandler<HTMLElement>;
  onPointerMove: PointerEventHandler<HTMLElement>;
  onPointerUp: PointerEventHandler<HTMLElement>;
  onPointerCancel: PointerEventHandler<HTMLElement>;
  onKeyDown: KeyboardEventHandler<HTMLElement>;
  tabIndex: number;
}

/** Canvas state and DOM bindings. Coordinates passed to zoomBy are local to the viewport. */
export function useViewport(bounds: Rect, initial: View = { x: 0, y: 0, k: 1 }) {
  const [view, setView] = useState<View>(initial);
  const viewport = useRef<HTMLElement | null>(null);
  const drag = useRef<{ x: number; y: number; view: View } | null>(null);
  const zoomBy = useCallback((factor: number, x: number, y: number) => {
    setView(previous => zoomAt(previous, factor, x, y));
  }, []);
  /** Zoom by a factor about the center of the attached viewport element. */
  const zoomAboutCenter = useCallback((factor: number) => {
    const element = viewport.current;
    zoomBy(factor, (element?.clientWidth ?? 0) / 2, (element?.clientHeight ?? 0) / 2);
  }, [zoomBy]);
  const fit = useCallback((size?: Size) => {
    const measured = size ?? { w: viewport.current?.clientWidth ?? 0, h: viewport.current?.clientHeight ?? 0 };
    setView(fitRect(bounds, measured, 24, 44));
  }, [bounds]);
  // React's synthetic onWheel listener is passive, so its preventDefault cannot stop the page
  // scrolling. Wheel zoom must be a native listener with { passive: false } on the viewport element.
  const onWheelZoom = useCallback((event: WheelEvent) => {
    event.preventDefault();
    const element = event.currentTarget as HTMLElement | null;
    if (!element) return;
    const rect = element.getBoundingClientRect();
    zoomBy(Math.exp(-event.deltaY * 0.001), event.clientX - rect.left, event.clientY - rect.top);
  }, [zoomBy]);
  // The element ref is also what makes fit() work before the first pointer or wheel interaction.
  const setViewportElement = useCallback((element: HTMLElement | null) => {
    if (viewport.current === element) return;
    viewport.current?.removeEventListener("wheel", onWheelZoom);
    viewport.current = element;
    element?.addEventListener("wheel", onWheelZoom, { passive: false });
  }, [onWheelZoom]);
  const stop: PointerEventHandler<HTMLElement> = event => {
    if (drag.current) event.currentTarget.releasePointerCapture?.(event.pointerId);
    drag.current = null;
  };
  const bind: ViewportBind = {
    tabIndex: 0,
    ref: setViewportElement,
    onPointerDown: event => {
      if (event.button !== 0 || (event.target as Element).closest("button,a,input")) return;
      drag.current = { x: event.clientX, y: event.clientY, view };
      event.currentTarget.setPointerCapture?.(event.pointerId);
    },
    onPointerMove: event => {
      if (!drag.current) return;
      const { x, y, view: start } = drag.current;
      const size = { w: event.currentTarget.clientWidth, h: event.currentTarget.clientHeight };
      setView(clampPan({ ...start, x: start.x + event.clientX - x, y: start.y + event.clientY - y }, bounds, size));
    },
    onPointerUp: stop,
    onPointerCancel: stop,
    onKeyDown: event => {
      if (event.key === "+" || event.key === "=") { event.preventDefault(); zoomAboutCenter(1.2); }
      if (event.key === "-") { event.preventDefault(); zoomAboutCenter(1 / 1.2); }
      if (event.key === "0") { event.preventDefault(); fit(); }
    },
  };
  return { view, bind, fit, zoomBy, zoomAboutCenter, setView };
}
