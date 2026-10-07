// Small bar charts on a node, one bar per key (a day, a step). Hovering a bar marks the same key on
// every chart on the canvas, so a reader can ask "was this day bad everywhere?". The key is opaque:
// the model decides what it means. Pure string rendering plus one tiny DOM helper, no layout maths.

import type { Ctx } from "./ctx.ts";
import { on } from "./ctx.ts";
import { esc, type NodeBar } from "./model.ts";

const BAR_UNIT = 4; // viewBox units per bar; the chart is stretched to the node's width by CSS

/** The chart as an SVG string, or "" when the node has no bars. A null value is a missing key: a red tick, never a zero bar. */
export function barsHtml(bars: NodeBar[] | undefined, height = 22): string {
  if (!bars || bars.length === 0) return "";
  const width = bars.length * BAR_UNIT;
  const max = Math.max(1, ...bars.map(b => b.value ?? 0));
  const lastWithData = bars.map(b => b.value !== null).lastIndexOf(true);
  const rects = bars.map((b, i) => {
    const x = i * BAR_UNIT;
    const w = BAR_UNIT - 1;
    const label = esc(b.label ?? (b.value === null ? `${b.key}: no data` : `${b.key}: ${b.value}`));
    if (b.value === null) {
      return `<rect class="miss" data-key="${esc(b.key)}" x="${x}" y="${height - 4}" width="${w}" height="4"><title>${label}</title></rect>`;
    }
    const h = Math.max(1, (b.value / max) * (height - 5));
    const cls = b.kind === "low" ? "low" : i === lastWithData ? "last" : "";
    return `<rect${cls ? ` class="${cls}"` : ""} data-key="${esc(b.key)}" x="${x}" y="${height - h}" width="${w}" height="${h}"><title>${label}</title></rect>`;
  });
  const first = esc(bars[0]!.key), last = esc(bars[bars.length - 1]!.key);
  return `<svg class="bars" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="Bars, ${first} to ${last}">${rects.join("")}</svg>`;
}

/** Mark every bar with this key, on every chart under root, and clear the rest. null clears all. */
export function markKey(root: ParentNode, key: string | null): void {
  for (const r of Array.from(root.querySelectorAll("rect[data-key]"))) {
    if (key !== null && r.getAttribute("data-key") === key) r.setAttribute("data-hl", "true");
    else r.removeAttribute("data-hl");
  }
}

/** Hovering a bar marks its key everywhere and tells the host page; leaving the canvas clears it. */
export function installBars(ctx: Ctx): void {
  const set = (key: string | null): void => {
    if (ctx.hoverKey === key) return;
    ctx.hoverKey = key;
    markKey(ctx.els.world, key);
    ctx.onHoverKey?.(key);
  };
  on(ctx, ctx.els.world, "mouseover", (e: MouseEvent) => {
    const bar = (e.target as Element | null)?.closest?.("rect[data-key]");
    set(bar ? bar.getAttribute("data-key") : null);
  });
  on(ctx, ctx.els.world, "mouseleave", () => set(null));
}
