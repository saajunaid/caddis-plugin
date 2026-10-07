// Geometry from a model: where every node, lane and column sits in world units. Pure, no DOM.
// Node sizes are fixed per kind, so layout never depends on fonts or text measurement.

import { NODE_HEIGHT, type Model } from "./model.ts";
import type { Rect, Size } from "./viewport.ts";

export interface Placed extends Rect { id: string }
export interface Geometry {
  xs: number[];
  nodes: Record<string, Placed>;
  lanes: Record<string, Rect>;
  loops: Record<string, { channelY: number }>;
  bounds: Rect;
  world: Size;
}
export interface LayoutOptions { pitch: number; top: number; gap: number; padX: number; visible: (id: string) => boolean }

export const DEFAULTS: LayoutOptions = { pitch: 62, top: 64, gap: 34, padX: 24, visible: () => true };

const BARS_EXTRA = 26; // room for the bar chart under a node's text
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
    const h = (NODE_HEIGHT[n.kind] ?? 54) + (n.bars?.length ? BARS_EXTRA : 0);
    if (m.layout === "free") {
      nodes[n.id] = { id: n.id, x: n.x ?? 0, y: n.y ?? 0, w: n.w ?? 190, h: n.h ?? h };
      continue;
    }
    const first = Math.min(Math.max(0, n.col ?? 0), m.columns.length - 1);
    const last = Math.min(m.columns.length - 1, first + (n.colSpan ?? 1) - 1);
    const x0 = xs[first] ?? o.padX;
    const x1 = (xs[last] ?? x0) + (m.columns[last]?.width ?? 0);
    nodes[n.id] = { id: n.id, x: x0, y: o.top + 40 + (n.row ?? 0) * o.pitch - h / 2, w: Math.max(1, x1 - x0), h };
  }
  if (m.layout === "free") world.w = Math.max(world.w, ...Object.values(nodes).map(p => p.x + p.w + o.padX), 1);

  const loops: Geometry["loops"] = {};
  const lanes: Record<string, Rect> = {};
  const visibleMembers = (id: string) => m.nodes.filter(n => n.lane === id && o.visible(n.id)).map(n => nodes[n.id]!);
  const ordered = m.lanes.map(l => ({ l, mem: visibleMembers(l.id) })).filter(x => x.mem.length)
    .sort((a, b) => Math.min(...a.mem.map(p => p.y)) - Math.min(...b.mem.map(p => p.y)));
  let previousBottom = -Infinity;
  for (const { l, mem } of ordered) {
    const top = Math.min(...mem.map(p => p.y)) - LANE_PAD_TOP;
    const shift = m.layout === "free" ? 0 : Math.max(0, previousBottom + 8 - top);
    if (shift) for (const p of mem) p.y += shift;
    const y1 = top + shift;
    const laneNodeIds = new Set(mem.map(p => p.id));
    // Reserve channel space before shifting the following lane. The exact channel
    // positions are calculated only after every lane has reached its final y.
    const possibleLoops = m.links.filter(link => link.kind === "loop-back" && o.visible(link.from) && o.visible(link.to)
      && (laneNodeIds.has(link.from) || laneNodeIds.has(link.to))).length;
    const bottom = Math.max(...mem.map(p => p.y + p.h));
    const y2 = bottom + (possibleLoops ? 10 + 8 * (possibleLoops - 1) : 0) + LANE_PAD_BOTTOM;
    lanes[l.id] = { x: 8, y: y1, w: world.w - 16, h: y2 - y1 };
    previousBottom = y2;
  }

  const channelCounts = new Map<string, number>();
  for (const link of m.links) {
    if (link.kind !== "loop-back" || !o.visible(link.from) || !o.visible(link.to)) continue;
    const a = nodes[link.from], b = nodes[link.to];
    if (!a || !b) continue;
    const lower = a.y + a.h >= b.y + b.h ? a : b;
    const laneId = m.nodes.find(n => n.id === lower.id)?.lane;
    if (!laneId || !lanes[laneId]) continue;
    const left = Math.min(a.x + a.w / 2, b.x + b.w / 2);
    const right = Math.max(a.x + a.w / 2, b.x + b.w / 2);
    const laneMembers = visibleMembers(laneId);
    const crossed = laneMembers.filter(p => p.x < right && p.x + p.w > left);
    const lowestBottom = Math.max(a.y + a.h, b.y + b.h, ...crossed.map(p => p.y + p.h));
    const index = channelCounts.get(laneId) ?? 0;
    loops[link.id] = { channelY: lowestBottom + 10 + 8 * index };
    channelCounts.set(laneId, index + 1);
    const lane = lanes[laneId];
    lane.h = Math.max(lane.h, loops[link.id]!.channelY + LANE_PAD_BOTTOM - lane.y);
  }

  const all = Object.values(lanes);
  let bounds: Rect = { x: 0, y: 0, w: world.w, h: 1 };
  if (all.length) {
    const top = Math.min(...all.map(r => r.y));
    bounds = { x: 8, y: top, w: world.w - 16, h: Math.max(...all.map(r => r.y + r.h)) - top };
  }
  world.h = Math.max(1, bounds.y + bounds.h + 70);
  return { xs, nodes, lanes, loops, bounds, world };
}
