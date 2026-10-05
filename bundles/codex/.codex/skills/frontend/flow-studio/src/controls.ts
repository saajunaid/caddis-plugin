// The canvas controls: view (pan and zoom), pinned headers, pointer, wheel, pinch, keys and the tool strip.
// The maths lives in viewport.ts; this file only reads and writes the DOM.

import { on, el, type Ctx } from "./ctx.ts";
import { clampPan, fitRect, fitWidth, zoomAt, type Rect, type View } from "./viewport.ts";

const HEAD = 44; // height of the pinned header overlay

const ICON: Record<string, string> = {
  select: '<path d="M5 3l12 6.5-5.2 1.6L9.5 17z"/>',
  hand: '<path d="M8 11V5.5a1.5 1.5 0 013 0V10m0-5a1.5 1.5 0 013 0v5m0-3.5a1.5 1.5 0 013 0V13c0 4-2.5 7-6.5 7S5 17 5 14l-1.6-3.2a1.4 1.4 0 012.4-1.4L8 12"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  minus: '<path d="M5 12h14"/>',
  fit: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
  one: '<path d="M9 8l3-2v12"/><path d="M5 20h14"/>',
  sel: '<circle cx="12" cy="12" r="3.2"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3"/>',
  full: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
};

export function install(ctx: Ctx): void {
  const { els, model } = ctx;
  const vp = els.vp;
  // The size is cached: reading clientWidth on every wheel event would force a layout of the whole page each time.
  let cached = { w: vp.clientWidth, h: vp.clientHeight };
  const size = () => cached;
  // Same for the viewport rectangle: it is refreshed on resize, scroll and when the pointer enters.
  let vpRect = vp.getBoundingClientRect();
  const refreshRect = () => { vpRect = vp.getBoundingClientRect(); };
  let animTimer = 0;
  let raf = 0;

  function applyView(): void {
    const v = ctx.view;
    els.world.style.transform = `translate(${v.x}px,${v.y}px) scale(${v.k})`;
    vp.style.setProperty("--inv", Math.max(1, 0.9 / v.k).toFixed(3));
    vp.style.setProperty("--k", v.k.toFixed(4));
    vp.classList.toggle("lod1", v.k < 0.62);
    vp.classList.toggle("lod2", v.k < 0.4);
    els.zoom.textContent = Math.round(v.k * 100) + "%";
    ctx.fn.stickLabels();
    ctx.fn.placeHeaders();
    if (!raf) raf = requestAnimationFrame(() => { raf = 0; if (document.body.classList.contains("notes")) ctx.fn.placeMarkers(); });
  }

  function setView(v: View, animate = false): void {
    const c = clampPan(v, ctx.geom.bounds, size());
    ctx.view = [c.x, c.y, c.k].every(Number.isFinite) ? c : { x: 0, y: 0, k: 1 };
    const glide = animate && !ctx.reduced;
    vp.classList.toggle("anim", glide);
    if (glide) { clearTimeout(animTimer); animTimer = window.setTimeout(() => vp.classList.remove("anim"), 330); }
    applyView();
  }

  function fit(animate = false, rect?: Rect, inset = 0): void {
    const r = rect ?? ctx.geom.bounds;
    if (!(r.w > 0)) return;
    const s = size();
    setView(fitRect(r, { w: s.w - inset, h: s.h }, 28, HEAD + 8), animate);
  }
  function fitW(animate = false): void {
    setView(fitWidth(ctx.geom.bounds, size(), 28, HEAD + 8), animate);
  }
  function zoomBy(f: number): void {
    const s = size();
    ctx.userMoved = true;
    setView(zoomAt(ctx.view, f, s.w / 2, s.h / 2), true);
    ctx.fn.announce("Zoom " + Math.round(ctx.view.k * 100) + " percent");
  }

  function placeHeaders(): void {
    const cols = els.cols;
    if (!cols.firstChild) {
      model.columns.forEach((c, i) => { const h = el("div", "hd"); h.textContent = (c.short ?? c.title).toUpperCase(); h.title = c.title; h.dataset.i = String(i); cols.appendChild(h); });
      let i = 0;
      while (i < model.columns.length) {
        const name = model.columns[i]?.phase;
        let j = i;
        while (j + 1 < model.columns.length && model.columns[j + 1]?.phase === name) j++;
        if (name) { const p = el("div", "ph"); p.innerHTML = "<span></span><i></i>"; (p.firstElementChild as HTMLElement).textContent = name; p.dataset.a = String(i); p.dataset.b = String(j); cols.appendChild(p); }
        i = j + 1;
      }
    }
    const v = ctx.view, xs = ctx.geom.xs;
    cols.querySelectorAll<HTMLElement>(".hd").forEach(h => { const i = +(h.dataset.i ?? 0); h.style.left = v.x + (xs[i] ?? 0) * v.k + "px"; h.style.width = Math.max(0, (model.columns[i]?.width ?? 0) * v.k - 6) + "px"; });
    cols.querySelectorAll<HTMLElement>(".ph").forEach(p => {
      const a = +(p.dataset.a ?? 0), b = +(p.dataset.b ?? 0);
      p.style.left = v.x + (xs[a] ?? 0) * v.k + "px";
      p.style.width = Math.max(40, ((xs[b] ?? 0) + (model.columns[b]?.width ?? 0) - (xs[a] ?? 0)) * v.k) + "px";
    });
  }

  function stickLabels(): void {
    const wl = (52 - ctx.view.x) / ctx.view.k;
    for (const l of model.lanes) {
      const r = ctx.geom.lanes[l.id], d = ctx.laneEls.get(l.id);
      if (!r || !d?.firstElementChild) continue;
      (d.firstElementChild as HTMLElement).style.left = Math.min(Math.max(12, wl - r.x), Math.max(12, r.w - 300)) + "px";
    }
  }

  // ---- pointer: drag the background (or any spot with the hand tool, Space, or the middle button) to pan; pinch to zoom
  const pointers = new Map<number, { x: number; y: number }>();
  let drag: { x: number; y: number; vx: number; vy: number } | null = null;
  let pinch: { d: number; view: View } | null = null;

  on(ctx, vp, "pointerdown", (e: PointerEvent) => {
    if ((e.target as HTMLElement).closest("#tools, .bandlabel")) return;
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    ctx.moved = 0;
    if (pointers.size === 2) {
      const [a, b] = [...pointers.values()] as [{ x: number; y: number }, { x: number; y: number }];
      pinch = { d: Math.hypot(a.x - b.x, a.y - b.y), view: { ...ctx.view } };
      drag = null;
      return;
    }
    const onNode = !!(e.target as HTMLElement).closest(".node");
    if (e.button === 1 || ctx.tool === "hand" || ctx.spaceDown || !onNode) {
      drag = { x: e.clientX, y: e.clientY, vx: ctx.view.x, vy: ctx.view.y };
      try { vp.setPointerCapture(e.pointerId); } catch { /* a synthetic pointer cannot be captured */ }
      vp.classList.add("panning");
      if (e.button === 1) e.preventDefault();
    }
  });
  on(ctx, vp, "pointermove", (e: PointerEvent) => {
    if (pointers.has(e.pointerId)) pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pinch && pointers.size === 2) {
      const [a, b] = [...pointers.values()] as [{ x: number; y: number }, { x: number; y: number }];
      const d = Math.hypot(a.x - b.x, a.y - b.y), r = vpRect;
      ctx.userMoved = true;
      setView(zoomAt(pinch.view, d / pinch.d, (a.x + b.x) / 2 - r.left, (a.y + b.y) / 2 - r.top), false);
      return;
    }
    if (!drag) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    ctx.moved = Math.max(ctx.moved, Math.hypot(dx, dy));
    if (ctx.moved > 4) { ctx.userMoved = true; setView({ k: ctx.view.k, x: drag.vx + dx, y: drag.vy + dy }, false); }
  });
  const endDrag = (e: PointerEvent) => {
    pointers.delete(e.pointerId);
    if (pointers.size < 2) pinch = null;
    if (drag) {
      drag = null;
      vp.classList.remove("panning");
      try { vp.releasePointerCapture(e.pointerId); } catch { /* not captured */ }
      window.setTimeout(() => { ctx.moved = 0; }, 0);
    }
  };
  on(ctx, vp, "pointerup", endDrag);
  on(ctx, vp, "pointercancel", endDrag);
  on(ctx, vp, "wheel", (e: WheelEvent) => {
    e.preventDefault();
    const r = vpRect, unit = e.deltaMode === 1 ? 16 : 1;
    ctx.userMoved = true;
    setView(zoomAt(ctx.view, Math.exp(-e.deltaY * unit * (e.ctrlKey ? 0.01 : 0.0012)), e.clientX - r.left, e.clientY - r.top), false);
  }, { passive: false });
  on(ctx, vp, "dblclick", (e: MouseEvent) => { if (!(e.target as HTMLElement).closest(".node, .bandlabel, #tools")) { ctx.userMoved = false; fit(true); } });
  on(ctx, vp, "click", (e: MouseEvent) => { if (!(e.target as HTMLElement).closest(".node, .bandlabel, #tools") && ctx.moved <= 4) ctx.fn.select(null); });

  const ro = new ResizeObserver(() => { cached = { w: vp.clientWidth, h: vp.clientHeight }; refreshRect(); if (!ctx.userMoved) fitW(false); else setView(ctx.view, false); });
  ro.observe(vp);
  on(ctx, vp, "pointerenter", refreshRect);
  on(ctx, window, "scroll", refreshRect, { passive: true });
  ctx.disposers.push(() => ro.disconnect());

  // ---- tools
  function setTool(id: "select" | "hand"): void {
    ctx.tool = id;
    vp.classList.toggle("hand", id === "hand");
    els.tools.querySelectorAll<HTMLElement>("[data-id='select'], [data-id='hand']").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.id === id)));
    ctx.fn.announce(id === "hand" ? "Hand tool: drag to pan" : "Select tool");
  }
  function toggleFull(): void {
    const ws = els.workspace;
    if (document.fullscreenElement) void document.exitFullscreen();
    else if (ws.requestFullscreen) ws.requestFullscreen().catch(() => ws.classList.toggle("fs"));
    else ws.classList.toggle("fs");
  }
  type Tool = [string, string, "tool" | "full" | (() => void)] | ["-"];
  const TOOLS: Tool[] = [
    ["select", "Select (V)", "tool"], ["hand", "Hand: drag to pan (H)", "tool"], ["-"],
    ["plus", "Zoom in (+)", () => zoomBy(1.25)], ["minus", "Zoom out (-)", () => zoomBy(1 / 1.25)],
    ["fit", "Fit to screen (0)", () => { ctx.userMoved = false; fit(true); ctx.fn.announce("Fit to screen"); }],
    ["one", "Actual size (1)", () => { const s = size(); ctx.userMoved = true; setView(zoomAt(ctx.view, 1 / ctx.view.k, s.w / 2, s.h / 2), true); }],
    ["sel", "Zoom to selection (F)", () => ctx.fn.zoomToPath()], ["-"],
    ["full", "Fullscreen", "full"],
  ];
  els.tools.innerHTML = "";
  for (const t of TOOLS) {
    if (t[0] === "-") { els.tools.appendChild(el("div", "sep")); continue; }
    const [id, label, act] = t as [string, string, "tool" | "full" | (() => void)];
    const b = el("button", "tb", `<svg viewBox="0 0 24 24" aria-hidden="true">${ICON[id] ?? ""}</svg>`);
    b.type = "button"; b.title = label; b.setAttribute("aria-label", label); b.dataset.id = id;
    if (act === "tool") { b.setAttribute("aria-pressed", String(ctx.tool === id)); on(ctx, b, "click", () => setTool(id as "select" | "hand")); }
    else if (act === "full") on(ctx, b, "click", toggleFull);
    else on(ctx, b, "click", act);
    els.tools.appendChild(b);
  }
  requestAnimationFrame(() => { const r = els.tools.getBoundingClientRect(), v = vp.getBoundingClientRect(); els.zoom.style.top = r.bottom - v.top + 6 + "px"; });
  on(ctx, document, "fullscreenchange", () => window.setTimeout(() => { if (!ctx.userMoved) fitW(false); }, 60));

  // ---- keys
  on(ctx, document, "keydown", (e: KeyboardEvent) => {
    const typing = !!e.target && /INPUT|TEXTAREA/.test((e.target as HTMLElement).tagName);
    if (typing) { if (e.key === "Escape") (e.target as HTMLElement).blur(); return; }
    if (e.ctrlKey || e.metaKey || e.altKey) return; // never hijack Ctrl+F, Ctrl+N, Ctrl+plus and the like
    if (e.key === " " && document.activeElement === vp) { ctx.spaceDown = true; e.preventDefault(); vp.classList.add("hand"); return; }
    const k = e.key, step = e.shiftKey ? 240 : 60;
    if (k === "/") { e.preventDefault(); els.q.focus(); }
    else if (k === "n" || k === "N") ctx.fn.toggleNotes();
    else if (k === "v" || k === "V") setTool("select");
    else if (k === "h" || k === "H") setTool("hand");
    else if (k === "+" || k === "=") zoomBy(1.25);
    else if (k === "-" || k === "_") zoomBy(1 / 1.25);
    else if (k === "0") { ctx.userMoved = false; fit(true); }
    else if (k === "1") { const s = size(); ctx.userMoved = true; setView(zoomAt(ctx.view, 1 / ctx.view.k, s.w / 2, s.h / 2), true); }
    else if (k === "f" || k === "F") ctx.fn.zoomToPath();
    else if (k.startsWith("Arrow") && (document.activeElement === vp || document.activeElement === document.body)) {
      e.preventDefault();
      ctx.userMoved = true;
      setView({ k: ctx.view.k, x: ctx.view.x + (k === "ArrowLeft" ? step : k === "ArrowRight" ? -step : 0), y: ctx.view.y + (k === "ArrowUp" ? step : k === "ArrowDown" ? -step : 0) }, false);
    } else if (k === "Escape") ctx.fn.escape();
  });
  on(ctx, document, "keyup", (e: KeyboardEvent) => { if (e.key === " ") { ctx.spaceDown = false; if (ctx.tool !== "hand") vp.classList.remove("hand"); } });

  ctx.fn.setView = setView;
  ctx.fn.fit = fit;
  ctx.fn.fitWidth = fitW;
  ctx.fn.zoomBy = zoomBy;
  ctx.fn.stickLabels = stickLabels;
  ctx.fn.placeHeaders = placeHeaders;
}
