// Interaction: tracing a path, selecting, the draw-in trail, the what-if action, zooming to a path or lane.

import type { Ctx } from "./ctx.ts";
import type { NodeDef, RelationDef } from "./model.ts";
import type { Rect } from "./viewport.ts";
import { connected, relatives, withinHops, type Edge } from "./trace.ts";
import { bucketOf, canonOf, effectiveLinks, nodeStateId, nodeVisible, toggleGroupState } from "./rules.ts";
import { notifySelection } from "./selection.ts";

export function relationsOf(ctx: Ctx): RelationDef[] {
  const given = ctx.model.inspector?.relations;
  if (given && given.length) return given;
  const last = Math.max(0, ctx.model.columns.length - 1);
  return [
    { id: "up", label: "Upstream", dir: "up" },
    { id: "down", label: "Downstream", dir: "down" },
    { id: "end", label: "At the end", dir: "down", filter: { col: last } },
  ];
}

export function visibleEdges(ctx: Ctx): Edge[] {
  return effectiveLinks(ctx.model, ctx.mode, ctx.collapsed, ctx.nodes).map(l => ({ from: l.from, to: l.to }));
}

export function relationSet(ctx: Ctx, rel: RelationDef, start: string): Set<string> {
  const canon = (id: string) => canonOf(ctx.nodes, id);
  const set = relatives(visibleEdges(ctx), canon, start, rel.dir);
  if (!rel.filter) return set;
  const out = new Set<string>([canon(start)]);
  for (const id of set) {
    const n = ctx.nodes.get(id);
    if (!n) continue;
    if ((rel.filter.col === undefined || n.col === rel.filter.col) && (rel.filter.kind === undefined || n.kind === rel.filter.kind)) out.add(id);
  }
  return out;
}

export function matches(ctx: Ctx, n: NodeDef): boolean {
  const q = ctx.query;
  return !!q && (n.title.toLowerCase().includes(q) || (n.members ?? []).some(m => m.toLowerCase().includes(q)));
}

