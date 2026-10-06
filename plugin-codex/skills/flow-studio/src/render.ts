// Builds the world (lanes, nodes, links) once, and paints it for the current view.
// Every model string goes through esc(), so a hostile title cannot become markup.

import { el, sv, on, type Ctx } from "./ctx.ts";
import { esc } from "./model.ts";
import type { NodeDef } from "./model.ts";
import { computeGeometry, DEFAULTS, type Placed } from "./layout.ts";
import { elbow, loopBack } from "./routing.ts";
import { cssId } from "./stateCss.ts";
import { baselineView, bucketOf, canonOf, effectiveLinks, isImproved, isNew, linkStateId, nodeStateId, nodeVisible } from "./rules.ts";
import { metricBadge, sparkline } from "./metrics.ts";

function loopRoute(ctx: Ctx, fromId: string, toId: string, from: Placed, to: Placed, channel: number): string {
  const detourFor = (end: Placed, other: Placed) => {
    const center = end.x + end.w / 2, bottom = end.y + end.h;
    const blocker = ctx.model.nodes.filter(n => n.id !== fromId && n.id !== toId && nodeVisible(ctx.model, ctx.mode, n, ctx.collapsed))
      .map(n => ctx.geom.nodes[n.id]).filter((p): p is Placed => !!p && p.x < center && center < p.x + p.w && p.y > bottom && p.y < channel)
      .sort((a, b) => a.y - b.y)[0];
    if (!blocker) return undefined;
    return { x: other.x + other.w / 2 < center ? blocker.x - 10 : blocker.x + blocker.w + 10, y: (bottom + blocker.y) / 2 };
  };
  return loopBack(from.x + from.w / 2, from.y + from.h, to.x + to.w / 2, to.y + to.h, channel,
    { from: detourFor(from, to), to: detourFor(to, from) });
}

function nodeHtml(ctx: Ctx, n: NodeDef): string {
  const badge = metricBadge(n.metrics);
  const spark = sparkline(n.metrics, 56, 12);
  if (n.kind === "gateway") {
    return `<svg class="gw" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true"><polygon points="50,0 100,50 50,100 0,50"></polygon></svg><span class="gw-title">${esc(n.title)}</span>${badge}${spark}`;
  }
  const m = ctx.model;
  const sid = nodeStateId(m, ctx.mode, n);
  const word = m.states[sid]?.word ?? sid;
  const bucket = bucketOf(m, sid);
  const sub = n.subtitle ?? m.columns[n.col ?? 0]?.title ?? "";
  const weight = Math.max(1, n.weight ?? 1);
  const showWord = n.kind !== "placeholder" && n.kind !== "note";
  const bar = weight > 1 && n.kind !== "chip"
    ? `<div class="bar"><i class="${["good", "neutral", "gap"].includes(bucket) ? bucket : "gap"}" style="width:100%"></i></div>`
    : "";
  const improved = isImproved(m, ctx.mode, n) ? '<span class="cor up" title="Gap filled in this view">▲</span>' : "";
  const upgrade = n.upgrade && bucket !== "good" ? `<span class="cor meas" title="${esc("Can improve: " + n.upgrade)}">↗</span>` : "";
  const arrow = n.kind === "chip" ? '<span aria-hidden="true">↑ </span>' : "";
  const lead = showWord ? `<b class="ev st-${cssId(sid)}">${esc(word)}</b> · ` : "";
  const fold = n.kind === "group" && n.contains?.length ? `<span class="fold">▸ ${n.contains.length}</span>` : "";
  return `<div class="t"><span class="newdot" title="Added in this view"></span><span class="name">${arrow}${esc(n.title)}</span>${fold}${badge}</div>`
    + `<div class="s${spark ? " has-spark" : ""}" title="${esc(sub)}">${lead}${esc(sub)}</div>${spark}${bar}${improved}${upgrade}`;
}

