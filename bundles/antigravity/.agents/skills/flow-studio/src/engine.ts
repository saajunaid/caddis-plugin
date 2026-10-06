// flow-studio engine entry. mount() draws a model into a page that has the shell's element ids and returns
// a small API (also placed on window.FlowStudio for the check harness). The generated demo page calls mount() itself.

import { validateModel, type Model, type NoteDef } from "./model.ts";
import { autoLayout } from "./autolayout.ts";
import type { Ctx, Els } from "./ctx.ts";
import type { View } from "./viewport.ts";
import type { Geometry } from "./layout.ts";
import { stateCss } from "./stateCss.ts";
import { defaultView, initialCollapsed } from "./rules.ts";
import { install as installInteract } from "./interact.ts";
import { install as installRender } from "./render.ts";
import { install as installControls } from "./controls.ts";
import { install as installInspector } from "./inspector.ts";
import { install as installChrome } from "./chrome.ts";
import { install as installNotes } from "./notes.ts";
import { install as installPlayback, type PlaybackController } from "./playbackui.ts";
import { diffModels } from "./diff.ts";
import { notifySelection } from "./selection.ts";
import type { Issue } from "./model.ts";

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
  play(scenarioId?: string): void;
  pause(): void;
  step(): void;
  seek(tMs: number): void;
  playback(): { scenario: string | null; step: number; playing: boolean; t: number };
  update(model: Model, opts?: { animate?: boolean }): { ok: boolean; issues: Issue[] };
  destroy(): void;
}

declare global {
  interface Window { FlowStudio?: FlowStudio; flowStudioMount?: typeof mount }
}

