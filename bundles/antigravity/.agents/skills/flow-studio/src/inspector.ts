// The slide-in inspector. It uses the markup and class names of the host app's own inspector
// (.insp, .insp-h, .counts .cbtn, .insp-b, .drill, .pill, .meta), so it looks native when the page lives in an app.
// It is closed until a click, and it also opens to list search matches when nothing is selected.

import type { Ctx } from "./ctx.ts";
import { esc } from "./model.ts";
import type { NodeDef, RelationDef } from "./model.ts";
import { bucketOf, effectiveLinks, groupFor, isImproved, isNew, nodeStateId, nodeVisible } from "./rules.ts";
import { matches, relationSet, relationsOf } from "./interact.ts";
import { sparklinePoints } from "./metrics.ts";

const BUCKET_COLOR = { good: "ok", neutral: "muted", gap: "warn" } as const;
const PILL = { ok: "ok", warn: "warn", crit: "warn", info: "info", accent: "info", muted: "muted" } as const;

export function install(ctx: Ctx): void {
  const { els, model } = ctx;

  const matchesFilter = (n: NodeDef, f: RelationDef["filter"]): boolean =>
    !f || ((f.col === undefined || n.col === f.col) && (f.kind === undefined || n.kind === f.kind));

  function wire(box: HTMLElement): void {
    box.querySelector("#hideInsp")?.addEventListener("click", () => {
      if (ctx.selected) ctx.fn.select(null);
      else { ctx.dismissed = true; ctx.fn.renderInspector(); }
    });
    box.querySelectorAll<HTMLElement>("[data-hl]").forEach(b => b.addEventListener("click", () => {
      ctx.hl = ctx.hl === b.dataset.hl ? null : (b.dataset.hl ?? null);
      ctx.fn.trace(ctx.selected);
      ctx.fn.renderInspector();
    }));
    box.querySelectorAll<HTMLElement>("[data-g]").forEach(b => b.addEventListener("click", () => { ctx.fn.select(b.dataset.g ?? null); ctx.fn.zoomToPath(); }));
    box.querySelectorAll<HTMLElement>("[data-act]").forEach(b => b.addEventListener("click", () => ctx.fn.simulate(b.dataset.act ?? "")));
    box.querySelectorAll<HTMLElement>("[data-toggle-group]").forEach(b => b.addEventListener("click", () => ctx.fn.toggleGroup(b.dataset.toggleGroup ?? "")));
    box.querySelector("#simReset")?.addEventListener("click", () => { ctx.fn.clearSim(); ctx.fn.renderInspector(); ctx.fn.announce("Simulation reset."); });
    box.querySelector("#zPath")?.addEventListener("click", () => ctx.fn.zoomToPath());
    box.querySelector("#zBand")?.addEventListener("click", () => { const n = ctx.selected ? ctx.nodes.get(ctx.selected) : undefined; if (n?.lane) ctx.fn.zoomToBand(n.lane); });
  }

  function renderInspector(): void {
    const box = els.inspector, ws = els.workspace;
    const sel = ctx.selected ? ctx.nodes.get(ctx.selected) : undefined;
    const head = `<div class="insp-h"><span>Inspector</span><button type="button" id="hideInsp" aria-label="Close the inspector">Close ✕</button></div>`;

    if (!sel) {
      const found = ctx.query && !ctx.dismissed ? model.nodes.filter(n => nodeVisible(model, ctx.mode, n, ctx.collapsed) && matches(ctx, n)) : [];
      const open = found.length > 0;
      box.classList.toggle("open", open);
      ws.classList.toggle("inspopen", open);
      box.setAttribute("aria-hidden", String(!open));
      if (!open) return;
      const rows = found.map(f => {
        const b = bucketOf(model, nodeStateId(model, ctx.mode, f));
        const hits = (f.members ?? []).filter(m => m.toLowerCase().includes(ctx.query)).length;
        return `<button type="button" class="dr" data-g="${esc(f.id)}"><span class="dbar" style="background:var(--${BUCKET_COLOR[b]})"></span><span class="dtx"><span class="dn">${esc(f.title)}</span><span class="dk">${hits} match · ${esc(model.columns[f.col ?? 0]?.title ?? "")}</span></span></button>`;
      }).join("");
      box.innerHTML = head + `<div class="insp-b"><div class="insp-sec"><b>${found.length}</b> group${found.length === 1 ? "" : "s"} match “${esc(ctx.query)}”</div><div class="drill">${rows}</div></div>`;
      wire(box);
      return;
    }

    box.classList.add("open");
    ws.classList.add("inspopen");
    box.setAttribute("aria-hidden", "false");

    const sid = nodeStateId(model, ctx.mode, sel);
    const st = model.states[sid];
    const bucket = bucketOf(model, sid);
    const lane = model.lanes.find(l => l.id === sel.lane);
    const counts = relationsOf(ctx).slice(0, 3).map(r => {
      const set = relationSet(ctx, r, sel.id);
      let n = 0;
      for (const id of set) {
        const x = ctx.nodes.get(id);
        if (!x) continue;
        if (r.filter) { if (matchesFilter(x, r.filter)) n += Math.max(1, x.weight ?? 1); }
        else if (id !== sel.id) n += 1;
      }
      const cls = r.id === "up" ? "cn--up" : r.id === "down" ? "cn--down" : "";
      return `<button class="cbtn" data-hl="${esc(r.id)}" aria-pressed="${ctx.hl === r.id}"><span class="cn ${cls}">${n}</span><span class="cl">${esc(r.label)}</span></button>`;
    }).join("");

    const pills = `<span class="pill ${PILL[st?.tone ?? "muted"]}">${esc(st?.word ?? sid)}</span>`
      + (isImproved(model, ctx.mode, sel) ? '<span class="pill info">gap filled</span>' : "")
      + (isNew(model, ctx.mode, sel) ? '<span class="pill muted">new in this view</span>' : "");
    const actions = (model.inspector?.actions ?? []).map(a => `<button type="button" class="danger" data-act="${esc(a.id)}">▶ ${esc(a.label)}</button>`).join("");
    const members = sel.members ?? [];
    const owner = groupFor(model, sel.id);
    const foldAction = sel.kind === "group" && sel.contains?.length && ctx.collapsed.has(sel.id)
      ? `<button type="button" data-toggle-group="${esc(sel.id)}">Expand group</button>`
      : owner && !ctx.collapsed.has(owner.id)
        ? `<button type="button" data-toggle-group="${esc(owner.id)}">Collapse into ${esc(owner.title)}</button>` : "";
    const exits = sel.kind === "gateway" ? effectiveLinks(model, ctx.mode, ctx.collapsed, ctx.nodes).filter(l => l.from === sel.id).map(l => {
      const target = ctx.nodes.get(l.to);
      return `<div class="dr"><span class="dtx"><span class="dn">${esc(l.label ?? "Unlabelled")}</span><span class="dk">${esc(target?.title ?? l.to)}</span></span></div>`;
    }).join("") : "";
    const metric = sel.metrics;
    const series = metric?.series ?? [];
    const points = sparklinePoints(series, 300, 40);
    const metricHtml = metric ? `<div class="insp-sec metrics"><b>Metrics</b><table class="meta"><tr><th>label</th><td>${esc(metric.label ?? "Metric")}</td></tr><tr><th>value</th><td>${esc(String(metric.value))} ${esc(metric.unit ?? "")}</td></tr>${metric.max != null ? `<tr><th>max</th><td>${esc(String(metric.max))} ${esc(metric.unit ?? "")}</td></tr>` : ""}</table>${points ? `<svg width="300" height="40" viewBox="0 0 300 40" role="img" aria-label="Metric trend"><polyline points="${points}"/></svg><div class="metric-range"><span>${esc(String(Math.min(...series)))}</span><span>${esc(String(Math.max(...series)))}</span></div>` : ""}</div>` : "";

    box.innerHTML = head + `<div class="counts">${counts}</div>
      <div class="insp-b"><div class="insp-sec"><p class="nname">${esc(sel.title)}</p><div class="nkind">${esc(model.columns[sel.col ?? 0]?.title ?? "")} · ${esc(lane?.title ?? sel.lane)}</div><div class="pillrow">${pills}</div>${sel.subtitle ? `<p class="note">${esc(sel.subtitle)}</p>` : ""}</div>
      <div class="insp-sec"><b>Details</b><table class="meta"><tr><th>state</th><td>${esc(st?.word ?? sid)}</td></tr><tr><th>members</th><td>${Math.max(1, sel.weight ?? 1)}</td></tr><tr><th>lane</th><td>${esc(lane?.title ?? sel.lane)}${lane?.badge ? ` (${esc(lane.badge)})` : ""}</td></tr>${sel.upgrade && bucket !== "good" ? `<tr><th>can improve</th><td>${esc(sel.upgrade)}</td></tr>` : ""}</table></div>
      ${metricHtml}
      ${sel.kind === "gateway" ? `<div class="insp-sec"><b>Exits</b><div class="drill">${exits}</div></div>` : ""}
      ${members.length ? `<div class="insp-sec"><b>Members</b> (${Math.max(members.length, sel.weight ?? 0)})<input id="mq" type="search" placeholder="Filter ${members.length} members…" aria-label="Filter members"><div class="drill" id="mlist"></div><p class="drill-hint" id="mcount"></p></div>` : `<div class="insp-sec"><p class="note">No member names are recorded for this group.</p></div>`}
      ${foldAction ? `<div class="acts">${foldAction}</div>` : ""}
      <div class="acts"><button type="button" id="zPath">Zoom to path</button><button type="button" id="zBand">Go to lane</button></div>
      ${actions ? `<div class="acts">${actions}<button type="button" id="simReset"${ctx.simActive ? "" : " hidden"}>Reset</button></div>` : ""}</div>`;
    wire(box);

    const mq = box.querySelector<HTMLInputElement>("#mq");
    const draw = () => {
      const f = (mq?.value ?? "").toLowerCase();
      const rows = members.filter(m => m.toLowerCase().includes(f));
      const list = box.querySelector<HTMLElement>("#mlist");
      if (list) list.innerHTML = rows.slice(0, 14).map(m => `<div class="dr"><span class="dbar" style="background:var(--${BUCKET_COLOR[bucket]})"></span><span class="dtx"><span class="dn mono" style="font-size:12px">${esc(m)}</span></span></div>`).join("");
      const cnt = box.querySelector<HTMLElement>("#mcount");
      const weight = sel.weight ?? 0;
      if (cnt) cnt.textContent = `${Math.min(14, rows.length)} of ${rows.length}${weight > members.length ? ` named (${weight} members in all)` : ""}`;
    };
    if (mq) { mq.addEventListener("input", draw); draw(); }
  }

  ctx.fn.renderInspector = renderInspector;
}
