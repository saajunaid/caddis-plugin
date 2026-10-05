// View rules: which nodes and links show in which view, and in which state. Pure, no DOM.
// A model may define views (for example "Today" and "Complete"). The first view is the baseline.
// A model with no views has one implicit view named "all".

import type { Model, NodeDef, LinkDef, Bucket } from "./model.ts";

export const baselineView = (m: Model): string => m.views?.[0]?.id ?? "all";
export const defaultView = (m: Model): string => (m.views?.find(v => v.default) ?? m.views?.[0])?.id ?? "all";

export const nodeVisible = (_m: Model, view: string, n: NodeDef): boolean => !n.visibleIn || n.visibleIn.includes(view);
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
