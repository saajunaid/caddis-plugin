// flow-studio engine entry. mount() draws a model into a page that has the shell's element ids and returns
// a small API (also placed on window.FlowStudio for the check harness). The generated demo page calls mount() itself.

import { validateModel, type Model, type NoteDef } from "./model.ts";
import type { Ctx, Els } from "./ctx.ts";
import type { View } from "./viewport.ts";
import type { Geometry } from "./layout.ts";
import { stateCss } from "./stateCss.ts";
import { defaultView } from "./rules.ts";
import { install as installInteract } from "./interact.ts";
import { install as installRender } from "./render.ts";
import { install as installControls } from "./controls.ts";
import { install as installInspector } from "./inspector.ts";
import { install as installChrome } from "./chrome.ts";
import { install as installNotes } from "./notes.ts";

export interface FlowStudio {
  model: Model;
  geometry(): Geometry;
  view(): View;
  setView(v: View, animate?: boolean): void;
  fit(animate?: boolean): void;
  select(id: string | null): void;
  selected(): string | null;
  mode(): string;
  setMode(id: string): void;
  simulate(actionId: string): void;
  resetSimulation(): void;
  destroy(): void;
}

declare global {
  interface Window { FlowStudio?: FlowStudio; flowStudioMount?: typeof mount }
}

const IDS: Record<keyof Els, string> = {
  vp: "viewport", world: "world", svg: "edges", layer: "edgeLayer", cols: "cols", tools: "tools", zoom: "zoomLabel",
  inspector: "inspector", workspace: "workspace", live: "live", strip: "layerstrip", tiles: "kpis", legend: "legend",
  ledger: "ledger", table: "tbl", q: "q", matchinfo: "matchinfo", modeSwitch: "modeSwitch", drawer: "drawer",
  notelist: "notelist", notesBtn: "notesBtn", theme: "theme", specbody: "specbody", spec: "spec", title: "title",
  readat: "readat", help: "help", footer: "footer",
};

function findEls(root: ParentNode): Els {
  const out = {} as Record<string, Element>;
  for (const [key, id] of Object.entries(IDS)) {
    const e = root.querySelector("#" + id);
    if (!e) throw new Error(`flow-studio: the page has no element #${id}`);
    out[key] = e;
  }
  return out as unknown as Els;
}

export function mount(root: ParentNode, model: Model, opts: { notes?: NoteDef[] } = {}): FlowStudio {
  if (!model || !Array.isArray(model.columns) || !Array.isArray(model.lanes) || !Array.isArray(model.nodes) || !Array.isArray(model.links) || !model.states) {
    throw new Error("flow-studio: the model needs columns, lanes, states, nodes and links");
  }
  const els = findEls(root);
  const issues = validateModel(model);
  const errors = issues.filter(i => i.level === "error");
  for (const i of issues) (i.level === "error" ? console.error : console.warn)(`flow-studio ${i.code} ${i.where}: ${i.message}`);
  if (errors.length) els.help.textContent = `${errors.length} model error(s). See the console. The page shows what it can.`;

  const rm = matchMedia("(prefers-reduced-motion: reduce)");
  const ctx: Ctx = {
    model, root, els,
    notes: opts.notes && opts.notes.length ? opts.notes : model.notes ?? [],
    nodes: new Map(model.nodes.map(n => [n.id, n])),
    links: model.links,
    geom: { xs: [], nodes: {}, lanes: {}, bounds: { x: 0, y: 0, w: 1, h: 1 }, world: { w: 1, h: 1 } },
    view: { x: 0, y: 0, k: 1 },
    reduced: rm.matches,
    mode: defaultView(model),
    selected: null, hl: null, query: "", filter: null, tool: "select",
    spaceDown: false, userMoved: false, dismissed: false, simActive: false, moved: 0,
    nodeEls: new Map(), laneEls: new Map(), edgeEls: [], labelEls: [], overlays: [], simTimers: [], disposers: [],
    fn: {} as Ctx["fn"],
  };
  const onRm = (e: MediaQueryListEvent) => { ctx.reduced = e.matches; };
  rm.addEventListener("change", onRm);
  ctx.disposers.push(() => rm.removeEventListener("change", onRm));

  let style = document.getElementById("state-css") as HTMLStyleElement | null;
  if (!style) { style = document.createElement("style"); style.id = "state-css"; document.head.prepend(style); }
  style.textContent = stateCss(model.states);

  installInteract(ctx);
  installRender(ctx);
  installControls(ctx);
  installInspector(ctx);
  installChrome(ctx);
  installNotes(ctx);

  document.body.classList.add("intro");
  window.setTimeout(() => document.body.classList.remove("intro"), 2100);
  ctx.fn.buildWorld();
  ctx.fn.paint(false);
  ctx.fn.fitWidth(false);
  window.setTimeout(() => ctx.fn.fitWidth(false), 120);

  const api: FlowStudio = {
    model,
    geometry: () => ctx.geom,
    view: () => ({ ...ctx.view }),
    setView: (v, animate) => ctx.fn.setView(v, animate),
    fit: animate => { ctx.userMoved = false; ctx.fn.fit(animate); },
    select: id => ctx.fn.select(id),
    selected: () => ctx.selected,
    mode: () => ctx.mode,
    setMode: id => ctx.fn.setMode(id),
    simulate: id => ctx.fn.simulate(id),
    resetSimulation: () => { ctx.fn.clearSim(); ctx.fn.renderInspector(); },
    destroy: () => {
      ctx.fn.clearSim();
      ctx.disposers.forEach(d => d());
      ctx.disposers = [];
      style?.remove();
      if (window.FlowStudio === api) delete window.FlowStudio;
    },
  };
  window.FlowStudio = api;
  return api;
}

function auto(): void {
  const m = document.getElementById("flow-model");
  if (!m) return;
  try {
    const model = JSON.parse(m.textContent ?? "{}") as Model;
    const n = document.getElementById("flow-notes");
    const notes = n ? (JSON.parse(n.textContent ?? "[]") as NoteDef[]) : undefined;
    mount(document, model, { notes });
  } catch (e) {
    console.error(e);
    const h = document.getElementById("help");
    if (h) h.textContent = "This page could not be drawn: " + (e instanceof Error ? e.message : String(e));
  }
}

window.flowStudioMount = mount;
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", auto);
else auto();
