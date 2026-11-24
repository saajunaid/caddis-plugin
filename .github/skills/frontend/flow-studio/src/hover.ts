// Hover and focus card on canvas nodes (WCAG 1.4.13: dismissable, hoverable, persistent).
// Built with textContent only, never innerHTML, and placed in the viewport so zoom never scales it.

import { el, on, type Ctx } from "./ctx.ts";
import type { NodeDef } from "./model.ts";
import type { Rect, Size } from "./viewport.ts";

export interface HoverPlacement {
  left: number;
  top: number;
  side: "below" | "above";
}

const GAP = 8;
const SHOW_MS = 150;
const HIDE_MS = 120;

let nextHoverId = 0;

/** Place the hover card in viewport-relative pixels: 8 px below the node, or above when below overflows. */
export function placeHover(node: Rect, vp: Rect, card: Size): HoverPlacement {
  const nx = node.x - vp.x;
  const ny = node.y - vp.y;
  const left = Math.max(GAP, Math.min(nx, vp.w - GAP - card.w));
  const belowTop = ny + node.h + GAP;
  if (belowTop + card.h > vp.h - GAP) {
    return { left, top: Math.max(GAP, ny - GAP - card.h), side: "above" };
  }
  return { left, top: Math.max(GAP, belowTop), side: "below" };
}

export function install(ctx: Ctx): void {
  const card = el("div", "fs-hovercard");
  const cardId = `fs-hover-${++nextHoverId}`;
  card.id = cardId;
  card.setAttribute("role", "tooltip");
  card.hidden = true;
  ctx.els.vp.appendChild(card);

  let showTimer = 0;
  let hideTimer = 0;
  let pendingNode: HTMLElement | null = null;
  let activeNode: HTMLElement | null = null;
  let pointerPress = false;

  function clearShow(): void {
    if (showTimer) { window.clearTimeout(showTimer); showTimer = 0; }
    pendingNode = null;
  }

  function clearHide(): void {
    if (hideTimer) { window.clearTimeout(hideTimer); hideTimer = 0; }
  }

  function hideCard(): boolean {
    clearHide();
    if (activeNode) {
      if (activeNode.getAttribute("aria-describedby") === cardId) activeNode.removeAttribute("aria-describedby");
      activeNode = null;
    }
    if (card.hidden) return false;
    card.hidden = true;
    return true;
  }

  function hideAll(): boolean {
    clearShow();
    return hideCard();
  }

  function hoverable(nodeEl: HTMLElement | null): { nodeEl: HTMLElement; def: NodeDef; lines: string[] } | null {
    if (!nodeEl || !nodeEl.isConnected || nodeEl.classList.contains("off")) return null;
    const id = nodeEl.id.startsWith("n_") ? nodeEl.id.slice(2) : "";
    const def = ctx.nodes.get(id);
    if (!def || !Array.isArray(def.hover) || def.hover.length === 0) return null;
    return { nodeEl, def, lines: def.hover };
  }

  function show(nodeEl: HTMLElement): void {
    clearShow();
    clearHide();
    const target = hoverable(nodeEl);
    if (!target) { hideCard(); return; }
    if (activeNode && activeNode !== target.nodeEl && activeNode.getAttribute("aria-describedby") === cardId) {
      activeNode.removeAttribute("aria-describedby");
    }
    card.replaceChildren();
    const title = el("b", "fs-hovercard-title");
    title.textContent = target.def.title;
    card.appendChild(title);
    for (const line of target.lines) {
      const row = el("div", "fs-hovercard-line");
      row.textContent = line;
      card.appendChild(row);
    }
    card.style.left = "0px";
    card.style.top = "0px";
    card.hidden = false;
    const nr = target.nodeEl.getBoundingClientRect();
    const vr = ctx.els.vp.getBoundingClientRect();
    const pos = placeHover(
      { x: nr.left, y: nr.top, w: nr.width, h: nr.height },
      { x: vr.left, y: vr.top, w: vr.width, h: vr.height },
      { w: card.offsetWidth, h: card.offsetHeight },
    );
    card.style.left = pos.left + "px";
    card.style.top = pos.top + "px";
    card.dataset.side = pos.side;
    activeNode = target.nodeEl;
    activeNode.setAttribute("aria-describedby", cardId);
  }

  on(ctx, ctx.els.world, "mouseenter", (e: MouseEvent) => {
    if (!(e.target instanceof HTMLElement) || !e.target.classList.contains("node")) return;
    const nodeEl = e.target;
    if (activeNode === nodeEl && !card.hidden) { clearHide(); return; }
    if (!hoverable(nodeEl)) { clearShow(); return; }
    clearShow();
    pendingNode = nodeEl;
    showTimer = window.setTimeout(() => { showTimer = 0; pendingNode = null; show(nodeEl); }, SHOW_MS);
  }, { capture: true });

  on(ctx, ctx.els.world, "mouseleave", (e: MouseEvent) => {
    if (!(e.target instanceof HTMLElement) || !e.target.classList.contains("node")) return;
    const nodeEl = e.target;
    if (pendingNode === nodeEl) clearShow();
    if (activeNode === nodeEl && !card.hidden) {
      clearHide();
      hideTimer = window.setTimeout(() => { hideTimer = 0; hideCard(); }, HIDE_MS);
    }
  }, { capture: true });

  on(ctx, card, "mouseenter", () => clearHide());
  on(ctx, card, "mouseleave", (e: MouseEvent) => {
    if (e.relatedTarget instanceof Node && activeNode?.contains(e.relatedTarget)) return;
    hideCard();
  });

  on(ctx, ctx.els.world, "focus", (e: FocusEvent) => {
    if (pointerPress) return;
    if (!(e.target instanceof HTMLElement) || !e.target.classList.contains("node")) return;
    if (!hoverable(e.target)) { hideAll(); return; }
    show(e.target);
  }, { capture: true });

  on(ctx, ctx.els.world, "blur", (e: FocusEvent) => {
    if (!(e.target instanceof HTMLElement) || !e.target.classList.contains("node")) return;
    if (activeNode === e.target || pendingNode === e.target) hideAll();
  }, { capture: true });

  on(ctx, ctx.els.world, "click", (e: MouseEvent) => {
    if ((e.target as Element | null)?.closest?.(".node")) hideAll();
  }, { capture: true });

  on(ctx, ctx.els.vp, "pointerdown", () => {
    pointerPress = true;
    window.setTimeout(() => { pointerPress = false; }, 0);
    hideAll();
  }, { capture: true });
  on(ctx, window, "pointerup", () => { pointerPress = false; });
  on(ctx, window, "pointercancel", () => { pointerPress = false; });
  on(ctx, ctx.els.vp, "wheel", () => { hideAll(); }, { capture: true, passive: true });

  const prevSelect = ctx.fn.select;
  ctx.fn.select = (id: string | null) => { hideAll(); prevSelect(id); };
  const prevPaint = ctx.fn.paint;
  ctx.fn.paint = (fromSwitch?: boolean) => { hideAll(); prevPaint(fromSwitch); };
  ctx.fn.hideHover = hideAll;

  ctx.disposers.push(() => {
    hideAll();
    card.remove();
  });
}
