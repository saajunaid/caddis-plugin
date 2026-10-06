// The engine's shared state. Each DOM module receives one Ctx, reads and writes it, and registers
// its functions on ctx.fn, so modules call each other without importing each other.

import type { Model, NodeDef, LinkDef, NoteDef } from "./model.ts";
import type { View, Rect } from "./viewport.ts";
import type { Geometry } from "./layout.ts";

export interface Els {
  vp: HTMLElement;
  world: HTMLElement;
  svg: SVGSVGElement;
  layer: SVGGElement;
  cols: HTMLElement;
  tools: HTMLElement;
  zoom: HTMLElement;
  inspector: HTMLElement;
  workspace: HTMLElement;
  live: HTMLElement;
  strip: HTMLElement;
  tiles: HTMLElement;
  legend: HTMLElement;
  ledger: HTMLElement;
  table: HTMLElement;
  q: HTMLInputElement;
  hops: HTMLSelectElement;
  matchinfo: HTMLElement;
  modeSwitch: HTMLElement;
  drawer: HTMLElement;
  notelist: HTMLElement;
  notesBtn: HTMLElement;
  theme: HTMLElement;
  specbody: HTMLElement;
  spec: HTMLElement;
  title: HTMLElement;
  readat: HTMLElement;
  help: HTMLElement;
  footer: HTMLElement;
  playbar: HTMLElement;
  pbScenario: HTMLSelectElement;
  pbPlay: HTMLButtonElement;
  pbStep: HTMLButtonElement;
  pbReset: HTMLButtonElement;
  pbSpeed: HTMLSelectElement;
  pbScrub: HTMLInputElement;
  pbCaption: HTMLElement;
  pbCounter: HTMLElement;
  pbChoices: HTMLElement;
  banner: HTMLElement;
}

export type Filter = "gap" | "upgrade" | null;

export interface Fns {
  paint(fromSwitch?: boolean): void;
  buildWorld(): void;
  trace(id: string | null): void;
  select(id: string | null): void;
  renderInspector(): void;
  setView(v: View, animate?: boolean): void;
  fit(animate?: boolean, rect?: Rect, inset?: number): void;
  fitWidth(animate?: boolean): void;
  zoomBy(factor: number): void;
  zoomToPath(): void;
  zoomToBand(id: string): void;
  rectOf(ids: string[]): Rect | null;
  drawTrail(): void;
  simulate(actionId: string): void;
  clearSim(): void;
  announce(text: string): void;
  stickLabels(): void;
  placeHeaders(): void;
  buildChrome(): void;
  toggleNotes(on?: boolean): void;
  placeMarkers(): void;
  escape(): void;
  setMode(id: string): void;
  toggleGroup(id: string): void;
}

export interface Ctx {
  model: Model;
  root: ParentNode;
  els: Els;
  onSelect?: (id: string | null) => void;
  notes: NoteDef[];
  nodes: Map<string, NodeDef>;
  links: LinkDef[];
  geom: Geometry;
  view: View;
  reduced: boolean;
  mode: string;
  collapsed: Set<string>;
  selected: string | null;
  hl: string | null;
  query: string;
  hops: number;
  filter: Filter;
  tool: "select" | "hand";
  spaceDown: boolean;
  userMoved: boolean;
  dismissed: boolean;
  simActive: boolean;
  moved: number;
  nodeEls: Map<string, HTMLElement>;
  laneEls: Map<string, HTMLElement>;
  edgeEls: SVGPathElement[];
  labelEls: HTMLElement[];
  overlays: SVGPathElement[];
  simTimers: number[];
  disposers: Array<() => void>;
  fn: Fns;
}

export const SVG_NS = "http://www.w3.org/2000/svg";

/** Make an element with a class and (trusted, already escaped) inner HTML. */
export function el<K extends keyof HTMLElementTagNameMap>(tag: K, cls?: string, html?: string): HTMLElementTagNameMap[K] {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html !== undefined) e.innerHTML = html;
  return e;
}

export function sv(tag: string, attrs: Record<string, string>): SVGElement {
  const e = document.createElementNS(SVG_NS, tag);
  for (const k of Object.keys(attrs)) e.setAttribute(k, attrs[k] as string);
  return e;
}

/** Listen on a target and remember how to stop, so destroy() removes every listener. */
export function on<T extends EventTarget>(ctx: Ctx, target: T, type: string, fn: (e: any) => void, opts?: AddEventListenerOptions): void {
  target.addEventListener(type, fn, opts);
  ctx.disposers.push(() => target.removeEventListener(type, fn, opts));
}
