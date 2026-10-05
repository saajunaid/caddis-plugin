// View maths for the pan and zoom canvas. Pure functions, no DOM. The world is moved with
// transform: translate(x, y) scale(k); a world point (wx, wy) is at screen (x + wx * k, y + wy * k).

export interface View { x: number; y: number; k: number }
export interface Rect { x: number; y: number; w: number; h: number }
export interface Size { w: number; h: number }

export const K_MIN = 0.25;
export const K_MAX = 2.5;

export const clampK = (k: number): number => (Number.isFinite(k) ? Math.min(K_MAX, Math.max(K_MIN, k)) : 1);

/** Zoom by a factor and keep the world point under (cx, cy) fixed. */
export function zoomAt(v: View, factor: number, cx: number, cy: number): View {
  const base = Number.isFinite(v.k) && v.k > 0 ? v.k : 1;
  const k = clampK(base * factor);
  const r = k / base;
  return { k, x: cx - (cx - v.x) * r, y: cy - (cy - v.y) * r };
}

/** Fit a world rectangle into the viewport. Never enlarges above 1. `top` reserves room for pinned headers. */
export function fitRect(rect: Rect, size: Size, pad: number, top: number): View {
  if (!(rect.w > 0 && rect.h > 0)) return { x: 0, y: 0, k: 1 };
  const aw = Math.max(1, size.w - 2 * pad);
  const ah = Math.max(1, size.h - 2 * pad - top);
  const k = Math.min(1, clampK(Math.min(aw / rect.w, ah / rect.h)));
  return { k, x: pad + (aw - rect.w * k) / 2 - rect.x * k, y: pad + top + (ah - rect.h * k) / 2 - rect.y * k };
}

/** Fit the width and start at the top: the readable first view. */
export function fitWidth(rect: Rect, size: Size, pad: number, top: number): View {
  if (!(rect.w > 0)) return { x: 0, y: 0, k: 1 };
  const k = Math.min(1, clampK((Math.max(1, size.w) - 2 * pad) / rect.w));
  return { k, x: pad - rect.x * k, y: top - rect.y * k };
}

/** Keep at least 80 px of the graph on screen so the reader cannot lose it. */
export function clampPan(v: View, bounds: Rect, size: Size): View {
  const keep = 80;
  const minX = keep - (bounds.x + bounds.w) * v.k;
  const maxX = size.w - keep - bounds.x * v.k;
  const minY = keep - (bounds.y + bounds.h) * v.k;
  const maxY = size.h - keep - bounds.y * v.k;
  return { k: v.k, x: Math.min(maxX, Math.max(minX, v.x)), y: Math.min(maxY, Math.max(minY, v.y)) };
}
