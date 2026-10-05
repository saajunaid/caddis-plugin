// The model: what an author writes. Pure types plus validation. No DOM.

export type Kind = "card" | "group" | "chip" | "gateway" | "start" | "end" | "event" | "placeholder" | "note";
export type Tone = "ok" | "warn" | "crit" | "info" | "muted" | "accent";
export type Border = "solid" | "dashed" | "dotted";
export type EdgeStyle = "flow" | "dash" | "dash-short" | "dot";
export type Motion = "flow" | "flow-slow" | "breathe" | "none";
export type Bucket = "good" | "neutral" | "gap";

export interface StateDef {
  word: string;
  tone: Tone;
  border: Border;
  edge: EdgeStyle;
  motion: Motion;
  bucket: Bucket;
}
export interface ColumnDef { id: string; title: string; short?: string; width: number; phase?: string }
export interface LaneDef { id: string; title: string; badge?: string; badgeTone?: "ok" | "warn" | "muted"; note?: string; gap?: boolean }
export interface NodeDef {
  id: string;
  kind: Kind;
  lane: string;
  col: number;
  colSpan?: number;
  row: number;
  state: string;
  stateIn?: Record<string, string>;
  visibleIn?: string[];
  title: string;
  subtitle?: string;
  members?: string[];
  weight?: number;
  ref?: string;
  upgrade?: string;
  allowIsolated?: boolean;
}
export interface LinkDef {
  id: string;
  from: string;
  to: string;
  state: string;
  stateIn?: Record<string, string>;
  visibleIn?: string[];
  label?: string;
}
export interface ViewDef { id: string; label: string; default?: boolean }
export interface RelationDef { id: string; label: string; dir: "up" | "down"; filter?: { col?: number; kind?: Kind } }
export interface ActionDef { id: string; label: string; dir: "down"; staleText: string }
export interface NoteDef { anchor: string; title: string; text: string }
export interface Model {
  version: 1;
  meta: { title: string; help: string; asOf: string; source: string; labels?: Record<string, string> };
  layout: "columns-lanes";
  columns: ColumnDef[];
  lanes: LaneDef[];
  states: Record<string, StateDef>;
  nodes: NodeDef[];
  links: LinkDef[];
  views?: ViewDef[];
  inspector?: { relations: RelationDef[]; actions?: ActionDef[] };
  notes?: NoteDef[];
}
export interface Issue { level: "error" | "warn"; code: string; where: string; message: string }

const TONES = ["ok", "warn", "crit", "info", "muted", "accent"];
const BORDERS = ["solid", "dashed", "dotted"];
const EDGES = ["flow", "dash", "dash-short", "dot"];
const MOTIONS = ["flow", "flow-slow", "breathe", "none"];
const BUCKETS = ["good", "neutral", "gap"];

