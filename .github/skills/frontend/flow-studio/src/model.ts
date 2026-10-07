// The model: what an author writes. Pure types plus validation. No DOM.

export type Kind = "card" | "group" | "chip" | "gateway" | "start" | "end" | "event" | "placeholder" | "note";
export type Tone = "ok" | "warn" | "crit" | "info" | "muted" | "accent";
export type Border = "solid" | "dashed" | "dotted";
export type EdgeStyle = "flow" | "dash" | "dash-short" | "dot";
export type Motion = "flow" | "flow-slow" | "breathe" | "none";
export type Bucket = "good" | "neutral" | "gap";
export const NODE_HEIGHT: Record<Kind, number> = { card: 54, group: 54, gateway: 64, placeholder: 54, chip: 40, start: 40, end: 40, event: 40, note: 40 };

export interface StateDef {
  word: string;
  tone: Tone;
  border: Border;
  edge: EdgeStyle;
  motion: Motion;
  bucket: Bucket;
}
export interface ColumnDef { id: string; title: string; short?: string; width: number; phase?: string; continues?: boolean }
export interface LaneDef { id: string; title: string; badge?: string; badgeTone?: "ok" | "warn" | "muted"; note?: string; gap?: boolean }
export interface NodeDef {
  id: string;
  kind: Kind;
  lane?: string;
  col?: number;
  colSpan?: number;
  row?: number;
  x?: number;
  y?: number;
  w?: number;
  h?: number;
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
  contains?: string[];
  collapsed?: boolean;
  sla?: number;
  metrics?: NodeMetric;
  bars?: NodeBar[];
}
export interface NodeMetric {
  value: number;
  /** null means "no maximum" — the same as omitting it. Renderers treat both the same way. */
  max?: number | null;
  unit?: string;
  label?: string;
  series?: number[];
}
/** One bar of a node's chart. `key` is opaque (a date, a step) and links the same key across charts;
 *  a null `value` means no data for that key and is drawn as a short red tick, never as zero. */