function build(ctx: Ctx): void {
  const { model, els } = ctx;
  ctx.geom = computeGeometry(model);
  els.world.style.width = ctx.geom.world.w + "px";
  els.world.style.height = ctx.geom.world.h + "px";
  els.svg.setAttribute("width", String(ctx.geom.world.w));
  els.svg.setAttribute("height", String(ctx.geom.world.h));
  els.world.querySelectorAll(".node, .band, .elabel").forEach(n => n.remove());
  els.layer.innerHTML = "";
  ctx.nodeEls.clear(); ctx.laneEls.clear(); ctx.edgeEls = []; ctx.labelEls = [];

  for (const l of model.lanes) {
    const d = el("div", "band" + (l.gap ? " gap" : ""));
    d.id = "lane_" + l.id;
    const badge = l.badge ? `<span class="bd t-${["ok", "warn", "muted"].includes(l.badgeTone ?? "") ? l.badgeTone : "muted"}">${esc(l.badge)}</span>` : "";
    const note = l.note ? `<span class="bn">${esc(l.note)}</span>` : "";
    d.innerHTML = `<div class="bandlabel" role="button" tabindex="0" aria-label="${esc("Zoom to the lane " + l.title)}"><b>${esc(l.title)}</b>${badge}${note}</div>`;
    const label = d.firstElementChild as HTMLElement;
    on(ctx, label, "click", (e: Event) => { e.stopPropagation(); ctx.fn.zoomToBand(l.id); });
    on(ctx, label, "keydown", (e: KeyboardEvent) => { if (e.key === "Enter") ctx.fn.zoomToBand(l.id); });
    els.world.insertBefore(d, els.svg.parentElement === els.world ? els.svg : null);
    ctx.laneEls.set(l.id, d);
  }

  for (const n of model.nodes) {
    const p = ctx.geom.nodes[n.id];
    if (!p) continue;
    const d = el("div", "node" + (n.kind === "chip" ? " ref" : "") + ((n.colSpan ?? 1) > 1 ? " wide" : ""));
    d.id = "n_" + n.id;
    d.tabIndex = 0;
    d.setAttribute("role", "button");
    d.style.setProperty("--c", String(n.col ?? 0));
    d.style.left = p.x + "px"; d.style.top = p.y + "px"; d.style.width = p.w + "px"; d.style.height = p.h + "px";
    on(ctx, d, "click", () => { if (ctx.moved > 4) return; ctx.fn.select(canonOf(ctx.nodes, n.id)); });
    on(ctx, d, "dblclick", (e: Event) => { e.stopPropagation(); ctx.fn.select(canonOf(ctx.nodes, n.id)); ctx.fn.zoomToPath(); });
    on(ctx, d, "keydown", (e: KeyboardEvent) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); ctx.fn.select(canonOf(ctx.nodes, n.id)); } });
    on(ctx, d, "mouseenter", () => ctx.fn.trace(n.id));
    on(ctx, d, "mouseleave", () => ctx.fn.trace(ctx.selected));
    on(ctx, d, "focus", () => ctx.fn.trace(n.id));
    on(ctx, d, "blur", () => ctx.fn.trace(ctx.selected));
    els.world.appendChild(d);
    ctx.nodeEls.set(n.id, d);
  }

  const gap = DEFAULTS.gap;
  ctx.links.forEach((l, i) => {
    const A = ctx.geom.nodes[l.from], B = ctx.geom.nodes[l.to];
    if (!A || !B) { console.warn(`flow-studio: link ${l.id} skipped (an end is missing)`); return; }
    const x1 = A.x + A.w, y1 = A.y + A.h / 2, x2 = B.x, y2 = B.y + B.h / 2, tx = x1 + gap / 2;
    const loop = l.kind === "loop-back";
    const channel = ctx.geom.loops[l.id]?.channelY ?? Math.max(A.y + A.h, B.y + B.h) + 10;
    const d = loop
      ? loopRoute(ctx, l.from, l.to, A, B, channel)
      : elbow(x1, y1, x2 - 1, y2, tx);
    const path = sv("path", { d, class: "edge" + (loop ? " loop" : ""), "data-i": String(i), "data-a": l.from, "data-b": l.to, "marker-end": "url(#arr)" }) as SVGPathElement;
    els.layer.appendChild(path);
    ctx.edgeEls[i] = path;
    if (l.label) {
      const lab = el("div", "elabel", esc(l.label));
      lab.dataset.i = String(i); lab.dataset.a = l.from; lab.dataset.b = l.to;
      lab.style.left = (loop ? (A.x + A.w / 2 + B.x + B.w / 2) / 2 : Math.abs(y2 - y1) < 1 ? (x1 + x2) / 2 : tx) + "px";
      lab.style.top = (loop ? ctx.geom.loops[l.id]?.channelY ?? Math.max(A.y + A.h, B.y + B.h) + 10 : (y1 + y2) / 2) + "px";
      els.world.appendChild(lab);
      ctx.labelEls[i] = lab;
    }
  });
}