export function install(ctx: Ctx): void {
  const { els, model } = ctx;
  const canon = (id: string) => canonOf(ctx.nodes, id);
  const visibleNodes = () => model.nodes.filter(n => nodeVisible(model, ctx.mode, n, ctx.collapsed));
  const inspInset = () => (els.inspector.classList.contains("open") ? 340 : 0);

  function activeSet(id: string | null): Set<string> | null {
    const edges = visibleEdges(ctx);
    if (id) {
      if (id === ctx.selected && ctx.hl) {
        const rel = relationsOf(ctx).find(r => r.id === ctx.hl);
        if (rel) return relationSet(ctx, rel, id);
      }
      return connected(edges, canon, id);
    }
    if (ctx.filter) {
      return new Set(visibleNodes().filter(n => {
        const b = bucketOf(model, nodeStateId(model, ctx.mode, n));
        return ctx.filter === "gap" ? b === "gap" : !!n.upgrade && b !== "good";
      }).map(n => canon(n.id)));
    }
    if (ctx.query) return withinHops(edges, canon, visibleNodes().filter(n => matches(ctx, n)).map(n => n.id), ctx.hops);
    return null;
  }

  function trace(id: string | null): void {
    const set = activeSet(id);
    const lit = !!id && !!set;
    for (const n of model.nodes) {
      const d = ctx.nodeEls.get(n.id);
      if (!d) continue;
      d.classList.toggle("dim", !!set && !set.has(canon(n.id)));
      d.classList.toggle("lit", lit && !!set && set.has(canon(n.id)));
    }
    ctx.edgeEls.forEach(p => {
      if (!p) return;
      const inSet = !!set && set.has(canon(p.dataset.a ?? "")) && set.has(canon(p.dataset.b ?? ""));
      p.classList.toggle("dim", !!set && !inSet);
      p.classList.toggle("hot", lit && inSet);
    });
    ctx.labelEls.forEach(l => { if (l) l.classList.toggle("show", lit && !!set && set.has(canon(l.dataset.a ?? "")) && set.has(canon(l.dataset.b ?? ""))); });
  }

  function select(id: string | null): void {
    clearSim();
    const previous = ctx.selected;
    ctx.selected = id ? canon(id) : null;
    ctx.hl = null;
    ctx.dismissed = false;
    for (const n of model.nodes) ctx.nodeEls.get(n.id)?.classList.toggle("sel", !!ctx.selected && canon(n.id) === ctx.selected);
    trace(ctx.selected);
    ctx.fn.renderInspector();
    drawTrail();
    if (ctx.selected) revealNode(ctx.selected);
    notifySelection(previous, ctx.selected, ctx.onSelect);
  }

  /** An overlay is a copy of one link drawn on top. pathLength=1 makes the draw-in independent of zoom. */
  function overlay(edge: SVGPathElement, cls: string, delay: number, dur: number): SVGPathElement {
    const o = edge.cloneNode(false) as SVGPathElement;
    o.setAttribute("class", cls);
    o.setAttribute("pathLength", "1");
    o.removeAttribute("data-i");
    els.layer.appendChild(o);
    ctx.overlays.push(o);
    if (ctx.reduced) return o;
    o.style.strokeDasharray = "1 1";
    o.style.strokeDashoffset = "1";
    o.getBoundingClientRect();
    o.style.transition = `stroke-dashoffset ${dur}s ${delay}s ease-out`;
    o.style.strokeDashoffset = "0";
    return o;
  }
  function dropOverlays(cls: string): void {
    ctx.overlays.filter(o => o.classList.contains(cls)).forEach(o => o.remove());
    ctx.overlays = ctx.overlays.filter(o => o.isConnected);
  }
  function drawTrail(): void {
    dropOverlays("trail");
    if (!ctx.selected || ctx.reduced) return;
    const set = connected(visibleEdges(ctx), canon, ctx.selected);
    const c0 = ctx.nodes.get(ctx.selected)?.col ?? 0;
    for (const p of ctx.edgeEls) {
      if (!p || p.classList.contains("off")) continue;
      const a = canon(p.dataset.a ?? ""), b = canon(p.dataset.b ?? "");
      if (!(set.has(a) && set.has(b))) continue;
      const delay = Math.min(Math.abs((ctx.nodes.get(a)?.col ?? 0) - c0), Math.abs((ctx.nodes.get(b)?.col ?? 0) - c0)) * 0.09;
      const o = overlay(p, "trail", delay, 0.55);
      window.setTimeout(() => { o.style.transition = "opacity .6s"; o.style.opacity = "0"; window.setTimeout(() => o.remove(), 650); }, (delay + 0.55) * 1000 + 150);
    }
  }

  function simulate(actionId: string): void {
    clearSim();
    if (!ctx.selected) return;
    const action = model.inspector?.actions?.find(a => a.id === actionId);
    const stale = action?.staleText ?? "potentially stale";
    ctx.simActive = true;
    const down = relatives(visibleEdges(ctx), canon, ctx.selected, "down");
    const c0 = ctx.nodes.get(ctx.selected)?.col ?? 0;
    for (const p of ctx.edgeEls) {
      if (!p || p.classList.contains("off")) continue;
      const a = canon(p.dataset.a ?? ""), b = canon(p.dataset.b ?? "");
      if (down.has(a) && down.has(b)) overlay(p, "ripple", Math.abs((ctx.nodes.get(a)?.col ?? 0) - c0) * 0.11, 0.5);
    }
    down.forEach(id => {
      if (id === ctx.selected) return;
      const d = ctx.nodeEls.get(id);
      if (!d) return;
      const delay = ctx.reduced ? 0 : Math.abs((ctx.nodes.get(id)?.col ?? 0) - c0) * 110 + 450;
      ctx.simTimers.push(window.setTimeout(() => {
        d.classList.add("fail");
        const sub = d.querySelector(".s");
        if (sub) { d.dataset.s = sub.innerHTML; sub.textContent = stale; }
      }, delay));
    });
    ctx.fn.announce(`Simulation: ${down.size - 1} groups downstream of ${ctx.nodes.get(ctx.selected)?.title ?? ""} would be ${stale}.`);
    ctx.fn.renderInspector();
  }
  function clearSim(): void {
    ctx.simTimers.forEach(t => clearTimeout(t));
    ctx.simTimers = [];
    dropOverlays("ripple");
    document.querySelectorAll<HTMLElement>(".node.fail").forEach(d => {
      d.classList.remove("fail");
      const sub = d.querySelector(".s");
      if (sub && d.dataset.s !== undefined) { sub.innerHTML = d.dataset.s; delete d.dataset.s; }
    });
    ctx.simActive = false;
  }

  /** The inspector covers the right 340 px. If the group would sit under it, glide the view left. */
  function revealNode(id: string): void {
    const d = ctx.nodeEls.get(id);
    if (!d) return;
    const r = d.getBoundingClientRect(), v = els.vp.getBoundingClientRect(), edge = v.right - 340 - 24;
    if (r.right > edge) {
      ctx.userMoved = true;
      ctx.fn.setView({ k: ctx.view.k, x: ctx.view.x + Math.max(edge - r.right, v.left + 60 - r.left), y: ctx.view.y }, true);
    }
  }

  function rectOf(ids: string[]): Rect | null {
    const ps = ids.map(i => ctx.geom.nodes[i]).filter((p): p is NonNullable<typeof p> => !!p && !!ctx.nodes.get(p.id) && nodeVisible(model, ctx.mode, ctx.nodes.get(p.id) as NodeDef, ctx.collapsed));
    if (!ps.length) return null;
    const x1 = Math.min(...ps.map(p => p.x)), y1 = Math.min(...ps.map(p => p.y));
    const x2 = Math.max(...ps.map(p => p.x + p.w)), y2 = Math.max(...ps.map(p => p.y + p.h));
    return { x: x1 - 20, y: y1 - 20, w: x2 - x1 + 40, h: y2 - y1 + 40 };
  }
  function zoomToPath(): void {
    if (!ctx.selected) return;
    const ids = [...connected(visibleEdges(ctx), canon, ctx.selected)];
    ids.push(...model.nodes.filter(n => n.ref && ids.includes(n.ref)).map(n => n.id));
    const r = rectOf(ids);
    if (r) { ctx.userMoved = true; ctx.fn.fit(true, r, inspInset()); ctx.fn.announce(`Zoomed to the path of ${ctx.nodes.get(ctx.selected)?.title ?? ""}`); }
  }
  function zoomToBand(id: string): void {
    const r = ctx.geom.lanes[id];
    if (!r) return;
    ctx.userMoved = true;
    ctx.fn.fit(true, { x: r.x - 10, y: r.y - 10, w: r.w + 20, h: r.h + 20 }, inspInset());
    ctx.fn.announce(`Zoomed to the lane ${model.lanes.find(l => l.id === id)?.title ?? id}`);
  }

  function escape(): void {
    clearSim();
    select(null);
    ctx.filter = null;
    ctx.query = "";
    els.q.value = "";
    els.matchinfo.textContent = "";
    ctx.fn.buildChrome();
    trace(null);
    ctx.fn.toggleNotes(false);
  }
  function setMode(id: string): void {
    if (ctx.mode === id) return;
    document.body.classList.remove("intro");
    clearSim();
    ctx.mode = id;
    const sel = ctx.selected && ctx.nodes.get(ctx.selected);
    if (sel && !nodeVisible(model, id, sel, ctx.collapsed)) select(null);
    ctx.fn.paint(true);
    ctx.userMoved = false;
    ctx.fn.fitWidth(true);
    const added = model.nodes.filter(n => nodeVisible(model, id, n, ctx.collapsed) && !nodeVisible(model, model.views?.[0]?.id ?? "all", n, ctx.collapsed)).length;
    ctx.fn.announce(added ? `${model.views?.find(v => v.id === id)?.label ?? id} view: ${added} groups added.` : `${model.views?.find(v => v.id === id)?.label ?? id} view.`);
  }

  ctx.fn.trace = trace;
  ctx.fn.select = select;
  ctx.fn.drawTrail = drawTrail;
  ctx.fn.simulate = simulate;
  ctx.fn.clearSim = clearSim;
  ctx.fn.rectOf = rectOf;
  ctx.fn.zoomToPath = zoomToPath;
  ctx.fn.zoomToBand = zoomToBand;
  ctx.fn.escape = escape;
  ctx.fn.setMode = setMode;
  ctx.fn.toggleGroup = (id: string) => {
    const group = model.nodes.find(n => n.id === id && n.kind === "group" && n.contains?.length);
    if (!group) return;
    const change = toggleGroupState(model, ctx.mode, ctx.collapsed, id);
    if (!change) return;
    ctx.collapsed = change.collapsed;
    ctx.fn.paint();
    ctx.fn.select(change.selected);
    ctx.fn.announce(change.expanding ? `Expanded ${group.title}.` : `Collapsed into ${group.title}.`);
  };
  ctx.fn.announce = (t: string) => { els.live.textContent = t; };
}