export interface NodeBar {
  key: string;
  value: number | null;
  kind?: "low";
  label?: string;
}
export interface LinkDef {
  id: string;
  from: string;
  to: string;
  state: string;
  stateIn?: Record<string, string>;
  visibleIn?: string[];
  label?: string;
  kind?: "forward" | "loop-back";
}
export interface ViewDef { id: string; label: string; default?: boolean }
export interface RelationDef { id: string; label: string; dir: "up" | "down"; filter?: { col?: number; kind?: Kind } }
export interface ActionDef { id: string; label: string; dir: "down"; staleText: string }
export interface NoteDef { anchor: string; title: string; text: string }
export interface StepDef { link: string; at?: number; dur?: number; caption?: string }
export interface ScenarioDef { id: string; label: string; steps: StepDef[] }
export interface Model {
  version: 1;
  meta: { title: string; help: string; asOf: string; source: string; labels?: Record<string, string> };
  layout: "columns-lanes" | "free" | "auto";
  columns: ColumnDef[];
  lanes: LaneDef[];
  states: Record<string, StateDef>;
  nodes: NodeDef[];
  links: LinkDef[];
  views?: ViewDef[];
  inspector?: { relations: RelationDef[]; actions?: ActionDef[] };
  notes?: NoteDef[];
  scenarios?: ScenarioDef[];
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
  if (!["columns-lanes", "free", "auto"].includes(m.layout)) add("error", "layout-unsupported", "layout", `layout ${String(m.layout)} is not supported: use "columns-lanes", "free", or "auto".`);
  if (!Array.isArray(m.columns) || (m.layout === "columns-lanes" && m.columns.length === 0)) add("error", "columns-missing", "columns", "Columns are required for columns-lanes layout.");
  if (!Array.isArray(m.lanes) || (m.layout !== "auto" && m.lanes.length === 0)) add("error", "lanes-missing", "lanes", "At least one lane is required.");
  if (!m.states || typeof m.states !== "object" || Object.keys(m.states).length === 0) add("error", "states-missing", "states", "At least one state is required.");
  const columns = Array.isArray(m.columns) ? m.columns : [];
  if (columns[0]?.continues) add("error", "column-continues-first", "columns[0]", "The first column cannot continue a column before it.");
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
    if ((m.layout !== "auto" || n.lane !== undefined) && !laneIds.has(n.lane ?? "")) add("error", "lane-undefined", w, `Lane ${n.lane} is not defined.`);
    for (const s of [n.state, ...Object.values(n.stateIn ?? {})]) if (!stateIds.has(s)) add("error", "state-undefined", w, `State ${s} is not defined.`);
    if (m.layout === "columns-lanes" && (typeof n.row !== "number" || !Number.isFinite(n.row))) add("error", "row-invalid", w, `Node ${n.id} needs a finite number for row (it sets the vertical position).`);
    const span = n.colSpan ?? 1;
    if (m.layout === "columns-lanes" && (!Number.isInteger(n.col) || (n.col ?? -1) < 0 || (n.col ?? 0) + span > ncols)) add("error", "column-range", w, `Column ${n.col} with span ${span} is outside 0..${ncols - 1}.`);
    if (m.layout === "free") {
      if (!Number.isFinite(n.x) || !Number.isFinite(n.y)) add("error", "position-invalid", w, `Node ${n.id} needs finite x and y.`);
      if ((n.w !== undefined && (!Number.isFinite(n.w) || n.w <= 0)) || (n.h !== undefined && (!Number.isFinite(n.h) || n.h <= 0))) add("error", "size-invalid", w, `Node ${n.id} needs positive finite width and height.`);
    }
    const metric = n.metrics;
    const invalidSeries = metric?.series !== undefined && (!Array.isArray(metric.series) || metric.series.length > 60 || metric.series.some(v => !Number.isFinite(v)));
    if (metric !== undefined && (!metric || !Number.isFinite(metric.value) || (metric.max != null && !Number.isFinite(metric.max)) || invalidSeries)) add("error", "metric-invalid", w, "Metrics need finite values and at most 60 finite series points.");
    const badBars = n.bars !== undefined && (!Array.isArray(n.bars) || n.bars.length > 120 || n.bars.some(b => !b || typeof b.key !== "string" || (b.value !== null && (typeof b.value !== "number" || !Number.isFinite(b.value) || b.value < 0))));
    if (badBars) add("error", "bars-invalid", w, "Bars need a list of at most 120 items, each with a string key and a finite, non-negative value or null.");
    if (n.sla !== undefined && (!Number.isFinite(n.sla) || n.sla <= 0)) add("error", "sla-invalid", w, "SLA must be a positive finite number of seconds.");
  }
  for (const n of nodes) {
    if (n.kind === "chip" && (!n.ref || !nodeIds.has(n.ref))) add("error", "chip-ref", `nodes[${n.id}]`, `A chip must point at a real node (ref ${n.ref}).`);
  }
  const owner = new Map<string, string>();
  for (const group of nodes.filter(n => n.contains !== undefined)) {
    if (group.kind !== "group" || !Array.isArray(group.contains)) {
      add("error", "contains-shape", `nodes[${group.id}]`, "Only a group may contain a list of node ids.");
      continue;
    }
    for (const id of group.contains) {
      if (id === group.id) add("error", "contains-self", `nodes[${group.id}]`, `Group ${group.id} cannot contain itself.`);
      else if (!nodeIds.has(id)) add("error", "contains-undefined", `nodes[${group.id}]`, `Contained node ${id} does not exist.`);
      else if (owner.has(id)) add("error", "contains-duplicate", `nodes[${group.id}]`, `Node ${id} is already contained by ${owner.get(id)}.`);
      else owner.set(id, group.id);
    }
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
      if (m.layout !== "free" && a.col !== undefined && b.col !== undefined) {
        const forward = b.col > a.col + (a.colSpan ?? 1) - 1;
        if (!forward && l.kind !== "loop-back") add("warn", "link-direction", w, `Link ${l.id} does not run left to right (column ${a.col} to ${b.col}); mark it loop-back if it returns to an earlier stage.`);
        if (forward && l.kind === "loop-back") add("warn", "loop-back-forward", w, `Link ${l.id} is marked loop-back but runs forward.`);
      }
    }
    for (const s of [l.state, ...Object.values(l.stateIn ?? {})]) if (!stateIds.has(s)) add("error", "state-undefined", w, `State ${s} is not defined.`);
  }
  const scenarioIds = new Set<string>();
  for (const [i, scenario] of (Array.isArray(m.scenarios) ? m.scenarios : []).entries()) {
    const w = `scenarios[${i}]`;
    if (!scenario || typeof scenario.id !== "string" || typeof scenario.label !== "string" || !Array.isArray(scenario.steps)) { add("error", "scenario-shape", w, "A scenario needs an id, label and steps."); continue; }
    if (scenarioIds.has(scenario.id)) add("error", "scenario-duplicate", w, `Duplicate scenario id ${scenario.id}.`);
    scenarioIds.add(scenario.id);
    if (!scenario.steps.length) add("error", "scenario-empty", w, "A scenario needs at least one step.");
    const timed = scenario.steps.filter(s => s && s.at !== undefined).length;
    if (timed && timed !== scenario.steps.length) add("error", "scenario-at-partial", w, "Give every step an at time or none.");
    let prev: LinkDef | undefined, previousAt = -Infinity;
    for (const [j, step] of scenario.steps.entries()) {
      const sw = `${w}.steps[${j}]`;
      const link = links.find(l => l.id === step?.link);
      if (!link) add("error", "scenario-link", sw, `Unknown link ${step?.link}.`);
      if (step?.at !== undefined) {
        if (!Number.isFinite(step.at) || step.at < 0 || step.at < previousAt) add("error", "scenario-at-order", sw, "Step times must be finite, nonnegative and nondecreasing.");
        if (Number.isFinite(step.at) && step.at >= 0 && step.at >= previousAt) previousAt = step.at;
      }
      if (step?.dur !== undefined && (!Number.isFinite(step.dur) || step.dur <= 0)) add("error", "scenario-duration", sw, "Duration must be positive and finite.");
      if (prev && link) {
        const previousTo = prev.to;
        if ((nodes.find(n => n.id === previousTo)?.ref ?? previousTo) !== (nodes.find(n => n.id === link.from)?.ref ?? link.from)) add("warn", "scenario-gap", sw, "This step does not start at the previous step's target.");
      }
      if (link) prev = link;
    }
  }
  for (const n of nodes) {
    if (n.kind !== "gateway") continue;
    const exits = links.filter(l => l.from === n.id);
    if (exits.length === 0) add("warn", "gateway-no-exit", `nodes[${n.id}]`, `Gateway ${n.id} has no exit.`);
    else if (exits.length > 1 && exits.some(l => !l.label?.trim())) add("warn", "gateway-exit-label", `nodes[${n.id}]`, `Every exit from gateway ${n.id} needs a label.`);
  }
  for (const n of nodes) {
    if (!linked.has(n.id) && !n.allowIsolated && n.kind !== "note" && !(n.kind === "group" && n.contains?.length)) {
      add("error", "orphan", `nodes[${n.id}]`, `Node ${n.id} has no links. Add a link, a placeholder neighbour, or set allowIsolated.`);
    }
  }
  // Columns and rows are global to the canvas, so two nodes clash whatever their lane.
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const a = nodes[i]!, b = nodes[j]!;
      if (a.contains?.includes(b.id) || b.contains?.includes(a.id)) continue;
      if (m.layout === "free") {
        const aw = a.w ?? 190, ah = a.h ?? NODE_HEIGHT[a.kind] ?? 54, bw = b.w ?? 190, bh = b.h ?? NODE_HEIGHT[b.kind] ?? 54;
        if ([a.x, a.y, b.x, b.y, aw, ah, bw, bh].every(v => typeof v === "number" && Number.isFinite(v))
          && a.x! < b.x! + bw && b.x! < a.x! + aw && a.y! < b.y! + bh && b.y! < a.y! + ah) {
          add("error", "rect-overlap", `nodes[${a.id}]`, `Nodes ${a.id} and ${b.id} overlap.`);
        }
      } else if (a.col !== undefined && b.col !== undefined && a.row !== undefined && b.row !== undefined) {
        const ax2 = a.col + (a.colSpan ?? 1), bx2 = b.col + (b.colSpan ?? 1);
        if (a.col < bx2 && b.col < ax2 && Math.abs(a.row - b.row) < 1) {
          add("error", "cell-overlap", `nodes[${a.id}]`, `Nodes ${a.id} and ${b.id} overlap (same columns, rows less than 1 apart).`);
        }
      }
    }
  }
  const used = new Set(nodes.map(n => n.lane));
  for (const l of lanes) if (!used.has(l.id)) add("warn", "lane-empty", `lanes[${l.id}]`, `Lane ${l.id} has no nodes.`);
  return out;
}