const IDS: Record<keyof Els, string> = {
  vp: "viewport", world: "world", svg: "edges", layer: "edgeLayer", cols: "cols", tools: "tools", zoom: "zoomLabel",
  inspector: "inspector", workspace: "workspace", live: "live", strip: "layerstrip", tiles: "kpis", legend: "legend",
  ledger: "ledger", table: "tbl", q: "q", hops: "hops", matchinfo: "matchinfo", modeSwitch: "modeSwitch", drawer: "drawer",
  notelist: "notelist", notesBtn: "notesBtn", theme: "theme", specbody: "specbody", spec: "spec", title: "title",
  readat: "readat", help: "help", footer: "footer", playbar: "playbar", pbScenario: "pbScenario", pbPlay: "pbPlay",
  pbStep: "pbStep", pbReset: "pbReset", pbSpeed: "pbSpeed", pbScrub: "pbScrub", pbCaption: "pbCaption",
  pbCounter: "pbCounter", pbChoices: "pbChoices", banner: "banner",
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

interface SavedState { view: View; mode: string; selected: string | null; inspectorOpen: boolean; query: string; hops: number; filter: Ctx["filter"]; collapsed: Set<string>; knownGroups: Set<string>; playback: ReturnType<PlaybackController["playback"]> }
export function mount(root: ParentNode, model: Model, opts: { notes?: NoteDef[]; onSelect?: (id: string | null) => void; restore?: SavedState } = {}): FlowStudio {
  if (!model || !Array.isArray(model.columns) || !Array.isArray(model.lanes) || !Array.isArray(model.nodes) || !Array.isArray(model.links) || !model.states) {
    throw new Error("flow-studio: the model needs columns, lanes, states, nodes and links");
  }
  if (model.layout === "auto") model = autoLayout(model);
  const els = findEls(root);
  const issues = validateModel(model);
  const errors = issues.filter(i => i.level === "error");
  for (const i of issues) (i.level === "error" ? console.error : console.warn)(`flow-studio ${i.code} ${i.where}: ${i.message}`);
  if (errors.length) els.help.textContent = `${errors.length} model error(s). See the console. The page shows what it can.`;

  const rm = matchMedia("(prefers-reduced-motion: reduce)");
  const ctx: Ctx = {
    model, root, els, onSelect: opts.onSelect,
    notes: opts.notes && opts.notes.length ? opts.notes : model.notes ?? [],
    nodes: new Map(model.nodes.map(n => [n.id, n])),
    links: model.links,
    geom: { xs: [], nodes: {}, lanes: {}, loops: {}, bounds: { x: 0, y: 0, w: 1, h: 1 }, world: { w: 1, h: 1 } },
    view: { x: 0, y: 0, k: 1 },
    reduced: rm.matches,
    mode: opts.restore && (model.views?.some(v => v.id === opts.restore!.mode) || (!model.views?.length && opts.restore.mode === "all")) ? opts.restore.mode : defaultView(model),
    collapsed: opts.restore ? new Set(model.nodes.filter(n => n.kind === "group" && n.contains && (opts.restore!.collapsed.has(n.id) || (!opts.restore!.knownGroups.has(n.id) && n.collapsed !== false))).map(n => n.id)) : initialCollapsed(model),
    selected: opts.restore?.selected && model.nodes.some(n => n.id === opts.restore!.selected) ? opts.restore.selected : null,
    hl: null, query: opts.restore?.query ?? "", hops: opts.restore?.hops ?? 0, filter: opts.restore?.filter ?? null, tool: "select",
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
  els.q.value = ctx.query;
  els.hops.value = String(ctx.hops);

  ctx.fn.buildWorld();
  ctx.fn.paint(false);
  const playback = installPlayback(ctx);
  if (opts.restore) {
    ctx.userMoved = true;
    ctx.fn.setView(opts.restore.view, false);
    playback.restore(opts.restore.playback);
    if (opts.restore.inspectorOpen) {
      els.inspector.classList.add("open");
      els.workspace.classList.add("inspopen");
      els.inspector.setAttribute("aria-hidden", "false");
      ctx.fn.renderInspector();
    } else {
      els.inspector.classList.remove("open");
      els.workspace.classList.remove("inspopen");
      els.inspector.setAttribute("aria-hidden", "true");
    }
  } else {
    // The entrance animation is for the first mount only; a live update restores and must not replay it.
    document.body.classList.add("intro");
    const introTimer = window.setTimeout(() => document.body.classList.remove("intro"), 2100);
    // destroy() clears these timers, so an update inside the window cannot fire the old instance's callbacks.
    ctx.disposers.push(() => { window.clearTimeout(introTimer); document.body.classList.remove("intro"); });
    ctx.fn.fitWidth(false);
    const fitTimer = window.setTimeout(() => { if (!ctx.userMoved) ctx.fn.fitWidth(false); }, 120);
    ctx.disposers.push(() => window.clearTimeout(fitTimer));
  }

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
    play: id => playback.play(id),
    pause: () => playback.pause(),
    step: () => playback.step(),
    seek: t => playback.seek(t),
    playback: () => playback.playback(),
    update: (nextModel, updateOpts) => {
      const prepared = nextModel.layout === "auto" ? autoLayout(nextModel) : nextModel;
      const nextIssues = validateModel(prepared);
      const count = nextIssues.filter(i => i.level === "error").length;
      if (count) {
        els.banner.textContent = `Update failed: ${count} errors. Showing the last good graph.`;
        els.banner.hidden = false;
        return { ok: false, issues: nextIssues };
      }
      const changes = diffModels(ctx.model, prepared);
      const saved: SavedState = { view: { ...ctx.view }, mode: ctx.mode, selected: ctx.selected, inspectorOpen: els.inspector.classList.contains("open"), query: ctx.query, hops: ctx.hops, filter: ctx.filter, collapsed: new Set(ctx.collapsed), knownGroups: new Set(ctx.model.nodes.filter(n => n.kind === "group").map(n => n.id)), playback: playback.playback() };
      api.destroy();
      const replacement = mount(root, prepared, { notes: opts.notes, onSelect: opts.onSelect, restore: saved });
      notifySelection(saved.selected, replacement.selected(), opts.onSelect);
      // Refresh this api in place: callers keep their reference and window.FlowStudio stays this
      // instance, so an update can never overwrite a different mounted engine.
      Object.assign(api, replacement);
      window.FlowStudio = api;
      els.banner.hidden = true; els.banner.textContent = "";
      if (updateOpts?.animate !== false && !ctx.reduced) {
        for (const id of changes.changed) root.querySelector<HTMLElement>(`#n_${CSS.escape(id)}`)?.classList.add("updated");
        for (const id of changes.added) root.querySelector<HTMLElement>(`#n_${CSS.escape(id)}`)?.classList.add("added");
      }
      return { ok: true, issues: nextIssues };
    },
    destroy: () => {
      ctx.fn.clearSim();
      ctx.disposers.forEach(d => d());
      ctx.disposers = [];
      style?.remove();
      if (window.FlowStudio === api || window.FlowStudio?.model === api.model) delete window.FlowStudio;
    },
  };
  window.FlowStudio = api;
  return api;
}
