// The page around the canvas: completeness strip, summary tiles, legend, ledger, table view, title,
// view switch, search box and theme toggle. Text comes from the model; every string goes through esc() or textContent.

import { el, on, type Ctx } from "./ctx.ts";
import { esc } from "./model.ts";
import { DASH, toneVar, cssId } from "./stateCss.ts";
import { bucketOf, columnTitle, effectiveLinks, nodeStateId, nodeVisible } from "./rules.ts";
import { matches } from "./interact.ts";

const DEFAULT_LABELS: Record<string, string> = {
  tileGood: "links in a good state",
  tileNeutral: "links in a neutral state",
  tileGap: "groups with a gap: click to show",
  tileUpgrade: "groups you can improve: click to show",
  ledgerTitle: "What this view could not establish",
  tableTitle: "Table view",
};

export function install(ctx: Ctx): void {
  const { els, model } = ctx;
  const label = (k: string): string => model.meta.labels?.[k] ?? DEFAULT_LABELS[k] ?? k;
  const visible = (id: string): boolean => { const n = ctx.nodes.get(id); return !!n && nodeVisible(model, ctx.mode, n, ctx.collapsed); };

  function countUp(node: HTMLElement, to: number, ms = 700): void {
    if (ctx.reduced) { node.textContent = String(to); return; }
    const t0 = performance.now();
    const step = (t: number) => {
      const k = Math.min(1, (t - t0) / ms), e = 1 - Math.pow(1 - k, 3);
      node.textContent = String(Math.round(to * e));
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  function buildStrip(): void {
    const box = els.strip;
    box.style.display = model.columns.length ? "" : "none";
    box.style.gridTemplateColumns = `repeat(${Math.max(1, model.columns.length)}, minmax(0, 1fr))`;
    if (!box.firstChild) {
      box.innerHTML = model.columns.map(c => `<div class="lcell"><div class="ln">${esc(c.title)}</div><div class="lb"><i class="good"></i><i class="neutral"></i><i class="gap"></i></div><div class="lv"></div></div>`).join("");
    }
    box.querySelectorAll<HTMLElement>(".lcell").forEach((cell, i) => {
      cell.style.setProperty("--i", String(i));
      let tot = 0, good = 0, neutral = 0, gap = 0;
      for (const n of model.nodes) {
        if (n.col !== i || n.kind === "chip") continue;
        if (!visible(n.id)) continue;
        const w = Math.max(1, n.weight ?? 1);
        tot += w;
        const b = bucketOf(model, nodeStateId(model, ctx.mode, n));
        if (b === "good") good += w; else if (b === "neutral") neutral += w; else gap += w;
      }
      const t = tot || 1, bars = cell.querySelectorAll<HTMLElement>("i");
      requestAnimationFrame(() => {
        if (bars[0]) bars[0].style.width = good / t * 100 + "%";
        if (bars[1]) bars[1].style.width = neutral / t * 100 + "%";
        if (bars[2]) bars[2].style.width = gap / t * 100 + "%";
      });
      const lv = cell.querySelector<HTMLElement>(".lv");
      if (lv) lv.textContent = `${good + neutral} / ${tot}`;
      cell.title = `${model.columns[i]?.title ?? ""}: ${good} good, ${neutral} neutral, ${gap} gap`;
    });
  }

  function buildTiles(): void {
    const k = els.tiles;
    let good = 0, neutral = 0;
    for (const l of effectiveLinks(model, ctx.mode, ctx.collapsed, ctx.nodes)) {
      const b = bucketOf(model, l.state);
      if (b === "good") good++; else if (b === "neutral") neutral++;
    }
    let gaps = 0, upgrades = 0;
    for (const n of model.nodes) {
      if (!visible(n.id) || n.kind === "chip") continue;
      const b = bucketOf(model, nodeStateId(model, ctx.mode, n));
      if (b === "gap") gaps += 1;
      if (n.upgrade && b !== "good") upgrades++;
    }
    k.innerHTML = "";
    const tile = (cls: string, n: number, text: string, filter?: "gap" | "upgrade") => {
      const b = el(filter ? "button" : "div", "tile " + cls, `<span class="tn">0</span><span class="tl">${esc(text)}</span>`);
      b.style.setProperty("--i", String(k.children.length + 9));
      if (filter) {
        (b as HTMLButtonElement).type = "button";
        b.setAttribute("aria-pressed", String(ctx.filter === filter));
        b.addEventListener("click", () => {
          ctx.filter = ctx.filter === filter ? null : filter;
          ctx.fn.select(null);
          buildTiles();
          ctx.fn.trace(null);
          ctx.fn.announce(ctx.filter ? "Filter on" : "Filter off");
        });
      }
      k.appendChild(b);
      countUp(b.querySelector<HTMLElement>(".tn") as HTMLElement, n);
    };
    tile("ok", good, label("tileGood"));
    tile("", neutral, label("tileNeutral"));
    tile("warn", gaps, label("tileGap"), "gap");
    tile("", upgrades, label("tileUpgrade"), "upgrade");
  }

  function buildLegend(): void {
    const parts = Object.entries(model.states).map(([id, s]) => {
      const cap = s.edge === "dot" ? ' stroke-linecap="round"' : "";
      return `<span><svg width="40" height="10" aria-hidden="true"><path d="M0 5 H40" stroke="${toneVar(s.tone)}" stroke-width="2" stroke-dasharray="${DASH[s.edge]}"${cap}/></svg><b class="ev st-${cssId(id)}">${esc(s.word)}</b></span>`;
    });
    parts.push('<span id="hintline">scroll = zoom · drag = pan · double-click = fit</span>');
    els.legend.innerHTML = parts.join("");
  }

  function buildLedger(): void {
    let gaps = 0, total = 0;
    for (const n of model.nodes) { if (n.kind === "chip" || !visible(n.id)) continue; total++; if (bucketOf(model, nodeStateId(model, ctx.mode, n)) === "gap") gaps++; }
    const noLane = model.lanes.filter(l => l.gap).length;
    els.ledger.innerHTML = `<h4>${esc(label("ledgerTitle"))}</h4><p><b>${gaps}</b> of <b>${total}</b> groups in this view have a gap: they are drawn dotted and are never guessed. ${noLane ? `<b>${noLane}</b> lane${noLane === 1 ? " has" : "s have"} no source document yet.` : ""}</p><p>${esc(model.meta.source)}</p>`;
  }

  function buildTable(): void {
    const rows = model.nodes.filter(n => visible(n.id) && n.kind !== "chip").map(n => {
      const sid = nodeStateId(model, ctx.mode, n);
      const lane = model.lanes.find(l => l.id === n.lane)?.title ?? n.lane;
      return `<tr><th scope="row">${esc(columnTitle(model, n))}</th><td>${esc(lane)}</td><td>${esc(n.title)}</td><td>${esc(model.states[sid]?.word ?? sid)}</td><td>${Math.max(1, n.weight ?? 1)}</td><td>${esc(n.subtitle ?? "")}</td><td>${esc(n.upgrade ?? "")}</td></tr>`;
    }).join("");
    els.table.innerHTML = `<thead><tr><th scope="col">Column</th><th scope="col">Lane</th><th scope="col">Group</th><th scope="col">State</th><th scope="col">Members</th><th scope="col">Detail</th><th scope="col">Can improve</th></tr></thead><tbody>${rows}</tbody>`;
  }

  ctx.fn.buildChrome = () => { buildStrip(); buildTiles(); buildTable(); buildLedger(); };

  // ---- page text and controls, set up once
  document.title = model.meta.title;
  els.title.textContent = model.meta.title;
  els.help.textContent = model.meta.help;
  els.readat.textContent = model.meta.asOf ? `as of ${model.meta.asOf}` : "";
  els.footer.textContent = model.meta.source;
  buildLegend();

  const views = model.views ?? [];
  els.modeSwitch.hidden = views.length < 2;
  els.modeSwitch.innerHTML = "";
  for (const v of views) {
    const b = el("button", "seg");
    b.type = "button"; b.setAttribute("role", "tab"); b.dataset.mode = v.id;
    b.setAttribute("aria-selected", String(v.id === ctx.mode));
    b.textContent = v.label;
    on(ctx, b, "click", () => {
      els.modeSwitch.querySelectorAll("button").forEach(x => x.setAttribute("aria-selected", String(x === b)));
      ctx.fn.setMode(v.id);
    });
    els.modeSwitch.appendChild(b);
  }

  on(ctx, els.q, "input", (e: Event) => {
    ctx.query = (e.target as HTMLInputElement).value.trim().toLowerCase();
    ctx.dismissed = false;
    const n = model.nodes.filter(x => visible(x.id) && matches(ctx, x)).length;
    els.matchinfo.textContent = ctx.query ? `${n} group${n === 1 ? "" : "s"} match` : "";
    if (!ctx.selected) { ctx.fn.trace(null); ctx.fn.renderInspector(); }
  });
  on(ctx, els.hops, "change", () => {
    ctx.hops = Number(els.hops.value);
    ctx.fn.trace(ctx.selected);
  });
  on(ctx, els.q, "keydown", (e: KeyboardEvent) => {
    if (e.key !== "Enter" || !ctx.query) return;
    const ids = model.nodes.filter(x => visible(x.id) && matches(ctx, x)).map(x => x.id);
    const r = ctx.fn.rectOf(ids);
    if (r) { ctx.userMoved = true; ctx.fn.fit(true, r, els.inspector.classList.contains("open") ? 340 : 0); ctx.fn.announce(`Zoomed to ${ids.length} matching groups`); }
  });
  on(ctx, els.theme, "click", () => {
    const r = document.documentElement;
    const dark = r.dataset.theme ? r.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    r.dataset.theme = dark ? "light" : "dark";
  });
}