/** Turns a value into text that is safe inside HTML. Use it for every model string put into markup. */
export function esc(s: unknown): string {
  const map: Record<string, string> = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  return String(s ?? "").replace(/[&<>"']/g, c => map[c] as string);
}

/** Checks a model and returns every problem. Never throws. An error blocks the build; a warning does not. */
export function validateModel(input: unknown): Issue[] {
  const out: Issue[] = [];
  const add = (level: Issue["level"], code: string, where: string, message: string) => out.push({ level, code, where, message });
  if (!input || typeof input !== "object") {
    add("error", "model-shape", "model", "The model must be a JSON object.");
    return out;
  }
  const m = input as Model;
  if (m.version !== 1) add("error", "model-version", "version", "version must be 1.");
  if (m.layout !== "columns-lanes") add("error", "layout-unsupported", "layout", `layout ${String(m.layout)} is not supported yet: use "columns-lanes" ("free" and "auto" arrive in a later stage).`);
  if (!Array.isArray(m.columns) || m.columns.length === 0) add("error", "columns-missing", "columns", "At least one column is required.");
  if (!Array.isArray(m.lanes) || m.lanes.length === 0) add("error", "lanes-missing", "lanes", "At least one lane is required.");
  if (!m.states || typeof m.states !== "object" || Object.keys(m.states).length === 0) add("error", "states-missing", "states", "At least one state is required.");
  const columns = Array.isArray(m.columns) ? m.columns : [];
  const lanes = Array.isArray(m.lanes) ? m.lanes : [];
  const states = m.states && typeof m.states === "object" ? m.states : {};
  if (!m.meta || typeof m.meta !== "object" || typeof m.meta.title !== "string") add("error", "meta-missing", "meta", "meta with a title is required.");
  // Entries that are not objects are reported and dropped, so no later loop can throw on them.
  const nodes: NodeDef[] = [];
  (Array.isArray(m.nodes) ? m.nodes : []).forEach((n, i) => {
    if (!n || typeof n !== "object" || typeof (n as NodeDef).id !== "string") add("error", "node-shape", `nodes[${i}]`, "A node must be an object with a string id.");
    else nodes.push(n);
  });
  const links: LinkDef[] = [];
  (Array.isArray(m.links) ? m.links : []).forEach((l, i) => {
    if (!l || typeof l !== "object" || typeof (l as LinkDef).id !== "string") add("error", "link-shape", `links[${i}]`, "A link must be an object with a string id.");
    else links.push(l);
  });
  if (nodes.length === 0) add("warn", "model-empty", "nodes", "The model has no nodes.");

  for (const [id, s] of Object.entries(states)) {
    if (!/^[A-Za-z0-9_-]+$/.test(id)) add("error", "state-id", `states[${id}]`, `State id ${id} may only use letters, digits, "_" and "-" (it becomes a CSS class).`);
    const ok = s && typeof s.word === "string" && TONES.includes(s.tone) && BORDERS.includes(s.border) && EDGES.includes(s.edge) && MOTIONS.includes(s.motion) && BUCKETS.includes(s.bucket);
    if (!ok) add("error", "state-shape", `states[${id}]`, `State ${id} needs word, tone, border, edge, motion and bucket with allowed values.`);
  }
  const laneIds = new Set(lanes.map(l => l.id));
  const stateIds = new Set(Object.keys(states));
  const nodeIds = new Set<string>();
  const ncols = columns.length;
  for (const n of nodes) {
    const w = `nodes[${n.id}]`;
    if (nodeIds.has(n.id)) add("error", "node-duplicate", w, `Duplicate node id ${n.id}.`);
    nodeIds.add(n.id);
    if (!laneIds.has(n.lane)) add("error", "lane-undefined", w, `Lane ${n.lane} is not defined.`);
    for (const s of [n.state, ...Object.values(n.stateIn ?? {})]) if (!stateIds.has(s)) add("error", "state-undefined", w, `State ${s} is not defined.`);
    if (typeof n.row !== "number" || !Number.isFinite(n.row)) add("error", "row-invalid", w, `Node ${n.id} needs a finite number for row (it sets the vertical position).`);
    const span = n.colSpan ?? 1;
    if (!Number.isInteger(n.col) || n.col < 0 || n.col + span > ncols) add("error", "column-range", w, `Column ${n.col} with span ${span} is outside 0..${ncols - 1}.`);
  }
  for (const n of nodes) {
    if (n.kind === "chip" && (!n.ref || !nodeIds.has(n.ref))) add("error", "chip-ref", `nodes[${n.id}]`, `A chip must point at a real node (ref ${n.ref}).`);
  }
  const linkIds = new Set<string>();
  const linked = new Set<string>();
  for (const l of links) {
    const w = `links[${l.id}]`;
    if (linkIds.has(l.id)) add("error", "link-duplicate", w, `Duplicate link id ${l.id}.`);
    linkIds.add(l.id);
    if (!nodeIds.has(l.from) || !nodeIds.has(l.to)) add("error", "link-endpoint", w, `Link ${l.id} has an endpoint that is not a node (${l.from} to ${l.to}).`);
    else {
      linked.add(l.from); linked.add(l.to);
      const a = nodes.find(n => n.id === l.from)!, b = nodes.find(n => n.id === l.to)!;
      if (b.col <= a.col + (a.colSpan ?? 1) - 1) {
        add("warn", "link-direction", w, `Link ${l.id} does not run left to right (column ${a.col} to ${b.col}); it will look wrong until loop-back links arrive.`);
      }
    }
    for (const s of [l.state, ...Object.values(l.stateIn ?? {})]) if (!stateIds.has(s)) add("error", "state-undefined", w, `State ${s} is not defined.`);
  }
  for (const n of nodes) {
    if (!linked.has(n.id) && !n.allowIsolated && n.kind !== "note") {
      add("error", "orphan", `nodes[${n.id}]`, `Node ${n.id} has no links. Add a link, a placeholder neighbour, or set allowIsolated.`);
    }
  }
  // Columns and rows are global to the canvas, so two nodes clash whatever their lane.
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const a = nodes[i]!, b = nodes[j]!;
      const ax2 = a.col + (a.colSpan ?? 1), bx2 = b.col + (b.colSpan ?? 1);
      if (a.col < bx2 && b.col < ax2 && Math.abs(a.row - b.row) < 1) {
        add("error", "cell-overlap", `nodes[${a.id}]`, `Nodes ${a.id} and ${b.id} overlap (same columns, rows less than 1 apart).`);
      }
    }
  }
  const used = new Set(nodes.map(n => n.lane));
  for (const l of lanes) if (!used.has(l.id)) add("warn", "lane-empty", `lanes[${l.id}]`, `Lane ${l.id} has no nodes.`);
  return out;
}
