// Geometry from a model: where every node, lane and column sits in world units. Pure, no DOM.
// Node sizes are fixed per kind, so layout never depends on fonts or text measurement.

import type { Model, Kind } from "./model.ts";
import type { Rect, Size } from "./viewport.ts";

export interface Placed extends Rect { id: string }
export interface Geometry {
  xs: number[];
  nodes: Record<string, Placed>;
  lanes: Record<string, Rect>;
  bounds: Rect;
  world: Size;
}
export interface LayoutOptions { pitch: number; top: number; gap: number; padX: number; visible: (id: string) => boolean }

export const DEFAULTS: LayoutOptions = { pitch: 62, top: 64, gap: 34, padX: 24, visible: () => true };

const HEIGHT: Record<Kind, number> = { card: 54, group: 54, gateway: 54, placeholder: 54, chip: 34, start: 40, end: 40, event: 40, note: 40 };
const LANE_PAD_TOP = 38; // room for the lane title
const LANE_PAD_BOTTOM = 14;

export function computeGeometry(m: Model, opt: Partial<LayoutOptions> = {}): Geometry {
  const o: LayoutOptions = { ...DEFAULTS, ...opt };
  const xs: number[] = [];
  let x = o.padX;
  for (const c of m.columns) { xs.push(x); x += c.width + o.gap; }
  const world: Size = { w: Math.max(1, x - o.gap + o.padX), h: 1 };

  const nodes: Record<string, Placed> = {};
  for (const n of m.nodes) {
    const h = HEIGHT[n.kind] ?? 54;
    const first = Math.min(Math.max(0, n.col), m.columns.length - 1);
    const last = Math.min(m.columns.length - 1, first + (n.colSpan ?? 1) - 1);
    const x0 = xs[first] ?? o.padX;
    const x1 = (xs[last] ?? x0) + (m.columns[last]?.width ?? 0);
    nodes[n.id] = { id: n.id, x: x0, y: o.top + 40 + n.row * o.pitch - h / 2, w: Math.max(1, x1 - x0), h };
  }

  const lanes: Record<string, Rect> = {};
  for (const l of m.lanes) {
    const mem = m.nodes.filter(n => n.lane === l.id && o.visible(n.id)).map(n => nodes[n.id]!);
    if (!mem.length) continue;
    const y1 = Math.min(...mem.map(p => p.y)) - LANE_PAD_TOP;
    const y2 = Math.max(...mem.map(p => p.y + p.h)) + LANE_PAD_BOTTOM;
    lanes[l.id] = { x: 8, y: y1, w: world.w - 16, h: y2 - y1 };
  }

  const all = Object.values(lanes);
  let bounds: Rect = { x: 0, y: 0, w: world.w, h: 1 };
  if (all.length) {
    const top = Math.min(...all.map(r => r.y));
    bounds = { x: 8, y: top, w: world.w - 16, h: Math.max(...all.map(r => r.y + r.h)) - top };
  }
  world.h = Math.max(1, bounds.y + bounds.h + 70);
  return { xs, nodes, lanes, bounds, world };
}
