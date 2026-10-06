// View rules: which nodes and links show in which view, and in which state. Pure, no DOM.
// A model may define views (for example "Today" and "Complete"). The first view is the baseline.
// A model with no views has one implicit view named "all".

import type { Model, NodeDef, LinkDef, Bucket } from "./model.ts";

export const baselineView = (m: Model): string => m.views?.[0]?.id ?? "all";
export const defaultView = (m: Model): string => (m.views?.find(v => v.default) ?? m.views?.[0])?.id ?? "all";

/** A group that contains nodes starts folded unless it explicitly opts out. */
export const initialCollapsed = (m: Model): Set<string> => new Set(m.nodes
  .filter(n => n.kind === "group" && n.contains && n.collapsed !== false).map(n => n.id));
export const columnTitle = (m: Model, n: NodeDef): string => n.col === undefined ? "" : m.columns[n.col]?.title ?? "";

export function groupFor(m: Model, nodeId: string): NodeDef | undefined {
  return m.nodes.find(n => n.kind === "group" && n.contains?.includes(nodeId));
}

export const nodeVisible = (m: Model, view: string, n: NodeDef, collapsed?: Set<string>): boolean => {
  if (n.visibleIn && !n.visibleIn.includes(view)) return false;
  if (!collapsed) return true;
  if (n.kind === "group" && n.contains) return collapsed.has(n.id);
  const owner = groupFor(m, n.id);
  return !owner || !collapsed.has(owner.id);
};
export function toggleGroupState(m: Model, view: string, collapsed: Set<string>, id: string):
  { collapsed: Set<string>; selected: string | null; expanding: boolean } | null {
  const group = m.nodes.find(n => n.id === id && n.kind === "group" && n.contains?.length);
  if (!group) return null;
  const next = new Set(collapsed);
  const expanding = next.has(id);
  if (expanding) next.delete(id); else next.add(id);
  const selected = expanding ? group.contains?.find(child => {
    const n = m.nodes.find(candidate => candidate.id === child);
    return !!n && nodeVisible(m, view, n, next);
  }) ?? null : id;
  return { collapsed: next, selected, expanding };
}
export const nodeStateId = (_m: Model, view: string, n: NodeDef): string => n.stateIn?.[view] ?? n.state;

export function linkVisible(m: Model, view: string, l: LinkDef, nodes: Map<string, NodeDef>): boolean {
  if (l.visibleIn && !l.visibleIn.includes(view)) return false;
  const a = nodes.get(l.from);
  const b = nodes.get(l.to);
  return !!a && !!b && nodeVisible(m, view, a) && nodeVisible(m, view, b);
}
export const linkStateId = (_m: Model, view: string, l: LinkDef): string => l.stateIn?.[view] ?? l.state;

/** An unknown state counts as a gap: a typo must never read as "good". */
export const bucketOf = (m: Model, stateId: string): Bucket => m.states[stateId]?.bucket ?? "gap";

/** Visible now, but not in the baseline view: the view adds this node. */
export const isNew = (m: Model, view: string, n: NodeDef): boolean =>
  view !== baselineView(m) && nodeVisible(m, view, n) && !nodeVisible(m, baselineView(m), n);

/** A gap in the baseline view that this view has filled. */
export const isImproved = (m: Model, view: string, n: NodeDef): boolean => {
  const base = baselineView(m);
  return view !== base && nodeVisible(m, base, n) && bucketOf(m, nodeStateId(m, base, n)) === "gap" && bucketOf(m, nodeStateId(m, view, n)) !== "gap";
};

/** A portal chip is an alias of the node it points at. */
export const canonOf = (nodes: Map<string, NodeDef>, id: string): string => nodes.get(id)?.ref ?? id;

/** Map hidden members to their visible group and merge parallel effective links. */
export function effectiveLinks(m: Model, view: string, collapsed: Set<string>, nodes: Map<string, NodeDef>): LinkDef[] {
  const byPair = new Map<string, LinkDef>();
  const rank = { good: 0, neutral: 1, gap: 2 };
  for (const link of m.links) {
    if (link.visibleIn && !link.visibleIn.includes(view)) continue;
    const a = nodes.get(link.from), b = nodes.get(link.to);
    if (!a || !b || (a.visibleIn && !a.visibleIn.includes(view)) || (b.visibleIn && !b.visibleIn.includes(view))) continue;
    const groupA = groupFor(m, a.id), groupB = groupFor(m, b.id);
    const from = groupA && collapsed.has(groupA.id) ? groupA.id : a.id;
    const to = groupB && collapsed.has(groupB.id) ? groupB.id : b.id;
    if (from === to) continue;
    const fromNode = nodes.get(from), toNode = nodes.get(to);
    if (!fromNode || !toNode || !nodeVisible(m, view, fromNode, collapsed) || !nodeVisible(m, view, toNode, collapsed)) continue;
    const state = linkStateId(m, view, link);
    const key = JSON.stringify([from, to]);
    const prev = byPair.get(key);
    if (!prev) byPair.set(key, { ...link, from, to, state, stateIn: undefined });
    else if (rank[bucketOf(m, state)] > rank[bucketOf(m, prev.state)]) prev.state = state;
  }
  return [...byPair.values()];
}