function paint(ctx: Ctx, fromSwitch = false): void {
  const { model } = ctx;
  const mode = ctx.mode;
  const effective = effectiveLinks(model, mode, ctx.collapsed, ctx.nodes);
  const effectiveById = new Map(effective.map(l => [l.id, l]));
  ctx.geom = computeGeometry({ ...model, links: effective }, { visible: id => { const n = ctx.nodes.get(id); return !!n && nodeVisible(model, mode, n, ctx.collapsed); } });
  ctx.els.world.style.height = ctx.geom.world.h + "px";
  ctx.els.svg.setAttribute("height", String(ctx.geom.world.h));
  document.body.classList.toggle("alt", !!model.views && mode !== baselineView(model));

  for (const n of model.nodes) {
    const d = ctx.nodeEls.get(n.id);
    if (!d) continue;
    const rect = ctx.geom.nodes[n.id];
    if (rect) { d.style.left = rect.x + "px"; d.style.top = rect.y + "px"; }
    const sid = nodeStateId(model, mode, n);
    const show = nodeVisible(model, mode, n, ctx.collapsed);
    const bucket = bucketOf(model, sid);
    const cors = (isImproved(model, mode, n) ? 1 : 0) + (n.upgrade && bucket !== "good" ? 1 : 0);
    const fresh = isNew(model, mode, n);
    d.className = "node st-" + cssId(sid)
      + (n.kind === "chip" ? " ref" : "") + (n.kind === "gateway" ? " gateway" : "") + ((n.colSpan ?? 1) > 1 ? " wide" : "") + (n.kind === "placeholder" ? " placeholder" : "")
      + (show ? "" : " off") + (fresh ? " isnew" : "") + (cors ? (cors > 1 ? " hascor2" : " hascor") : "")
      + (ctx.selected && canonOf(ctx.nodes, n.id) === ctx.selected ? " sel" : "")
      + (metricBadge(n.metrics) ? " has-metrics" : "");
    d.innerHTML = nodeHtml(ctx, n);
    d.setAttribute("aria-hidden", show ? "false" : "true");
    d.tabIndex = show ? 0 : -1;
    const word = model.states[sid]?.word ?? sid;
    const lane = model.lanes.find(l => l.id === n.lane)?.title ?? n.lane;
    d.setAttribute("aria-label", n.kind === "chip"
      ? `${n.title}: a reference to the node in the ${lane} lane. Press Enter to select it.`
      : `${n.title}. ${n.subtitle ?? model.columns[n.col ?? 0]?.title ?? ""}, ${word}. Press Enter to inspect.`);
    if (fromSwitch && fresh && !ctx.reduced) {
      d.style.transitionDelay = (n.col ?? 0) * 60 + "ms";
      d.classList.add("pulse");
      window.setTimeout(() => { d.style.transitionDelay = ""; d.classList.remove("pulse"); }, 2200);
    } else {
      d.style.transitionDelay = "";
    }
  }

  ctx.links.forEach((l, i) => {
    const p = ctx.edgeEls[i];
    if (!p) return;
    const edge = effectiveById.get(l.id);
    const vis = !!edge;
    const a = edge && ctx.geom.nodes[edge.from], b = edge && ctx.geom.nodes[edge.to];
    const loop = edge?.kind === "loop-back";
    if (a && b) {
      p.dataset.a = edge!.from; p.dataset.b = edge!.to;
      const channel = ctx.geom.loops[edge!.id]?.channelY ?? Math.max(a.y + a.h, b.y + b.h) + 10;
      p.setAttribute("d", loop
        ? loopRoute(ctx, edge!.from, edge!.to, a, b, channel)
        : elbow(a.x + a.w, a.y + a.h / 2, b.x - 1, b.y + b.h / 2, a.x + a.w + DEFAULTS.gap / 2));
      const lab = ctx.labelEls[i];
      if (lab) {
        lab.dataset.a = edge!.from; lab.dataset.b = edge!.to;
        lab.style.left = (loop ? (a.x + a.w / 2 + b.x + b.w / 2) / 2 : Math.abs(b.y + b.h / 2 - a.y - a.h / 2) < 1 ? (a.x + a.w + b.x) / 2 : a.x + a.w + DEFAULTS.gap / 2) + "px";
        lab.style.top = (loop ? channel : (a.y + a.h / 2 + b.y + b.h / 2) / 2) + "px";
      }
    }
    p.setAttribute("class", "edge st-" + cssId(edge?.state ?? linkStateId(model, mode, l)) + (loop ? " loop" : "") + (vis ? "" : " off"));
    ctx.labelEls[i]?.classList.toggle("off", !vis);
  });

  for (const l of model.lanes) {
    const d = ctx.laneEls.get(l.id);
    const r = ctx.geom.lanes[l.id];
    if (!d) continue;
    d.classList.toggle("off", !r);
    if (r) { d.style.left = r.x + "px"; d.style.top = r.y + "px"; d.style.width = r.w + "px"; d.style.height = r.h + "px"; }
  }

  ctx.fn.buildChrome();
  ctx.fn.trace(ctx.selected);
  ctx.fn.renderInspector();
  ctx.fn.stickLabels();
  ctx.fn.placeHeaders();
}

export function install(ctx: Ctx): void {
  ctx.fn.buildWorld = () => build(ctx);
  ctx.fn.paint = (fromSwitch?: boolean) => paint(ctx, fromSwitch);
}
