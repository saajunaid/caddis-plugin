var __defProp = Object.defineProperty;
var __export = (target, all) => {
  for (var name in all)
    __defProp(target, name, { get: all[name], enumerable: true });
};

// src/model.ts
var NODE_HEIGHT = { card: 54, group: 54, gateway: 64, placeholder: 54, chip: 40, start: 40, end: 40, event: 40, note: 40 };
var TONES = ["ok", "warn", "crit", "info", "muted", "accent"];
var BORDERS = ["solid", "dashed", "dotted"];
var EDGES = ["flow", "dash", "dash-short", "dot"];
var MOTIONS = ["flow", "flow-slow", "breathe", "none"];
var BUCKETS = ["good", "neutral", "gap"];
function esc(s) {
  const map = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  return String(s ?? "").replace(/[&<>"']/g, (c) => map[c]);
}
function validateModel(input) {
  const out = [];
  const add = (level, code, where, message) => out.push({ level, code, where, message });
  if (!input || typeof input !== "object") {
    add("error", "model-shape", "model", "The model must be a JSON object.");
    return out;
  }
  const m = input;
  if (m.version !== 1) add("error", "model-version", "version", "version must be 1.");
  if (!["columns-lanes", "free", "auto"].includes(m.layout)) add("error", "layout-unsupported", "layout", `layout ${String(m.layout)} is not supported: use "columns-lanes", "free", or "auto".`);
  if (!Array.isArray(m.columns) || m.layout === "columns-lanes" && m.columns.length === 0) add("error", "columns-missing", "columns", "Columns are required for columns-lanes layout.");
  if (!Array.isArray(m.lanes) || m.layout !== "auto" && m.lanes.length === 0) add("error", "lanes-missing", "lanes", "At least one lane is required.");
  if (!m.states || typeof m.states !== "object" || Object.keys(m.states).length === 0) add("error", "states-missing", "states", "At least one state is required.");
  const columns = Array.isArray(m.columns) ? m.columns : [];
  if (columns[0]?.continues) add("error", "column-continues-first", "columns[0]", "The first column cannot continue a column before it.");
  const lanes = Array.isArray(m.lanes) ? m.lanes : [];
  const states = m.states && typeof m.states === "object" ? m.states : {};
  if (!m.meta || typeof m.meta !== "object" || typeof m.meta.title !== "string") add("error", "meta-missing", "meta", "meta with a title is required.");
  const nodes = [];
  (Array.isArray(m.nodes) ? m.nodes : []).forEach((n, i) => {
    if (!n || typeof n !== "object" || typeof n.id !== "string") add("error", "node-shape", `nodes[${i}]`, "A node must be an object with a string id.");
    else nodes.push(n);
  });
  const links = [];
  (Array.isArray(m.links) ? m.links : []).forEach((l, i) => {
    if (!l || typeof l !== "object" || typeof l.id !== "string") add("error", "link-shape", `links[${i}]`, "A link must be an object with a string id.");
    else links.push(l);
  });
  if (nodes.length === 0) add("warn", "model-empty", "nodes", "The model has no nodes.");
  for (const [id, s] of Object.entries(states)) {
    if (!/^[A-Za-z0-9_-]+$/.test(id)) add("error", "state-id", `states[${id}]`, `State id ${id} may only use letters, digits, "_" and "-" (it becomes a CSS class).`);
    const ok = s && typeof s.word === "string" && TONES.includes(s.tone) && BORDERS.includes(s.border) && EDGES.includes(s.edge) && MOTIONS.includes(s.motion) && BUCKETS.includes(s.bucket);
    if (!ok) add("error", "state-shape", `states[${id}]`, `State ${id} needs word, tone, border, edge, motion and bucket with allowed values.`);
  }
  const laneIds = new Set(lanes.map((l) => l.id));
  const stateIds = new Set(Object.keys(states));
  const nodeIds = /* @__PURE__ */ new Set();
  const ncols = columns.length;
  for (const n of nodes) {
    const w = `nodes[${n.id}]`;
    if (nodeIds.has(n.id)) add("error", "node-duplicate", w, `Duplicate node id ${n.id}.`);
    nodeIds.add(n.id);
    if ((m.layout !== "auto" || n.lane !== void 0) && !laneIds.has(n.lane ?? "")) add("error", "lane-undefined", w, `Lane ${n.lane} is not defined.`);
    for (const s of [n.state, ...Object.values(n.stateIn ?? {})]) if (!stateIds.has(s)) add("error", "state-undefined", w, `State ${s} is not defined.`);
    if (m.layout === "columns-lanes" && (typeof n.row !== "number" || !Number.isFinite(n.row))) add("error", "row-invalid", w, `Node ${n.id} needs a finite number for row (it sets the vertical position).`);
    const span = n.colSpan ?? 1;
    if (m.layout === "columns-lanes" && (!Number.isInteger(n.col) || (n.col ?? -1) < 0 || (n.col ?? 0) + span > ncols)) add("error", "column-range", w, `Column ${n.col} with span ${span} is outside 0..${ncols - 1}.`);
    if (m.layout === "free") {
      if (!Number.isFinite(n.x) || !Number.isFinite(n.y)) add("error", "position-invalid", w, `Node ${n.id} needs finite x and y.`);
      if (n.w !== void 0 && (!Number.isFinite(n.w) || n.w <= 0) || n.h !== void 0 && (!Number.isFinite(n.h) || n.h <= 0)) add("error", "size-invalid", w, `Node ${n.id} needs positive finite width and height.`);
    }
    const metric = n.metrics;
    const invalidSeries = metric?.series !== void 0 && (!Array.isArray(metric.series) || metric.series.length > 60 || metric.series.some((v) => !Number.isFinite(v)));
    if (metric !== void 0 && (!metric || !Number.isFinite(metric.value) || metric.max != null && !Number.isFinite(metric.max) || invalidSeries)) add("error", "metric-invalid", w, "Metrics need finite values and at most 60 finite series points.");
    if (n.sla !== void 0 && (!Number.isFinite(n.sla) || n.sla <= 0)) add("error", "sla-invalid", w, "SLA must be a positive finite number of seconds.");
  }
  for (const n of nodes) {
    if (n.kind === "chip" && (!n.ref || !nodeIds.has(n.ref))) add("error", "chip-ref", `nodes[${n.id}]`, `A chip must point at a real node (ref ${n.ref}).`);
  }
  const owner = /* @__PURE__ */ new Map();
  for (const group of nodes.filter((n) => n.contains !== void 0)) {
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
  const linkIds = /* @__PURE__ */ new Set();
  const linked = /* @__PURE__ */ new Set();
  for (const l of links) {
    const w = `links[${l.id}]`;
    if (linkIds.has(l.id)) add("error", "link-duplicate", w, `Duplicate link id ${l.id}.`);
    linkIds.add(l.id);
    if (!nodeIds.has(l.from) || !nodeIds.has(l.to)) add("error", "link-endpoint", w, `Link ${l.id} has an endpoint that is not a node (${l.from} to ${l.to}).`);
    else {
      linked.add(l.from);
      linked.add(l.to);
      const a = nodes.find((n) => n.id === l.from), b = nodes.find((n) => n.id === l.to);
      if (m.layout !== "free" && a.col !== void 0 && b.col !== void 0) {
        const forward = b.col > a.col + (a.colSpan ?? 1) - 1;
        if (!forward && l.kind !== "loop-back") add("warn", "link-direction", w, `Link ${l.id} does not run left to right (column ${a.col} to ${b.col}); mark it loop-back if it returns to an earlier stage.`);
        if (forward && l.kind === "loop-back") add("warn", "loop-back-forward", w, `Link ${l.id} is marked loop-back but runs forward.`);
      }
    }
    for (const s of [l.state, ...Object.values(l.stateIn ?? {})]) if (!stateIds.has(s)) add("error", "state-undefined", w, `State ${s} is not defined.`);
  }
  const scenarioIds = /* @__PURE__ */ new Set();
  for (const [i, scenario] of (Array.isArray(m.scenarios) ? m.scenarios : []).entries()) {
    const w = `scenarios[${i}]`;
    if (!scenario || typeof scenario.id !== "string" || typeof scenario.label !== "string" || !Array.isArray(scenario.steps)) {
      add("error", "scenario-shape", w, "A scenario needs an id, label and steps.");
      continue;
    }
    if (scenarioIds.has(scenario.id)) add("error", "scenario-duplicate", w, `Duplicate scenario id ${scenario.id}.`);
    scenarioIds.add(scenario.id);
    if (!scenario.steps.length) add("error", "scenario-empty", w, "A scenario needs at least one step.");
    const timed = scenario.steps.filter((s) => s && s.at !== void 0).length;
    if (timed && timed !== scenario.steps.length) add("error", "scenario-at-partial", w, "Give every step an at time or none.");
    let prev, previousAt = -Infinity;
    for (const [j, step] of scenario.steps.entries()) {
      const sw = `${w}.steps[${j}]`;
      const link = links.find((l) => l.id === step?.link);
      if (!link) add("error", "scenario-link", sw, `Unknown link ${step?.link}.`);
      if (step?.at !== void 0) {
        if (!Number.isFinite(step.at) || step.at < 0 || step.at < previousAt) add("error", "scenario-at-order", sw, "Step times must be finite, nonnegative and nondecreasing.");
        if (Number.isFinite(step.at) && step.at >= 0 && step.at >= previousAt) previousAt = step.at;
      }
      if (step?.dur !== void 0 && (!Number.isFinite(step.dur) || step.dur <= 0)) add("error", "scenario-duration", sw, "Duration must be positive and finite.");
      if (prev && link) {
        const previousTo = prev.to;
        if ((nodes.find((n) => n.id === previousTo)?.ref ?? previousTo) !== (nodes.find((n) => n.id === link.from)?.ref ?? link.from)) add("warn", "scenario-gap", sw, "This step does not start at the previous step's target.");
      }
      if (link) prev = link;
    }
  }
  for (const n of nodes) {
    if (n.kind !== "gateway") continue;
    const exits = links.filter((l) => l.from === n.id);
    if (exits.length === 0) add("warn", "gateway-no-exit", `nodes[${n.id}]`, `Gateway ${n.id} has no exit.`);
    else if (exits.length > 1 && exits.some((l) => !l.label?.trim())) add("warn", "gateway-exit-label", `nodes[${n.id}]`, `Every exit from gateway ${n.id} needs a label.`);
  }
  for (const n of nodes) {
    if (!linked.has(n.id) && !n.allowIsolated && n.kind !== "note" && !(n.kind === "group" && n.contains?.length)) {
      add("error", "orphan", `nodes[${n.id}]`, `Node ${n.id} has no links. Add a link, a placeholder neighbour, or set allowIsolated.`);
    }
  }
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const a = nodes[i], b = nodes[j];
      if (a.contains?.includes(b.id) || b.contains?.includes(a.id)) continue;
      if (m.layout === "free") {
        const aw = a.w ?? 190, ah = a.h ?? NODE_HEIGHT[a.kind] ?? 54, bw = b.w ?? 190, bh = b.h ?? NODE_HEIGHT[b.kind] ?? 54;
        if ([a.x, a.y, b.x, b.y, aw, ah, bw, bh].every((v) => typeof v === "number" && Number.isFinite(v)) && a.x < b.x + bw && b.x < a.x + aw && a.y < b.y + bh && b.y < a.y + ah) {
          add("error", "rect-overlap", `nodes[${a.id}]`, `Nodes ${a.id} and ${b.id} overlap.`);
        }
      } else if (a.col !== void 0 && b.col !== void 0 && a.row !== void 0 && b.row !== void 0) {
        const ax2 = a.col + (a.colSpan ?? 1), bx2 = b.col + (b.colSpan ?? 1);
        if (a.col < bx2 && b.col < ax2 && Math.abs(a.row - b.row) < 1) {
          add("error", "cell-overlap", `nodes[${a.id}]`, `Nodes ${a.id} and ${b.id} overlap (same columns, rows less than 1 apart).`);
        }
      }
    }
  }
  const used = new Set(nodes.map((n) => n.lane));
  for (const l of lanes) if (!used.has(l.id)) add("warn", "lane-empty", `lanes[${l.id}]`, `Lane ${l.id} has no nodes.`);
  return out;
}

// src/autolayout.ts
function autoLayout(input) {
  const nodes = input.nodes.map((n) => ({ ...n }));
  const links = input.links.map((l) => ({ ...l }));
  const columns = input.columns.map((c) => ({ ...c }));
  const lanes = input.lanes.map((l) => ({ ...l }));
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const index = new Map(nodes.map((n, i) => [n.id, i]));
  const outgoing = new Map(nodes.map((n) => [n.id, []]));
  const incoming = new Map(nodes.map((n) => [n.id, []]));
  const neighbours = new Map(nodes.map((n) => [n.id, []]));
  for (const link of links) {
    if (!byId.has(link.from) || !byId.has(link.to)) continue;
    outgoing.get(link.from).push(link);
    incoming.get(link.to).push(link);
    neighbours.get(link.from).push(link.to);
    neighbours.get(link.to).push(link.from);
  }
  const color = /* @__PURE__ */ new Map();
  const post = [];
  for (const root of nodes) {
    if (color.has(root.id)) continue;
    color.set(root.id, 1);
    const stack = [{ id: root.id, next: 0 }];
    while (stack.length) {
      const frame = stack[stack.length - 1];
      const edges = outgoing.get(frame.id);
      if (frame.next >= edges.length) {
        color.set(frame.id, 2);
        post.push(frame.id);
        stack.pop();
        continue;
      }
      const link = edges[frame.next++];
      if (link.kind === "loop-back") continue;
      const state = color.get(link.to) ?? 0;
      if (state === 1) link.kind = "loop-back";
      else if (state === 0) {
        color.set(link.to, 1);
        stack.push({ id: link.to, next: 0 });
      }
    }
  }
  for (const id of post.reverse()) {
    const n = byId.get(id);
    if (n.col !== void 0) continue;
    let col = 0;
    for (const edge of incoming.get(id)) {
      if (edge.kind === "loop-back") continue;
      const parent = byId.get(edge.from);
      col = Math.max(col, (parent.col ?? 0) + (parent.colSpan ?? 1));
    }
    n.col = col;
  }
  const seen = /* @__PURE__ */ new Set();
  const usedLaneIds = new Set(lanes.map((l) => l.id));
  let group = 0;
  for (const first of nodes) {
    if (seen.has(first.id)) continue;
    const queue = [first.id];
    seen.add(first.id);
    for (let q = 0; q < queue.length; q++) {
      for (const id of neighbours.get(queue[q])) if (!seen.has(id)) {
        seen.add(id);
        queue.push(id);
      }
    }
    const missing = queue.map((id) => byId.get(id)).filter((n) => !n.lane);
    if (!missing.length) continue;
    group++;
    let laneId = `group-${group}`;
    while (usedLaneIds.has(laneId)) laneId += "-auto";
    usedLaneIds.add(laneId);
    lanes.push({ id: laneId, title: `Group ${group}` });
    for (const n of missing) n.lane = laneId;
  }
  const rank = new Map(nodes.map((n, i) => [n.id, i]));
  const laneOrder = lanes.map((l) => l.id);
  const cells = /* @__PURE__ */ new Map();
  for (const n of nodes) {
    const key = `${n.lane}\0${n.col}`;
    if (!cells.has(key)) cells.set(key, []);
    cells.get(key).push(n);
  }
  const maxCol = Math.max(0, ...nodes.map((n) => (n.col ?? 0) + (n.colSpan ?? 1) - 1));
  for (let sweep = 0; sweep < 4; sweep++) {
    const forward = sweep % 2 === 0;
    const layers = Array.from({ length: maxCol + 1 }, (_, i) => forward ? i : maxCol - i);
    for (const lane of laneOrder) for (const col of layers) {
      const groupNodes = cells.get(`${lane}\0${col}`);
      if (!groupNodes || groupNodes.length < 2) continue;
      const score = (n) => {
        const edges = forward ? incoming.get(n.id) : outgoing.get(n.id);
        const ns = edges.filter((e) => e.kind !== "loop-back").map((e) => forward ? e.from : e.to);
        return ns.length ? ns.reduce((sum, id) => sum + (rank.get(id) ?? 0), 0) / ns.length : rank.get(n.id) ?? 0;
      };
      groupNodes.sort((a, b) => score(a) - score(b) || index.get(a.id) - index.get(b.id));
      groupNodes.forEach((n, i) => rank.set(n.id, i));
    }
  }
  let nextBase = 0;
  const placed = nodes.filter((n) => n.row !== void 0);
  for (const lane of laneOrder) {
    const members = nodes.filter((n) => n.lane === lane);
    if (!members.length) continue;
    const ordered = [...members].sort((a, b) => (a.col ?? 0) - (b.col ?? 0) || (rank.get(a.id) ?? 0) - (rank.get(b.id) ?? 0) || index.get(a.id) - index.get(b.id));
    const rowAtCol = /* @__PURE__ */ new Map();
    for (const n of ordered) {
      if (n.row !== void 0) continue;
      let row = Math.max(nextBase, rowAtCol.get(n.col ?? 0) ?? nextBase);
      while (placed.some((p) => (n.col ?? 0) < (p.col ?? 0) + (p.colSpan ?? 1) && (p.col ?? 0) < (n.col ?? 0) + (n.colSpan ?? 1) && Math.abs(row - (p.row ?? 0)) < 1)) row += 1;
      n.row = row;
      placed.push(n);
      rowAtCol.set(n.col ?? 0, row + 1);
    }
    const last = Math.max(nextBase - 1, ...members.map((n) => n.row ?? 0));
    const loops = links.filter((l) => l.kind === "loop-back" && byId.get(l.from)?.lane === lane && byId.get(l.to)?.lane === lane).length;
    nextBase = last + 1.75 + loops * 0.35;
  }
  const needed = Math.max(0, ...nodes.map((n) => (n.col ?? 0) + (n.colSpan ?? 1)));
  while (columns.length < needed) {
    const i = columns.length + 1;
    columns.push({ id: `stage-${i}`, title: `Stage ${i}`, width: 190 });
  }
  return { ...input, nodes, links, columns, lanes };
}

// src/stateCss.ts
var cssId = (id) => id.replace(/[^A-Za-z0-9_-]/g, "_");
var TONES2 = { ok: "var(--ok)", warn: "var(--warn)", crit: "var(--crit)", info: "var(--up)", muted: "var(--muted)", accent: "var(--accent)" };
var toneVar = (t) => Object.hasOwn(TONES2, t) ? TONES2[t] : TONES2.muted;
var DASH = { flow: "5 9", dash: "7 6", "dash-short": "3 6", dot: "2 6" };
var KEYFRAMES = { flow: "flow", dash: "flowd", "dash-short": "flowc", dot: "" };
function stateCss(states) {
  const out = [];
  const reduced = [];
  for (const [id, s] of Object.entries(states)) {
    const c = cssId(id);
    const T = toneVar(s.tone);
    if (s.border === "dotted") {
      out.push(`.node.st-${c} { border:1px dotted ${T}; background:color-mix(in srgb, ${T} 10%, var(--panel)); --breath:${T}; }`);
      out.push(`.node.st-${c} .t { color:${T}; }`);
    } else {
      const glow = s.bucket === "good" ? ` box-shadow:0 0 14px -4px color-mix(in srgb, ${T} 55%, transparent), var(--shadow);` : "";
      out.push(`.node.st-${c} { border-left:4px ${s.border} ${T};${glow} --breath:${T}; }`);
    }
    out.push(`.node.st-${c}.gateway polygon { stroke:${T}; fill:color-mix(in srgb, ${T} 10%, var(--panel)); }`);
    out.push(`.ev.st-${c} { color:${T}; }`);
    if (s.motion === "breathe") out.push(`.node.st-${c}:not(.dim) { animation:breathe 3.2s ease-in-out infinite; }`);
    const edge = Object.hasOwn(DASH, s.edge) ? s.edge : "dash";
    const flows = edge !== "dot" && (s.motion === "flow" || s.motion === "flow-slow");
    let rule = `stroke:${T}; stroke-dasharray:${DASH[edge]}; opacity:${s.motion === "flow" ? ".85" : ".9"};`;
    if (edge === "dot") rule += " stroke-linecap:round;";
    if (flows) rule += ` animation:${KEYFRAMES[edge]} ${s.motion === "flow" ? "3s" : "7s"} linear infinite;`;
    if (flows && s.motion === "flow") rule += ` filter:drop-shadow(0 0 3px ${T});`;
    out.push(`path.edge.st-${c} { ${rule} }`);
    if (s.bucket === "gap") out.push(`path.edge.hot.st-${c} { stroke:${T}; filter:drop-shadow(0 0 5px ${T}); }`);
    if (flows) reduced.push(`path.edge.st-${c} { stroke-dasharray:none; }`);
  }
  if (reduced.length) out.push(`@media (prefers-reduced-motion: reduce) { ${reduced.join(" ")} }`);
  return out.join("\n");
}

// src/rules.ts
var rules_exports = {};
__export(rules_exports, {
  baselineView: () => baselineView,
  bucketOf: () => bucketOf,
  canonOf: () => canonOf,
  columnTitle: () => columnTitle,
  defaultView: () => defaultView,
  effectiveLinks: () => effectiveLinks,
  groupFor: () => groupFor,
  initialCollapsed: () => initialCollapsed,
  isImproved: () => isImproved,
  isNew: () => isNew,
  linkStateId: () => linkStateId,
  linkVisible: () => linkVisible,
  nodeStateId: () => nodeStateId,
  nodeVisible: () => nodeVisible,
  stripHeads: () => stripHeads,
  toggleGroupState: () => toggleGroupState
});
var baselineView = (m) => m.views?.[0]?.id ?? "all";
var defaultView = (m) => (m.views?.find((v) => v.default) ?? m.views?.[0])?.id ?? "all";
var initialCollapsed = (m) => new Set(m.nodes.filter((n) => n.kind === "group" && n.contains && n.collapsed !== false).map((n) => n.id));
var stripHeads = (m) => {
  let head = 0;
  return m.columns.map((c, i) => {
    if (!c.continues || i === 0) head = i;
    return head;
  });
};
var columnTitle = (m, n) => n.col === void 0 ? "" : m.columns[n.col]?.title ?? "";
function groupFor(m, nodeId) {
  return m.nodes.find((n) => n.kind === "group" && n.contains?.includes(nodeId));
}
var nodeVisible = (m, view, n, collapsed) => {
  if (n.visibleIn && !n.visibleIn.includes(view)) return false;
  if (!collapsed) return true;
  if (n.kind === "group" && n.contains) return collapsed.has(n.id);
  const owner = groupFor(m, n.id);
  return !owner || !collapsed.has(owner.id);
};
function toggleGroupState(m, view, collapsed, id) {
  const group = m.nodes.find((n) => n.id === id && n.kind === "group" && n.contains?.length);
  if (!group) return null;
  const next = new Set(collapsed);
  const expanding = next.has(id);
  if (expanding) next.delete(id);
  else next.add(id);
  const selected = expanding ? group.contains?.find((child) => {
    const n = m.nodes.find((candidate) => candidate.id === child);
    return !!n && nodeVisible(m, view, n, next);
  }) ?? null : id;
  return { collapsed: next, selected, expanding };
}
var nodeStateId = (_m, view, n) => n.stateIn?.[view] ?? n.state;
function linkVisible(m, view, l, nodes) {
  if (l.visibleIn && !l.visibleIn.includes(view)) return false;
  const a = nodes.get(l.from);
  const b = nodes.get(l.to);
  return !!a && !!b && nodeVisible(m, view, a) && nodeVisible(m, view, b);
}
var linkStateId = (_m, view, l) => l.stateIn?.[view] ?? l.state;
var bucketOf = (m, stateId) => m.states[stateId]?.bucket ?? "gap";
var isNew = (m, view, n) => view !== baselineView(m) && nodeVisible(m, view, n) && !nodeVisible(m, baselineView(m), n);
var isImproved = (m, view, n) => {
  const base = baselineView(m);
  return view !== base && nodeVisible(m, base, n) && bucketOf(m, nodeStateId(m, base, n)) === "gap" && bucketOf(m, nodeStateId(m, view, n)) !== "gap";
};
var canonOf = (nodes, id) => nodes.get(id)?.ref ?? id;
function effectiveLinks(m, view, collapsed, nodes) {
  const byPair = /* @__PURE__ */ new Map();
  const rank = { good: 0, neutral: 1, gap: 2 };
  for (const link of m.links) {
    if (link.visibleIn && !link.visibleIn.includes(view)) continue;
    const a = nodes.get(link.from), b = nodes.get(link.to);
    if (!a || !b || a.visibleIn && !a.visibleIn.includes(view) || b.visibleIn && !b.visibleIn.includes(view)) continue;
    const groupA = groupFor(m, a.id), groupB = groupFor(m, b.id);
    const from = groupA && collapsed.has(groupA.id) ? groupA.id : a.id;
    const to = groupB && collapsed.has(groupB.id) ? groupB.id : b.id;
    if (from === to) continue;
    const fromNode = nodes.get(from), toNode = nodes.get(to);
    if (!fromNode || !toNode || !nodeVisible(m, view, fromNode, collapsed) || !nodeVisible(m, view, toNode, collapsed)) continue;
    const state = linkStateId(m, view, link);
    const key = JSON.stringify([from, to]);
    const prev = byPair.get(key);
    if (!prev) byPair.set(key, { ...link, from, to, state, stateIn: void 0 });
    else if (rank[bucketOf(m, state)] > rank[bucketOf(m, prev.state)]) prev.state = state;
  }
  return [...byPair.values()];
}

// src/trace.ts
var trace_exports = {};
__export(trace_exports, {
  connected: () => connected,
  relatives: () => relatives,
  withinHops: () => withinHops
});
function relatives(edges, canonOf2, start, dir) {
  const set = /* @__PURE__ */ new Set([canonOf2(start)]);
  let grew = true;
  while (grew) {
    grew = false;
    for (const e of edges) {
      const a = canonOf2(e.from);
      const b = canonOf2(e.to);
      if (dir === "up" && set.has(b) && !set.has(a)) {
        set.add(a);
        grew = true;
      }
      if (dir === "down" && set.has(a) && !set.has(b)) {
        set.add(b);
        grew = true;
      }
    }
  }
  return set;
}
function connected(edges, canonOf2, start) {
  return /* @__PURE__ */ new Set([...relatives(edges, canonOf2, start, "up"), ...relatives(edges, canonOf2, start, "down")]);
}
function withinHops(edges, canonOf2, starts, n) {
  const found = new Set(starts.map(canonOf2));
  const radius = Number.isFinite(n) ? Math.max(0, Math.floor(n)) : 0;
  let frontier = [...found];
  for (let hop = 0; hop < radius && frontier.length; hop++) {
    const next = [];
    const current = new Set(frontier);
    for (const edge of edges) {
      const a = canonOf2(edge.from), b = canonOf2(edge.to);
      if (current.has(a) && !found.has(b)) {
        found.add(b);
        next.push(b);
      }
      if (current.has(b) && !found.has(a)) {
        found.add(a);
        next.push(a);
      }
    }
    frontier = next;
  }
  return found;
}

// src/selection.ts
function notifySelection(previous, next, onSelect) {
  if (previous !== next) onSelect?.(next);
}

// src/interact.ts
function relationsOf(ctx) {
  const given = ctx.model.inspector?.relations;
  if (given && given.length) return given;
  const last = Math.max(0, ctx.model.columns.length - 1);
  return [
    { id: "up", label: "Upstream", dir: "up" },
    { id: "down", label: "Downstream", dir: "down" },
    { id: "end", label: "At the end", dir: "down", filter: { col: last } }
  ];
}
function visibleEdges(ctx) {
  return effectiveLinks(ctx.model, ctx.mode, ctx.collapsed, ctx.nodes).map((l) => ({ from: l.from, to: l.to }));
}
function relationSet(ctx, rel, start) {
  const canon = (id) => canonOf(ctx.nodes, id);
  const set = relatives(visibleEdges(ctx), canon, start, rel.dir);
  if (!rel.filter) return set;
  const out = /* @__PURE__ */ new Set([canon(start)]);
  for (const id of set) {
    const n = ctx.nodes.get(id);
    if (!n) continue;
    if ((rel.filter.col === void 0 || n.col === rel.filter.col) && (rel.filter.kind === void 0 || n.kind === rel.filter.kind)) out.add(id);
  }
  return out;
}
function matches(ctx, n) {
  const q = ctx.query;
  return !!q && (n.title.toLowerCase().includes(q) || (n.members ?? []).some((m) => m.toLowerCase().includes(q)));
}
function install(ctx) {
  const { els, model } = ctx;
  const canon = (id) => canonOf(ctx.nodes, id);
  const visibleNodes = () => model.nodes.filter((n) => nodeVisible(model, ctx.mode, n, ctx.collapsed));
  const inspInset = () => els.inspector.classList.contains("open") ? 340 : 0;
  function activeSet(id) {
    const edges = visibleEdges(ctx);
    if (id) {
      if (id === ctx.selected && ctx.hl) {
        const rel = relationsOf(ctx).find((r) => r.id === ctx.hl);
        if (rel) return relationSet(ctx, rel, id);
      }
      return connected(edges, canon, id);
    }
    if (ctx.filter) {
      return new Set(visibleNodes().filter((n) => {
        const b = bucketOf(model, nodeStateId(model, ctx.mode, n));
        return ctx.filter === "gap" ? b === "gap" : !!n.upgrade && b !== "good";
      }).map((n) => canon(n.id)));
    }
    if (ctx.query) return withinHops(edges, canon, visibleNodes().filter((n) => matches(ctx, n)).map((n) => n.id), ctx.hops);
    return null;
  }
  function trace(id) {
    const set = activeSet(id);
    const lit = !!id && !!set;
    for (const n of model.nodes) {
      const d = ctx.nodeEls.get(n.id);
      if (!d) continue;
      d.classList.toggle("dim", !!set && !set.has(canon(n.id)));
      d.classList.toggle("lit", lit && !!set && set.has(canon(n.id)));
    }
    ctx.edgeEls.forEach((p) => {
      if (!p) return;
      const inSet = !!set && set.has(canon(p.dataset.a ?? "")) && set.has(canon(p.dataset.b ?? ""));
      p.classList.toggle("dim", !!set && !inSet);
      p.classList.toggle("hot", lit && inSet);
    });
    ctx.labelEls.forEach((l) => {
      if (l) l.classList.toggle("show", lit && !!set && set.has(canon(l.dataset.a ?? "")) && set.has(canon(l.dataset.b ?? "")));
    });
  }
  function select(id) {
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
  function overlay(edge, cls, delay, dur) {
    const o = edge.cloneNode(false);
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
  function dropOverlays(cls) {
    ctx.overlays.filter((o) => o.classList.contains(cls)).forEach((o) => o.remove());
    ctx.overlays = ctx.overlays.filter((o) => o.isConnected);
  }
  function drawTrail() {
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
      window.setTimeout(() => {
        o.style.transition = "opacity .6s";
        o.style.opacity = "0";
        window.setTimeout(() => o.remove(), 650);
      }, (delay + 0.55) * 1e3 + 150);
    }
  }
  function simulate(actionId) {
    clearSim();
    if (!ctx.selected) return;
    const action = model.inspector?.actions?.find((a) => a.id === actionId);
    const stale = action?.staleText ?? "potentially stale";
    ctx.simActive = true;
    const down = relatives(visibleEdges(ctx), canon, ctx.selected, "down");
    const c0 = ctx.nodes.get(ctx.selected)?.col ?? 0;
    for (const p of ctx.edgeEls) {
      if (!p || p.classList.contains("off")) continue;
      const a = canon(p.dataset.a ?? ""), b = canon(p.dataset.b ?? "");
      if (down.has(a) && down.has(b)) overlay(p, "ripple", Math.abs((ctx.nodes.get(a)?.col ?? 0) - c0) * 0.11, 0.5);
    }
    down.forEach((id) => {
      if (id === ctx.selected) return;
      const d = ctx.nodeEls.get(id);
      if (!d) return;
      const delay = ctx.reduced ? 0 : Math.abs((ctx.nodes.get(id)?.col ?? 0) - c0) * 110 + 450;
      ctx.simTimers.push(window.setTimeout(() => {
        d.classList.add("fail");
        const sub = d.querySelector(".s");
        if (sub) {
          d.dataset.s = sub.innerHTML;
          sub.textContent = stale;
        }
      }, delay));
    });
    ctx.fn.announce(`Simulation: ${down.size - 1} groups downstream of ${ctx.nodes.get(ctx.selected)?.title ?? ""} would be ${stale}.`);
    ctx.fn.renderInspector();
  }
  function clearSim() {
    ctx.simTimers.forEach((t) => clearTimeout(t));
    ctx.simTimers = [];
    dropOverlays("ripple");
    document.querySelectorAll(".node.fail").forEach((d) => {
      d.classList.remove("fail");
      const sub = d.querySelector(".s");
      if (sub && d.dataset.s !== void 0) {
        sub.innerHTML = d.dataset.s;
        delete d.dataset.s;
      }
    });
    ctx.simActive = false;
  }
  function revealNode(id) {
    const d = ctx.nodeEls.get(id);
    if (!d) return;
    const r = d.getBoundingClientRect(), v = els.vp.getBoundingClientRect(), edge = v.right - 340 - 24;
    if (r.right > edge) {
      ctx.userMoved = true;
      ctx.fn.setView({ k: ctx.view.k, x: ctx.view.x + Math.max(edge - r.right, v.left + 60 - r.left), y: ctx.view.y }, true);
    }
  }
  function rectOf(ids) {
    const ps = ids.map((i) => ctx.geom.nodes[i]).filter((p) => !!p && !!ctx.nodes.get(p.id) && nodeVisible(model, ctx.mode, ctx.nodes.get(p.id), ctx.collapsed));
    if (!ps.length) return null;
    const x1 = Math.min(...ps.map((p) => p.x)), y1 = Math.min(...ps.map((p) => p.y));
    const x2 = Math.max(...ps.map((p) => p.x + p.w)), y2 = Math.max(...ps.map((p) => p.y + p.h));
    return { x: x1 - 20, y: y1 - 20, w: x2 - x1 + 40, h: y2 - y1 + 40 };
  }
  function zoomToPath() {
    if (!ctx.selected) return;
    const ids = [...connected(visibleEdges(ctx), canon, ctx.selected)];
    ids.push(...model.nodes.filter((n) => n.ref && ids.includes(n.ref)).map((n) => n.id));
    const r = rectOf(ids);
    if (r) {
      ctx.userMoved = true;
      ctx.fn.fit(true, r, inspInset());
      ctx.fn.announce(`Zoomed to the path of ${ctx.nodes.get(ctx.selected)?.title ?? ""}`);
    }
  }
  function zoomToBand(id) {
    const r = ctx.geom.lanes[id];
    if (!r) return;
    ctx.userMoved = true;
    ctx.fn.fit(true, { x: r.x - 10, y: r.y - 10, w: r.w + 20, h: r.h + 20 }, inspInset());
    ctx.fn.announce(`Zoomed to the lane ${model.lanes.find((l) => l.id === id)?.title ?? id}`);
  }
  function escape() {
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
  function setMode(id) {
    if (ctx.mode === id) return;
    document.body.classList.remove("intro");
    clearSim();
    ctx.mode = id;
    const sel = ctx.selected && ctx.nodes.get(ctx.selected);
    if (sel && !nodeVisible(model, id, sel, ctx.collapsed)) select(null);
    ctx.fn.paint(true);
    ctx.userMoved = false;
    ctx.fn.fitWidth(true);
    const added = model.nodes.filter((n) => nodeVisible(model, id, n, ctx.collapsed) && !nodeVisible(model, model.views?.[0]?.id ?? "all", n, ctx.collapsed)).length;
    ctx.fn.announce(added ? `${model.views?.find((v) => v.id === id)?.label ?? id} view: ${added} groups added.` : `${model.views?.find((v) => v.id === id)?.label ?? id} view.`);
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
  ctx.fn.toggleGroup = (id) => {
    const group = model.nodes.find((n) => n.id === id && n.kind === "group" && n.contains?.length);
    if (!group) return;
    const change = toggleGroupState(model, ctx.mode, ctx.collapsed, id);
    if (!change) return;
    ctx.collapsed = change.collapsed;
    ctx.fn.paint();
    ctx.fn.select(change.selected);
    ctx.fn.announce(change.expanding ? `Expanded ${group.title}.` : `Collapsed into ${group.title}.`);
  };
  ctx.fn.announce = (t) => {
    els.live.textContent = t;
  };
}

// src/ctx.ts
var SVG_NS = "http://www.w3.org/2000/svg";
function el(tag, cls, html) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html !== void 0) e.innerHTML = html;
  return e;
}
function sv(tag, attrs) {
  const e = document.createElementNS(SVG_NS, tag);
  for (const k of Object.keys(attrs)) e.setAttribute(k, attrs[k]);
  return e;
}
function on(ctx, target, type, fn, opts) {
  target.addEventListener(type, fn, opts);
  ctx.disposers.push(() => target.removeEventListener(type, fn, opts));
}

// src/layout.ts
var DEFAULTS = { pitch: 62, top: 64, gap: 34, padX: 24, visible: () => true };
var LANE_PAD_TOP = 38;
var LANE_PAD_BOTTOM = 14;
function computeGeometry(m, opt = {}) {
  const o = { ...DEFAULTS, ...opt };
  const xs = [];
  let x = o.padX;
  for (const c of m.columns) {
    xs.push(x);
    x += c.width + o.gap;
  }
  const world = { w: Math.max(1, x - o.gap + o.padX), h: 1 };
  const nodes = {};
  for (const n of m.nodes) {
    const h = NODE_HEIGHT[n.kind] ?? 54;
    if (m.layout === "free") {
      nodes[n.id] = { id: n.id, x: n.x ?? 0, y: n.y ?? 0, w: n.w ?? 190, h: n.h ?? h };
      continue;
    }
    const first = Math.min(Math.max(0, n.col ?? 0), m.columns.length - 1);
    const last = Math.min(m.columns.length - 1, first + (n.colSpan ?? 1) - 1);
    const x0 = xs[first] ?? o.padX;
    const x1 = (xs[last] ?? x0) + (m.columns[last]?.width ?? 0);
    nodes[n.id] = { id: n.id, x: x0, y: o.top + 40 + (n.row ?? 0) * o.pitch - h / 2, w: Math.max(1, x1 - x0), h };
  }
  if (m.layout === "free") world.w = Math.max(world.w, ...Object.values(nodes).map((p) => p.x + p.w + o.padX), 1);
  const loops = {};
  const lanes = {};
  const visibleMembers = (id) => m.nodes.filter((n) => n.lane === id && o.visible(n.id)).map((n) => nodes[n.id]);
  const ordered = m.lanes.map((l) => ({ l, mem: visibleMembers(l.id) })).filter((x2) => x2.mem.length).sort((a, b) => Math.min(...a.mem.map((p) => p.y)) - Math.min(...b.mem.map((p) => p.y)));
  let previousBottom = -Infinity;
  for (const { l, mem } of ordered) {
    const top = Math.min(...mem.map((p) => p.y)) - LANE_PAD_TOP;
    const shift = m.layout === "free" ? 0 : Math.max(0, previousBottom + 8 - top);
    if (shift) for (const p of mem) p.y += shift;
    const y1 = top + shift;
    const laneNodeIds = new Set(mem.map((p) => p.id));
    const possibleLoops = m.links.filter((link) => link.kind === "loop-back" && o.visible(link.from) && o.visible(link.to) && (laneNodeIds.has(link.from) || laneNodeIds.has(link.to))).length;
    const bottom = Math.max(...mem.map((p) => p.y + p.h));
    const y2 = bottom + (possibleLoops ? 10 + 8 * (possibleLoops - 1) : 0) + LANE_PAD_BOTTOM;
    lanes[l.id] = { x: 8, y: y1, w: world.w - 16, h: y2 - y1 };
    previousBottom = y2;
  }
  const channelCounts = /* @__PURE__ */ new Map();
  for (const link of m.links) {
    if (link.kind !== "loop-back" || !o.visible(link.from) || !o.visible(link.to)) continue;
    const a = nodes[link.from], b = nodes[link.to];
    if (!a || !b) continue;
    const lower = a.y + a.h >= b.y + b.h ? a : b;
    const laneId = m.nodes.find((n) => n.id === lower.id)?.lane;
    if (!laneId || !lanes[laneId]) continue;
    const left = Math.min(a.x + a.w / 2, b.x + b.w / 2);
    const right = Math.max(a.x + a.w / 2, b.x + b.w / 2);
    const laneMembers = visibleMembers(laneId);
    const crossed = laneMembers.filter((p) => p.x < right && p.x + p.w > left);
    const lowestBottom = Math.max(a.y + a.h, b.y + b.h, ...crossed.map((p) => p.y + p.h));
    const index = channelCounts.get(laneId) ?? 0;
    loops[link.id] = { channelY: lowestBottom + 10 + 8 * index };
    channelCounts.set(laneId, index + 1);
    const lane = lanes[laneId];
    lane.h = Math.max(lane.h, loops[link.id].channelY + LANE_PAD_BOTTOM - lane.y);
  }
  const all = Object.values(lanes);
  let bounds = { x: 0, y: 0, w: world.w, h: 1 };
  if (all.length) {
    const top = Math.min(...all.map((r) => r.y));
    bounds = { x: 8, y: top, w: world.w - 16, h: Math.max(...all.map((r) => r.y + r.h)) - top };
  }
  world.h = Math.max(1, bounds.y + bounds.h + 70);
  return { xs, nodes, lanes, loops, bounds, world };
}

// src/routing.ts
var routing_exports = {};
__export(routing_exports, {
  elbow: () => elbow,
  loopBack: () => loopBack
});
function elbow(x1, y1, x2, y2, tx) {
  const r = 8;
  if (Math.abs(y2 - y1) < 1) return `M${x1},${y1} H${x2}`;
  if (Math.abs(y2 - y1) < 2 * r + 2) return `M${x1},${y1} C${tx},${y1} ${tx},${y2} ${x2},${y2}`;
  const dir = y2 > y1 ? 1 : -1;
  return `M${x1},${y1} H${tx - r} Q${tx},${y1} ${tx},${y1 + dir * r} V${y2 - dir * r} Q${tx},${y2} ${tx + r},${y2} H${x2}`;
}
function loopBack(x1, y1, x2, y2, channelY, detour = {}) {
  x1 = Number.isFinite(x1) ? x1 : 0;
  x2 = Number.isFinite(x2) ? x2 : 0;
  y1 = Number.isFinite(y1) ? y1 : 0;
  y2 = Number.isFinite(y2) ? y2 : 0;
  channelY = Number.isFinite(channelY) ? channelY : Math.max(y1, y2) + 10;
  channelY = Math.max(channelY, y1, y2);
  const from = detour.from, to = detour.to;
  const startX = from?.x ?? x1, endX = to?.x ?? x2;
  const start = from ? `M${x1},${y1} V${from.y} H${startX}` : `M${x1},${y1}`;
  const finish = to ? ` V${to.y} H${x2} V${y2}` : ` V${y2}`;
  if (from || to) {
    const dir2 = endX >= startX ? 1 : -1;
    const r2 = Math.max(0, Math.min(8, Math.abs(endX - startX) / 2, (channelY - (from?.y ?? y1)) / 2, (channelY - (to?.y ?? y2)) / 2));
    return `${start} V${channelY - r2} Q${startX},${channelY} ${startX + dir2 * r2},${channelY} H${endX - dir2 * r2} Q${endX},${channelY} ${endX},${channelY - r2}${finish}`;
  }
  const dx = x2 - x1;
  const dir = dx >= 0 ? 1 : -1;
  const run = Math.abs(dx) || 32;
  const radius = Math.min(8, run / 2, (channelY - y1) / 2, (channelY - y2) / 2);
  const r = Math.max(0, radius);
  if (dx === 0) {
    return `M${x1},${y1} V${channelY - r} Q${x1},${channelY} ${x1 + r},${channelY} H${x1 + 16} H${x1 - r} Q${x1},${channelY} ${x1},${channelY - r} V${y2}`;
  }
  return `M${x1},${y1} V${channelY - r} Q${x1},${channelY} ${x1 + dir * r},${channelY} H${x2 - dir * r} Q${x2},${channelY} ${x2},${channelY - r} V${y2}`;
}

// src/metrics.ts
function sparklinePoints(series, width, height) {
  if (!Array.isArray(series) || series.length < 2 || series.some((v) => !Number.isFinite(v))) return "";
  const min = Math.min(...series), max = Math.max(...series), span = max - min;
  return series.map((v, i) => `${Math.round(i / (series.length - 1) * width * 100) / 100},${Math.round((span ? 1 - (v - min) / span : 0.5) * height * 100) / 100}`).join(" ");
}
function metricBadge(metric) {
  if (!metric) return "";
  const label = metric.label ?? "Metric";
  const valStr = esc(String(metric.value));
  const unitStr = metric.unit ? " " + esc(metric.unit) : "";
  const title = `${esc(label)}: ${valStr}${unitStr}`;
  const hasMax = metric.max != null && Number.isFinite(metric.max) && metric.max > 0;
  const pct = hasMax && Number.isFinite(metric.value) ? Math.max(0, Math.min(100, metric.value / metric.max * 100)) : 0;
  const bar = hasMax ? `<i style="width:${pct}%"></i>` : "";
  return `<span class="metric-badge" title="${title}">${valStr}${unitStr}${bar}</span>`;
}
function sparkline(metric, width = 56, height = 12) {
  if (!metric?.series || metric.series.length < 2) return "";
  const points = sparklinePoints(metric.series, width, height);
  if (!points) return "";
  return `<svg class="spark" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" aria-hidden="true"><polyline points="${points}"/></svg>`;
}

// src/render.ts
function loopRoute(ctx, fromId, toId, from, to, channel) {
  const detourFor = (end, other) => {
    const center = end.x + end.w / 2, bottom = end.y + end.h;
    const blocker = ctx.model.nodes.filter((n) => n.id !== fromId && n.id !== toId && nodeVisible(ctx.model, ctx.mode, n, ctx.collapsed)).map((n) => ctx.geom.nodes[n.id]).filter((p) => !!p && p.x < center && center < p.x + p.w && p.y > bottom && p.y < channel).sort((a, b) => a.y - b.y)[0];
    if (!blocker) return void 0;
    return { x: other.x + other.w / 2 < center ? blocker.x - 10 : blocker.x + blocker.w + 10, y: (bottom + blocker.y) / 2 };
  };
  return loopBack(
    from.x + from.w / 2,
    from.y + from.h,
    to.x + to.w / 2,
    to.y + to.h,
    channel,
    { from: detourFor(from, to), to: detourFor(to, from) }
  );
}
function nodeHtml(ctx, n) {
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
  const bar = weight > 1 && n.kind !== "chip" ? `<div class="bar"><i class="${["good", "neutral", "gap"].includes(bucket) ? bucket : "gap"}" style="width:100%"></i></div>` : "";
  const improved = isImproved(m, ctx.mode, n) ? '<span class="cor up" title="Gap filled in this view">\u25B2</span>' : "";
  const upgrade = n.upgrade && bucket !== "good" ? `<span class="cor meas" title="${esc("Can improve: " + n.upgrade)}">\u2197</span>` : "";
  const arrow = n.kind === "chip" ? '<span aria-hidden="true">\u2191 </span>' : "";
  const lead = showWord ? `<b class="ev st-${cssId(sid)}">${esc(word)}</b> \xB7 ` : "";
  const fold = n.kind === "group" && n.contains?.length ? `<span class="fold">\u25B8 ${n.contains.length}</span>` : "";
  return `<div class="t"><span class="newdot" title="Added in this view"></span><span class="name">${arrow}${esc(n.title)}</span>${fold}${badge}</div><div class="s${spark ? " has-spark" : ""}" title="${esc(sub)}">${lead}${esc(sub)}</div>${spark}${bar}${improved}${upgrade}`;
}
function build(ctx) {
  const { model, els } = ctx;
  ctx.geom = computeGeometry(model);
  els.world.style.width = ctx.geom.world.w + "px";
  els.world.style.height = ctx.geom.world.h + "px";
  els.svg.setAttribute("width", String(ctx.geom.world.w));
  els.svg.setAttribute("height", String(ctx.geom.world.h));
  els.world.querySelectorAll(".node, .band, .elabel").forEach((n) => n.remove());
  els.layer.innerHTML = "";
  ctx.nodeEls.clear();
  ctx.laneEls.clear();
  ctx.edgeEls = [];
  ctx.labelEls = [];
  for (const l of model.lanes) {
    const d = el("div", "band" + (l.gap ? " gap" : ""));
    d.id = "lane_" + l.id;
    const badge = l.badge ? `<span class="bd t-${["ok", "warn", "muted"].includes(l.badgeTone ?? "") ? l.badgeTone : "muted"}">${esc(l.badge)}</span>` : "";
    const note = l.note ? `<span class="bn">${esc(l.note)}</span>` : "";
    d.innerHTML = `<div class="bandlabel" role="button" tabindex="0" aria-label="${esc("Zoom to the lane " + l.title)}"><b>${esc(l.title)}</b>${badge}${note}</div>`;
    const label = d.firstElementChild;
    on(ctx, label, "click", (e) => {
      e.stopPropagation();
      ctx.fn.zoomToBand(l.id);
    });
    on(ctx, label, "keydown", (e) => {
      if (e.key === "Enter") ctx.fn.zoomToBand(l.id);
    });
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
    d.style.left = p.x + "px";
    d.style.top = p.y + "px";
    d.style.width = p.w + "px";
    d.style.height = p.h + "px";
    on(ctx, d, "click", () => {
      if (ctx.moved > 4) return;
      ctx.fn.select(canonOf(ctx.nodes, n.id));
    });
    on(ctx, d, "dblclick", (e) => {
      e.stopPropagation();
      ctx.fn.select(canonOf(ctx.nodes, n.id));
      ctx.fn.zoomToPath();
    });
    on(ctx, d, "keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        ctx.fn.select(canonOf(ctx.nodes, n.id));
      }
    });
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
    if (!A || !B) {
      console.warn(`flow-studio: link ${l.id} skipped (an end is missing)`);
      return;
    }
    const x1 = A.x + A.w, y1 = A.y + A.h / 2, x2 = B.x, y2 = B.y + B.h / 2, tx = x1 + gap / 2;
    const loop = l.kind === "loop-back";
    const channel = ctx.geom.loops[l.id]?.channelY ?? Math.max(A.y + A.h, B.y + B.h) + 10;
    const d = loop ? loopRoute(ctx, l.from, l.to, A, B, channel) : elbow(x1, y1, x2 - 1, y2, tx);
    const path = sv("path", { d, class: "edge" + (loop ? " loop" : ""), "data-i": String(i), "data-a": l.from, "data-b": l.to, "marker-end": "url(#arr)" });
    els.layer.appendChild(path);
    ctx.edgeEls[i] = path;
    if (l.label) {
      const lab = el("div", "elabel", esc(l.label));
      lab.dataset.i = String(i);
      lab.dataset.a = l.from;
      lab.dataset.b = l.to;
      lab.style.left = (loop ? (A.x + A.w / 2 + B.x + B.w / 2) / 2 : Math.abs(y2 - y1) < 1 ? (x1 + x2) / 2 : tx) + "px";
      lab.style.top = (loop ? ctx.geom.loops[l.id]?.channelY ?? Math.max(A.y + A.h, B.y + B.h) + 10 : (y1 + y2) / 2) + "px";
      els.world.appendChild(lab);
      ctx.labelEls[i] = lab;
    }
  });
}
function paint(ctx, fromSwitch = false) {
  const { model } = ctx;
  const mode = ctx.mode;
  const effective = effectiveLinks(model, mode, ctx.collapsed, ctx.nodes);
  const effectiveById = new Map(effective.map((l) => [l.id, l]));
  ctx.geom = computeGeometry({ ...model, links: effective }, { visible: (id) => {
    const n = ctx.nodes.get(id);
    return !!n && nodeVisible(model, mode, n, ctx.collapsed);
  } });
  ctx.els.world.style.height = ctx.geom.world.h + "px";
  ctx.els.svg.setAttribute("height", String(ctx.geom.world.h));
  document.body.classList.toggle("alt", !!model.views && mode !== baselineView(model));
  for (const n of model.nodes) {
    const d = ctx.nodeEls.get(n.id);
    if (!d) continue;
    const rect = ctx.geom.nodes[n.id];
    if (rect) {
      d.style.left = rect.x + "px";
      d.style.top = rect.y + "px";
    }
    const sid = nodeStateId(model, mode, n);
    const show = nodeVisible(model, mode, n, ctx.collapsed);
    const bucket = bucketOf(model, sid);
    const cors = (isImproved(model, mode, n) ? 1 : 0) + (n.upgrade && bucket !== "good" ? 1 : 0);
    const fresh = isNew(model, mode, n);
    d.className = "node st-" + cssId(sid) + (n.kind === "chip" ? " ref" : "") + (n.kind === "gateway" ? " gateway" : "") + ((n.colSpan ?? 1) > 1 ? " wide" : "") + (n.kind === "placeholder" ? " placeholder" : "") + (show ? "" : " off") + (fresh ? " isnew" : "") + (cors ? cors > 1 ? " hascor2" : " hascor" : "") + (ctx.selected && canonOf(ctx.nodes, n.id) === ctx.selected ? " sel" : "") + (metricBadge(n.metrics) ? " has-metrics" : "");
    d.innerHTML = nodeHtml(ctx, n);
    d.setAttribute("aria-hidden", show ? "false" : "true");
    d.tabIndex = show ? 0 : -1;
    const word = model.states[sid]?.word ?? sid;
    const lane = model.lanes.find((l) => l.id === n.lane)?.title ?? n.lane;
    d.setAttribute("aria-label", n.kind === "chip" ? `${n.title}: a reference to the node in the ${lane} lane. Press Enter to select it.` : `${n.title}. ${n.subtitle ?? model.columns[n.col ?? 0]?.title ?? ""}, ${word}. Press Enter to inspect.`);
    if (fromSwitch && fresh && !ctx.reduced) {
      d.style.transitionDelay = (n.col ?? 0) * 60 + "ms";
      d.classList.add("pulse");
      window.setTimeout(() => {
        d.style.transitionDelay = "";
        d.classList.remove("pulse");
      }, 2200);
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
      p.dataset.a = edge.from;
      p.dataset.b = edge.to;
      const channel = ctx.geom.loops[edge.id]?.channelY ?? Math.max(a.y + a.h, b.y + b.h) + 10;
      p.setAttribute("d", loop ? loopRoute(ctx, edge.from, edge.to, a, b, channel) : elbow(a.x + a.w, a.y + a.h / 2, b.x - 1, b.y + b.h / 2, a.x + a.w + DEFAULTS.gap / 2));
      const lab = ctx.labelEls[i];
      if (lab) {
        lab.dataset.a = edge.from;
        lab.dataset.b = edge.to;
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
    if (r) {
      d.style.left = r.x + "px";
      d.style.top = r.y + "px";
      d.style.width = r.w + "px";
      d.style.height = r.h + "px";
    }
  }
  ctx.fn.buildChrome();
  ctx.fn.trace(ctx.selected);
  ctx.fn.renderInspector();
  ctx.fn.stickLabels();
  ctx.fn.placeHeaders();
}
function install2(ctx) {
  ctx.fn.buildWorld = () => build(ctx);
  ctx.fn.paint = (fromSwitch) => paint(ctx, fromSwitch);
}

// src/viewport.ts
var viewport_exports = {};
__export(viewport_exports, {
  K_MAX: () => K_MAX,
  K_MIN: () => K_MIN,
  clampK: () => clampK,
  clampPan: () => clampPan,
  fitRect: () => fitRect,
  fitWidth: () => fitWidth,
  zoomAt: () => zoomAt
});
var K_MIN = 0.25;
var K_MAX = 2.5;
var clampK = (k) => Number.isFinite(k) ? Math.min(K_MAX, Math.max(K_MIN, k)) : 1;
function zoomAt(v, factor, cx, cy) {
  const base = Number.isFinite(v.k) && v.k > 0 ? v.k : 1;
  const k = clampK(base * factor);
  const r = k / base;
  return { k, x: cx - (cx - v.x) * r, y: cy - (cy - v.y) * r };
}
function fitRect(rect, size, pad, top) {
  if (!(rect.w > 0 && rect.h > 0)) return { x: 0, y: 0, k: 1 };
  const aw = Math.max(1, size.w - 2 * pad);
  const ah = Math.max(1, size.h - 2 * pad - top);
  const k = Math.min(1, clampK(Math.min(aw / rect.w, ah / rect.h)));
  return { k, x: pad + (aw - rect.w * k) / 2 - rect.x * k, y: pad + top + (ah - rect.h * k) / 2 - rect.y * k };
}
function fitWidth(rect, size, pad, top) {
  if (!(rect.w > 0)) return { x: 0, y: 0, k: 1 };
  const k = Math.min(1, clampK((Math.max(1, size.w) - 2 * pad) / rect.w));
  return { k, x: pad - rect.x * k, y: top - rect.y * k };
}
function clampPan(v, bounds, size) {
  const keep = 80;
  const minX = keep - (bounds.x + bounds.w) * v.k;
  const maxX = size.w - keep - bounds.x * v.k;
  const minY = keep - (bounds.y + bounds.h) * v.k;
  const maxY = size.h - keep - bounds.y * v.k;
  return { k: v.k, x: Math.min(maxX, Math.max(minX, v.x)), y: Math.min(maxY, Math.max(minY, v.y)) };
}

// src/controls.ts
var HEAD = 44;
var ICON = {
  select: '<path d="M5 3l12 6.5-5.2 1.6L9.5 17z"/>',
  hand: '<path d="M8 11V5.5a1.5 1.5 0 013 0V10m0-5a1.5 1.5 0 013 0v5m0-3.5a1.5 1.5 0 013 0V13c0 4-2.5 7-6.5 7S5 17 5 14l-1.6-3.2a1.4 1.4 0 012.4-1.4L8 12"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  minus: '<path d="M5 12h14"/>',
  fit: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
  one: '<path d="M9 8l3-2v12"/><path d="M5 20h14"/>',
  sel: '<circle cx="12" cy="12" r="3.2"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3"/>',
  full: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>'
};
function install3(ctx) {
  const { els, model } = ctx;
  const vp = els.vp;
  let cached = { w: vp.clientWidth, h: vp.clientHeight };
  const size = () => cached;
  let vpRect = vp.getBoundingClientRect();
  const refreshRect = () => {
    vpRect = vp.getBoundingClientRect();
  };
  let animTimer = 0;
  let raf = 0;
  function applyView() {
    const v = ctx.view;
    els.world.style.transform = `translate(${v.x}px,${v.y}px) scale(${v.k})`;
    vp.style.setProperty("--inv", Math.max(1, 0.9 / v.k).toFixed(3));
    vp.style.setProperty("--k", v.k.toFixed(4));
    vp.classList.toggle("lod1", v.k < 0.62);
    vp.classList.toggle("lod2", v.k < 0.4);
    els.zoom.textContent = Math.round(v.k * 100) + "%";
    ctx.fn.stickLabels();
    ctx.fn.placeHeaders();
    if (!raf) raf = requestAnimationFrame(() => {
      raf = 0;
      if (document.body.classList.contains("notes")) ctx.fn.placeMarkers();
    });
  }
  function setView(v, animate = false) {
    const c = clampPan(v, ctx.geom.bounds, size());
    ctx.view = [c.x, c.y, c.k].every(Number.isFinite) ? c : { x: 0, y: 0, k: 1 };
    const glide = animate && !ctx.reduced;
    vp.classList.toggle("anim", glide);
    if (glide) {
      clearTimeout(animTimer);
      animTimer = window.setTimeout(() => vp.classList.remove("anim"), 330);
    }
    applyView();
  }
  function fit(animate = false, rect, inset = 0) {
    const r = rect ?? ctx.geom.bounds;
    if (!(r.w > 0)) return;
    const s = size();
    setView(fitRect(r, { w: s.w - inset, h: s.h }, 28, HEAD + 8), animate);
  }
  function fitW(animate = false) {
    setView(fitWidth(ctx.geom.bounds, size(), 28, HEAD + 8), animate);
  }
  function zoomBy(f) {
    const s = size();
    ctx.userMoved = true;
    setView(zoomAt(ctx.view, f, s.w / 2, s.h / 2), true);
    ctx.fn.announce("Zoom " + Math.round(ctx.view.k * 100) + " percent");
  }
  function placeHeaders() {
    const cols = els.cols;
    cols.style.display = model.columns.length ? "" : "none";
    if (!cols.firstChild) {
      model.columns.forEach((c, i2) => {
        const h = el("div", "hd");
        h.textContent = c.continues ? "" : (c.short ?? c.title).toUpperCase();
        h.title = c.title;
        h.dataset.i = String(i2);
        cols.appendChild(h);
      });
      let i = 0;
      while (i < model.columns.length) {
        const name = model.columns[i]?.phase;
        let j = i;
        while (j + 1 < model.columns.length && model.columns[j + 1]?.phase === name) j++;
        if (name) {
          const p = el("div", "ph");
          p.innerHTML = "<span></span><i></i>";
          p.firstElementChild.textContent = name;
          p.dataset.a = String(i);
          p.dataset.b = String(j);
          cols.appendChild(p);
        }
        i = j + 1;
      }
    }
    const v = ctx.view, xs = ctx.geom.xs;
    cols.querySelectorAll(".hd").forEach((h) => {
      const i = +(h.dataset.i ?? 0);
      h.style.left = v.x + (xs[i] ?? 0) * v.k + "px";
      h.style.width = Math.max(0, (model.columns[i]?.width ?? 0) * v.k - 6) + "px";
    });
    cols.querySelectorAll(".ph").forEach((p) => {
      const a = +(p.dataset.a ?? 0), b = +(p.dataset.b ?? 0);
      p.style.left = v.x + (xs[a] ?? 0) * v.k + "px";
      p.style.width = Math.max(40, ((xs[b] ?? 0) + (model.columns[b]?.width ?? 0) - (xs[a] ?? 0)) * v.k) + "px";
    });
  }
  function stickLabels() {
    const wl = (52 - ctx.view.x) / ctx.view.k;
    for (const l of model.lanes) {
      const r = ctx.geom.lanes[l.id], d = ctx.laneEls.get(l.id);
      if (!r || !d?.firstElementChild) continue;
      d.firstElementChild.style.left = Math.min(Math.max(12, wl - r.x), Math.max(12, r.w - 300)) + "px";
    }
  }
  const pointers = /* @__PURE__ */ new Map();
  let drag = null;
  let pinch = null;
  on(ctx, vp, "pointerdown", (e) => {
    if (e.target.closest("#tools, .bandlabel")) return;
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    ctx.moved = 0;
    if (pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      pinch = { d: Math.hypot(a.x - b.x, a.y - b.y), view: { ...ctx.view } };
      drag = null;
      return;
    }
    const onNode = !!e.target.closest(".node");
    if (e.button === 1 || ctx.tool === "hand" || ctx.spaceDown || !onNode) {
      drag = { x: e.clientX, y: e.clientY, vx: ctx.view.x, vy: ctx.view.y };
      try {
        vp.setPointerCapture(e.pointerId);
      } catch {
      }
      vp.classList.add("panning");
      if (e.button === 1) e.preventDefault();
    }
  });
  on(ctx, vp, "pointermove", (e) => {
    if (pointers.has(e.pointerId)) pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pinch && pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      const d = Math.hypot(a.x - b.x, a.y - b.y), r = vpRect;
      ctx.userMoved = true;
      setView(zoomAt(pinch.view, d / pinch.d, (a.x + b.x) / 2 - r.left, (a.y + b.y) / 2 - r.top), false);
      return;
    }
    if (!drag) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    ctx.moved = Math.max(ctx.moved, Math.hypot(dx, dy));
    if (ctx.moved > 4) {
      ctx.userMoved = true;
      setView({ k: ctx.view.k, x: drag.vx + dx, y: drag.vy + dy }, false);
    }
  });
  const endDrag = (e) => {
    pointers.delete(e.pointerId);
    if (pointers.size < 2) pinch = null;
    if (drag) {
      drag = null;
      vp.classList.remove("panning");
      try {
        vp.releasePointerCapture(e.pointerId);
      } catch {
      }
      window.setTimeout(() => {
        ctx.moved = 0;
      }, 0);
    }
  };
  on(ctx, vp, "pointerup", endDrag);
  on(ctx, vp, "pointercancel", endDrag);
  on(ctx, vp, "wheel", (e) => {
    e.preventDefault();
    const r = vpRect, unit = e.deltaMode === 1 ? 16 : 1;
    ctx.userMoved = true;
    setView(zoomAt(ctx.view, Math.exp(-e.deltaY * unit * (e.ctrlKey ? 0.01 : 12e-4)), e.clientX - r.left, e.clientY - r.top), false);
  }, { passive: false });
  on(ctx, vp, "dblclick", (e) => {
    if (!e.target.closest(".node, .bandlabel, #tools")) {
      ctx.userMoved = false;
      fit(true);
    }
  });
  on(ctx, vp, "click", (e) => {
    if (!e.target.closest(".node, .bandlabel, #tools") && ctx.moved <= 4) ctx.fn.select(null);
  });
  const ro = new ResizeObserver(() => {
    cached = { w: vp.clientWidth, h: vp.clientHeight };
    refreshRect();
    if (!ctx.userMoved) fitW(false);
    else setView(ctx.view, false);
  });
  ro.observe(vp);
  on(ctx, vp, "pointerenter", refreshRect);
  on(ctx, window, "scroll", refreshRect, { passive: true });
  ctx.disposers.push(() => ro.disconnect());
  function setTool(id) {
    ctx.tool = id;
    vp.classList.toggle("hand", id === "hand");
    els.tools.querySelectorAll("[data-id='select'], [data-id='hand']").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.id === id)));
    ctx.fn.announce(id === "hand" ? "Hand tool: drag to pan" : "Select tool");
  }
  function toggleFull() {
    const ws = els.workspace;
    if (document.fullscreenElement) void document.exitFullscreen();
    else if (ws.requestFullscreen) ws.requestFullscreen().catch(() => ws.classList.toggle("fs"));
    else ws.classList.toggle("fs");
  }
  const TOOLS = [
    ["select", "Select (V)", "tool"],
    ["hand", "Hand: drag to pan (H)", "tool"],
    ["-"],
    ["plus", "Zoom in (+)", () => zoomBy(1.25)],
    ["minus", "Zoom out (-)", () => zoomBy(1 / 1.25)],
    ["fit", "Fit to screen (0)", () => {
      ctx.userMoved = false;
      fit(true);
      ctx.fn.announce("Fit to screen");
    }],
    ["one", "Actual size (1)", () => {
      const s = size();
      ctx.userMoved = true;
      setView(zoomAt(ctx.view, 1 / ctx.view.k, s.w / 2, s.h / 2), true);
    }],
    ["sel", "Zoom to selection (F)", () => ctx.fn.zoomToPath()],
    ["-"],
    ["full", "Fullscreen", "full"]
  ];
  els.tools.innerHTML = "";
  for (const t of TOOLS) {
    if (t[0] === "-") {
      els.tools.appendChild(el("div", "sep"));
      continue;
    }
    const [id, label, act] = t;
    const b = el("button", "tb", `<svg viewBox="0 0 24 24" aria-hidden="true">${ICON[id] ?? ""}</svg>`);
    b.type = "button";
    b.title = label;
    b.setAttribute("aria-label", label);
    b.dataset.id = id;
    if (act === "tool") {
      b.setAttribute("aria-pressed", String(ctx.tool === id));
      on(ctx, b, "click", () => setTool(id));
    } else if (act === "full") on(ctx, b, "click", toggleFull);
    else on(ctx, b, "click", act);
    els.tools.appendChild(b);
  }
  requestAnimationFrame(() => {
    const r = els.tools.getBoundingClientRect(), v = vp.getBoundingClientRect();
    els.zoom.style.top = r.bottom - v.top + 6 + "px";
  });
  on(ctx, document, "fullscreenchange", () => window.setTimeout(() => {
    if (!ctx.userMoved) fitW(false);
  }, 60));
  on(ctx, document, "keydown", (e) => {
    const typing = !!e.target && /INPUT|TEXTAREA/.test(e.target.tagName);
    if (typing) {
      if (e.key === "Escape") e.target.blur();
      return;
    }
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === " " && document.activeElement === vp) {
      ctx.spaceDown = true;
      e.preventDefault();
      vp.classList.add("hand");
      return;
    }
    const k = e.key, step = e.shiftKey ? 240 : 60;
    if (k === "/") {
      e.preventDefault();
      els.q.focus();
    } else if (k === "n" || k === "N") ctx.fn.toggleNotes();
    else if (k === "v" || k === "V") setTool("select");
    else if (k === "h" || k === "H") setTool("hand");
    else if (k === "e" || k === "E") {
      const selected = ctx.selected && ctx.nodes.get(ctx.selected);
      if (selected) {
        const group = selected.kind === "group" ? selected : ctx.model.nodes.find((n) => n.kind === "group" && n.contains?.includes(selected.id));
        if (group) ctx.fn.toggleGroup(group.id);
      }
    } else if (k === "+" || k === "=") zoomBy(1.25);
    else if (k === "-" || k === "_") zoomBy(1 / 1.25);
    else if (k === "0") {
      ctx.userMoved = false;
      fit(true);
    } else if (k === "1") {
      const s = size();
      ctx.userMoved = true;
      setView(zoomAt(ctx.view, 1 / ctx.view.k, s.w / 2, s.h / 2), true);
    } else if (k === "f" || k === "F") ctx.fn.zoomToPath();
    else if (k.startsWith("Arrow") && (document.activeElement === vp || document.activeElement === document.body)) {
      e.preventDefault();
      ctx.userMoved = true;
      setView({ k: ctx.view.k, x: ctx.view.x + (k === "ArrowLeft" ? step : k === "ArrowRight" ? -step : 0), y: ctx.view.y + (k === "ArrowUp" ? step : k === "ArrowDown" ? -step : 0) }, false);
    } else if (k === "Escape") ctx.fn.escape();
  });
  on(ctx, document, "keyup", (e) => {
    if (e.key === " ") {
      ctx.spaceDown = false;
      if (ctx.tool !== "hand") vp.classList.remove("hand");
    }
  });
  ctx.fn.setView = setView;
  ctx.fn.fit = fit;
  ctx.fn.fitWidth = fitW;
  ctx.fn.zoomBy = zoomBy;
  ctx.fn.stickLabels = stickLabels;
  ctx.fn.placeHeaders = placeHeaders;
}

// src/inspector.ts
var BUCKET_COLOR = { good: "ok", neutral: "muted", gap: "warn" };
var PILL = { ok: "ok", warn: "warn", crit: "warn", info: "info", accent: "info", muted: "muted" };
function install4(ctx) {
  const { els, model } = ctx;
  const matchesFilter = (n, f) => !f || (f.col === void 0 || n.col === f.col) && (f.kind === void 0 || n.kind === f.kind);
  function wire(box) {
    box.querySelector("#hideInsp")?.addEventListener("click", () => {
      if (ctx.selected) ctx.fn.select(null);
      else {
        ctx.dismissed = true;
        ctx.fn.renderInspector();
      }
    });
    box.querySelectorAll("[data-hl]").forEach((b) => b.addEventListener("click", () => {
      ctx.hl = ctx.hl === b.dataset.hl ? null : b.dataset.hl ?? null;
      ctx.fn.trace(ctx.selected);
      ctx.fn.renderInspector();
    }));
    box.querySelectorAll("[data-g]").forEach((b) => b.addEventListener("click", () => {
      ctx.fn.select(b.dataset.g ?? null);
      ctx.fn.zoomToPath();
    }));
    box.querySelectorAll("[data-act]").forEach((b) => b.addEventListener("click", () => ctx.fn.simulate(b.dataset.act ?? "")));
    box.querySelectorAll("[data-toggle-group]").forEach((b) => b.addEventListener("click", () => ctx.fn.toggleGroup(b.dataset.toggleGroup ?? "")));
    box.querySelector("#simReset")?.addEventListener("click", () => {
      ctx.fn.clearSim();
      ctx.fn.renderInspector();
      ctx.fn.announce("Simulation reset.");
    });
    box.querySelector("#zPath")?.addEventListener("click", () => ctx.fn.zoomToPath());
    box.querySelector("#zBand")?.addEventListener("click", () => {
      const n = ctx.selected ? ctx.nodes.get(ctx.selected) : void 0;
      if (n?.lane) ctx.fn.zoomToBand(n.lane);
    });
  }
  function renderInspector() {
    const box = els.inspector, ws = els.workspace;
    const sel = ctx.selected ? ctx.nodes.get(ctx.selected) : void 0;
    const head = `<div class="insp-h"><span>Inspector</span><button type="button" id="hideInsp" aria-label="Close the inspector">Close \u2715</button></div>`;
    if (!sel) {
      const found = ctx.query && !ctx.dismissed ? model.nodes.filter((n) => nodeVisible(model, ctx.mode, n, ctx.collapsed) && matches(ctx, n)) : [];
      const open = found.length > 0;
      box.classList.toggle("open", open);
      ws.classList.toggle("inspopen", open);
      box.setAttribute("aria-hidden", String(!open));
      if (!open) return;
      const rows = found.map((f) => {
        const b = bucketOf(model, nodeStateId(model, ctx.mode, f));
        const hits = (f.members ?? []).filter((m) => m.toLowerCase().includes(ctx.query)).length;
        return `<button type="button" class="dr" data-g="${esc(f.id)}"><span class="dbar" style="background:var(--${BUCKET_COLOR[b]})"></span><span class="dtx"><span class="dn">${esc(f.title)}</span><span class="dk">${hits} match \xB7 ${esc(model.columns[f.col ?? 0]?.title ?? "")}</span></span></button>`;
      }).join("");
      box.innerHTML = head + `<div class="insp-b"><div class="insp-sec"><b>${found.length}</b> group${found.length === 1 ? "" : "s"} match \u201C${esc(ctx.query)}\u201D</div><div class="drill">${rows}</div></div>`;
      wire(box);
      return;
    }
    box.classList.add("open");
    ws.classList.add("inspopen");
    box.setAttribute("aria-hidden", "false");
    const sid = nodeStateId(model, ctx.mode, sel);
    const st = model.states[sid];
    const bucket = bucketOf(model, sid);
    const lane = model.lanes.find((l) => l.id === sel.lane);
    const counts = relationsOf(ctx).slice(0, 3).map((r) => {
      const set = relationSet(ctx, r, sel.id);
      let n = 0;
      for (const id of set) {
        const x = ctx.nodes.get(id);
        if (!x) continue;
        if (r.filter) {
          if (matchesFilter(x, r.filter)) n += Math.max(1, x.weight ?? 1);
        } else if (id !== sel.id) n += 1;
      }
      const cls = r.id === "up" ? "cn--up" : r.id === "down" ? "cn--down" : "";
      return `<button class="cbtn" data-hl="${esc(r.id)}" aria-pressed="${ctx.hl === r.id}"><span class="cn ${cls}">${n}</span><span class="cl">${esc(r.label)}</span></button>`;
    }).join("");
    const pills = `<span class="pill ${PILL[st?.tone ?? "muted"]}">${esc(st?.word ?? sid)}</span>` + (isImproved(model, ctx.mode, sel) ? '<span class="pill info">gap filled</span>' : "") + (isNew(model, ctx.mode, sel) ? '<span class="pill muted">new in this view</span>' : "");
    const actions = (model.inspector?.actions ?? []).map((a) => `<button type="button" class="danger" data-act="${esc(a.id)}">\u25B6 ${esc(a.label)}</button>`).join("");
    const members = sel.members ?? [];
    const owner = groupFor(model, sel.id);
    const foldAction = sel.kind === "group" && sel.contains?.length && ctx.collapsed.has(sel.id) ? `<button type="button" data-toggle-group="${esc(sel.id)}">Expand group</button>` : owner && !ctx.collapsed.has(owner.id) ? `<button type="button" data-toggle-group="${esc(owner.id)}">Collapse into ${esc(owner.title)}</button>` : "";
    const exits = sel.kind === "gateway" ? effectiveLinks(model, ctx.mode, ctx.collapsed, ctx.nodes).filter((l) => l.from === sel.id).map((l) => {
      const target = ctx.nodes.get(l.to);
      return `<div class="dr"><span class="dtx"><span class="dn">${esc(l.label ?? "Unlabelled")}</span><span class="dk">${esc(target?.title ?? l.to)}</span></span></div>`;
    }).join("") : "";
    const metric = sel.metrics;
    const series = metric?.series ?? [];
    const points = sparklinePoints(series, 300, 40);
    const metricHtml = metric ? `<div class="insp-sec metrics"><b>Metrics</b><table class="meta"><tr><th>label</th><td>${esc(metric.label ?? "Metric")}</td></tr><tr><th>value</th><td>${esc(String(metric.value))} ${esc(metric.unit ?? "")}</td></tr>${metric.max != null ? `<tr><th>max</th><td>${esc(String(metric.max))} ${esc(metric.unit ?? "")}</td></tr>` : ""}</table>${points ? `<svg width="300" height="40" viewBox="0 0 300 40" role="img" aria-label="Metric trend"><polyline points="${points}"/></svg><div class="metric-range"><span>${esc(String(Math.min(...series)))}</span><span>${esc(String(Math.max(...series)))}</span></div>` : ""}</div>` : "";
    box.innerHTML = head + `<div class="counts">${counts}</div>
      <div class="insp-b"><div class="insp-sec"><p class="nname">${esc(sel.title)}</p><div class="nkind">${esc(model.columns[sel.col ?? 0]?.title ?? "")} \xB7 ${esc(lane?.title ?? sel.lane)}</div><div class="pillrow">${pills}</div>${sel.subtitle ? `<p class="note">${esc(sel.subtitle)}</p>` : ""}</div>
      <div class="insp-sec"><b>Details</b><table class="meta"><tr><th>state</th><td>${esc(st?.word ?? sid)}</td></tr><tr><th>members</th><td>${Math.max(1, sel.weight ?? 1)}</td></tr><tr><th>lane</th><td>${esc(lane?.title ?? sel.lane)}${lane?.badge ? ` (${esc(lane.badge)})` : ""}</td></tr>${sel.upgrade && bucket !== "good" ? `<tr><th>can improve</th><td>${esc(sel.upgrade)}</td></tr>` : ""}</table></div>
      ${metricHtml}
      ${sel.kind === "gateway" ? `<div class="insp-sec"><b>Exits</b><div class="drill">${exits}</div></div>` : ""}
      ${members.length ? `<div class="insp-sec"><b>Members</b> (${Math.max(members.length, sel.weight ?? 0)})<input id="mq" type="search" placeholder="Filter ${members.length} members\u2026" aria-label="Filter members"><div class="drill" id="mlist"></div><p class="drill-hint" id="mcount"></p></div>` : `<div class="insp-sec"><p class="note">No member names are recorded for this group.</p></div>`}
      ${foldAction ? `<div class="acts">${foldAction}</div>` : ""}
      <div class="acts"><button type="button" id="zPath">Zoom to path</button><button type="button" id="zBand">Go to lane</button></div>
      ${actions ? `<div class="acts">${actions}<button type="button" id="simReset"${ctx.simActive ? "" : " hidden"}>Reset</button></div>` : ""}</div>`;
    wire(box);
    const mq = box.querySelector("#mq");
    const draw = () => {
      const f = (mq?.value ?? "").toLowerCase();
      const rows = members.filter((m) => m.toLowerCase().includes(f));
      const list = box.querySelector("#mlist");
      if (list) list.innerHTML = rows.slice(0, 14).map((m) => `<div class="dr"><span class="dbar" style="background:var(--${BUCKET_COLOR[bucket]})"></span><span class="dtx"><span class="dn mono" style="font-size:12px">${esc(m)}</span></span></div>`).join("");
      const cnt = box.querySelector("#mcount");
      const weight = sel.weight ?? 0;
      if (cnt) cnt.textContent = `${Math.min(14, rows.length)} of ${rows.length}${weight > members.length ? ` named (${weight} members in all)` : ""}`;
    };
    if (mq) {
      mq.addEventListener("input", draw);
      draw();
    }
  }
  ctx.fn.renderInspector = renderInspector;
}

// src/chrome.ts
var DEFAULT_LABELS = {
  tileGood: "links in a good state",
  tileNeutral: "links in a neutral state",
  tileGap: "groups with a gap: click to show",
  tileUpgrade: "groups you can improve: click to show",
  ledgerTitle: "What this view could not establish",
  tableTitle: "Table view"
};
function install5(ctx) {
  const { els, model } = ctx;
  const label = (k) => model.meta.labels?.[k] ?? DEFAULT_LABELS[k] ?? k;
  const visible = (id) => {
    const n = ctx.nodes.get(id);
    return !!n && nodeVisible(model, ctx.mode, n, ctx.collapsed);
  };
  function countUp(node, to, ms = 700) {
    if (ctx.reduced) {
      node.textContent = String(to);
      return;
    }
    const t0 = performance.now();
    const step = (t) => {
      const k = Math.min(1, (t - t0) / ms), e = 1 - Math.pow(1 - k, 3);
      node.textContent = String(Math.round(to * e));
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }
  function buildStrip() {
    const box = els.strip;
    const heads = stripHeads(model), cells = model.columns.map((c, i) => ({ c, i })).filter(({ i }) => heads[i] === i);
    box.style.display = model.columns.length ? "" : "none";
    box.style.gridTemplateColumns = `repeat(${Math.max(1, cells.length)}, minmax(0, 1fr))`;
    if (!box.firstChild) {
      box.innerHTML = cells.map(({ c }) => `<div class="lcell"><div class="ln">${esc(c.title)}</div><div class="lb"><i class="good"></i><i class="neutral"></i><i class="gap"></i></div><div class="lv"></div></div>`).join("");
    }
    box.querySelectorAll(".lcell").forEach((cell, cellIndex) => {
      const i = cells[cellIndex]?.i ?? cellIndex;
      cell.style.setProperty("--i", String(cellIndex));
      let tot = 0, good = 0, neutral = 0, gap = 0;
      for (const n of model.nodes) {
        if (heads[n.col ?? -1] !== i || n.kind === "chip") continue;
        if (!visible(n.id)) continue;
        const w = Math.max(1, n.weight ?? 1);
        tot += w;
        const b = bucketOf(model, nodeStateId(model, ctx.mode, n));
        if (b === "good") good += w;
        else if (b === "neutral") neutral += w;
        else gap += w;
      }
      const t = tot || 1, bars = cell.querySelectorAll("i");
      requestAnimationFrame(() => {
        if (bars[0]) bars[0].style.width = good / t * 100 + "%";
        if (bars[1]) bars[1].style.width = neutral / t * 100 + "%";
        if (bars[2]) bars[2].style.width = gap / t * 100 + "%";
      });
      const lv = cell.querySelector(".lv");
      if (lv) lv.textContent = `${good + neutral} / ${tot}`;
      cell.title = `${model.columns[i]?.title ?? ""}: ${good} good, ${neutral} neutral, ${gap} gap`;
    });
  }
  function buildTiles() {
    const k = els.tiles;
    let good = 0, neutral = 0;
    for (const l of effectiveLinks(model, ctx.mode, ctx.collapsed, ctx.nodes)) {
      const b = bucketOf(model, l.state);
      if (b === "good") good++;
      else if (b === "neutral") neutral++;
    }
    let gaps = 0, upgrades = 0;
    for (const n of model.nodes) {
      if (!visible(n.id) || n.kind === "chip") continue;
      const b = bucketOf(model, nodeStateId(model, ctx.mode, n));
      if (b === "gap") gaps += 1;
      if (n.upgrade && b !== "good") upgrades++;
    }
    k.innerHTML = "";
    const tile = (cls, n, text, filter) => {
      const b = el(filter ? "button" : "div", "tile " + cls, `<span class="tn">0</span><span class="tl">${esc(text)}</span>`);
      b.style.setProperty("--i", String(k.children.length + 9));
      if (filter) {
        b.type = "button";
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
      countUp(b.querySelector(".tn"), n);
    };
    tile("ok", good, label("tileGood"));
    tile("", neutral, label("tileNeutral"));
    tile("warn", gaps, label("tileGap"), "gap");
    tile("", upgrades, label("tileUpgrade"), "upgrade");
  }
  function buildLegend() {
    const parts = Object.entries(model.states).map(([id, s]) => {
      const cap = s.edge === "dot" ? ' stroke-linecap="round"' : "";
      return `<span><svg width="40" height="10" aria-hidden="true"><path d="M0 5 H40" stroke="${toneVar(s.tone)}" stroke-width="2" stroke-dasharray="${DASH[s.edge]}"${cap}/></svg><b class="ev st-${cssId(id)}">${esc(s.word)}</b></span>`;
    });
    parts.push('<span id="hintline">scroll = zoom \xB7 drag = pan \xB7 double-click = fit</span>');
    els.legend.innerHTML = parts.join("");
  }
  function buildLedger() {
    let gaps = 0, total = 0;
    for (const n of model.nodes) {
      if (n.kind === "chip" || !visible(n.id)) continue;
      total++;
      if (bucketOf(model, nodeStateId(model, ctx.mode, n)) === "gap") gaps++;
    }
    const noLane = model.lanes.filter((l) => l.gap).length;
    els.ledger.innerHTML = `<h4>${esc(label("ledgerTitle"))}</h4><p><b>${gaps}</b> of <b>${total}</b> groups in this view have a gap: they are drawn dotted and are never guessed. ${noLane ? `<b>${noLane}</b> lane${noLane === 1 ? " has" : "s have"} no source document yet.` : ""}</p><p>${esc(model.meta.source)}</p>`;
  }
  function buildTable() {
    const rows = model.nodes.filter((n) => visible(n.id) && n.kind !== "chip").map((n) => {
      const sid = nodeStateId(model, ctx.mode, n);
      const lane = model.lanes.find((l) => l.id === n.lane)?.title ?? n.lane;
      return `<tr><th scope="row">${esc(columnTitle(model, n))}</th><td>${esc(lane)}</td><td>${esc(n.title)}</td><td>${esc(model.states[sid]?.word ?? sid)}</td><td>${Math.max(1, n.weight ?? 1)}</td><td>${esc(n.subtitle ?? "")}</td><td>${esc(n.upgrade ?? "")}</td></tr>`;
    }).join("");
    els.table.innerHTML = `<thead><tr><th scope="col">Column</th><th scope="col">Lane</th><th scope="col">Group</th><th scope="col">State</th><th scope="col">Members</th><th scope="col">Detail</th><th scope="col">Can improve</th></tr></thead><tbody>${rows}</tbody>`;
  }
  ctx.fn.buildChrome = () => {
    buildStrip();
    buildTiles();
    buildTable();
    buildLedger();
  };
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
    b.type = "button";
    b.setAttribute("role", "tab");
    b.dataset.mode = v.id;
    b.setAttribute("aria-selected", String(v.id === ctx.mode));
    b.textContent = v.label;
    on(ctx, b, "click", () => {
      els.modeSwitch.querySelectorAll("button").forEach((x) => x.setAttribute("aria-selected", String(x === b)));
      ctx.fn.setMode(v.id);
    });
    els.modeSwitch.appendChild(b);
  }
  on(ctx, els.q, "input", (e) => {
    ctx.query = e.target.value.trim().toLowerCase();
    ctx.dismissed = false;
    const n = model.nodes.filter((x) => visible(x.id) && matches(ctx, x)).length;
    els.matchinfo.textContent = ctx.query ? `${n} group${n === 1 ? "" : "s"} match` : "";
    if (!ctx.selected) {
      ctx.fn.trace(null);
      ctx.fn.renderInspector();
    }
  });
  on(ctx, els.hops, "change", () => {
    ctx.hops = Number(els.hops.value);
    ctx.fn.trace(ctx.selected);
  });
  on(ctx, els.q, "keydown", (e) => {
    if (e.key !== "Enter" || !ctx.query) return;
    const ids = model.nodes.filter((x) => visible(x.id) && matches(ctx, x)).map((x) => x.id);
    const r = ctx.fn.rectOf(ids);
    if (r) {
      ctx.userMoved = true;
      ctx.fn.fit(true, r, els.inspector.classList.contains("open") ? 340 : 0);
      ctx.fn.announce(`Zoomed to ${ids.length} matching groups`);
    }
  });
  on(ctx, els.theme, "click", () => {
    const r = document.documentElement;
    const dark = r.dataset.theme ? r.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    r.dataset.theme = dark ? "light" : "dark";
  });
}

// src/notes.ts
function install6(ctx) {
  const { els, model } = ctx;
  const notes = ctx.notes.map((n, i) => ({ id: i + 1, ...n }));
  const card = (id) => els.notelist.querySelector(`[data-n="${id}"]`);
  const anchorOf = (sel) => {
    try {
      return document.querySelector(sel);
    } catch {
      return null;
    }
  };
  function clearMarkers() {
    document.querySelectorAll(".marker").forEach((m) => m.remove());
    document.querySelectorAll(".anchored").forEach((a) => a.classList.remove("anchored"));
  }
  function placeMarkers() {
    clearMarkers();
    for (const n of notes) {
      const a = anchorOf(n.anchor);
      if (!a) continue;
      let r = a.getBoundingClientRect();
      if (!r.width && !r.height) {
        let d = a.closest("details");
        while (d && d.open) d = d.parentElement?.closest("details") ?? null;
        if (d) r = d.getBoundingClientRect();
      }
      if (!r.width && !r.height) continue;
      if (a.id === "inspector" && !a.classList.contains("open")) {
        const vr = els.vp.getBoundingClientRect();
        r = { left: vr.right - 130, top: vr.top + 56, right: vr.right - 128, bottom: vr.top + 58, width: 2, height: 2, x: 0, y: 0, toJSON: () => ({}) };
      }
      const v = els.vp.getBoundingClientRect();
      if (a.closest("#world") && (r.right < v.left || r.left > v.right || r.bottom < v.top || r.top > v.bottom)) continue;
      const m = el("button", "marker", String(n.id));
      m.type = "button";
      m.dataset.n = String(n.id);
      m.title = n.title;
      m.setAttribute("aria-label", `Note ${n.id}: ${n.title}`);
      m.style.left = r.left + scrollX - 10 + "px";
      m.style.top = r.top + scrollY - 10 + "px";
      m.addEventListener("mouseenter", () => {
        a.classList.add("anchored");
        card(n.id)?.classList.add("on");
      });
      m.addEventListener("mouseleave", () => {
        a.classList.remove("anchored");
        card(n.id)?.classList.remove("on");
      });
      m.addEventListener("click", () => card(n.id)?.scrollIntoView({ block: "center", behavior: ctx.reduced ? "auto" : "smooth" }));
      document.body.appendChild(m);
    }
  }
  function toggleNotes(next) {
    const on_ = next === void 0 ? !document.body.classList.contains("notes") : next;
    document.body.classList.toggle("notes", on_);
    els.notesBtn.setAttribute("aria-pressed", String(on_));
    if (on_) window.setTimeout(placeMarkers, ctx.reduced ? 30 : 340);
    else clearMarkers();
  }
  els.notelist.innerHTML = notes.map((n) => `<div class="ncard" data-n="${n.id}"><b><span>${n.id}</span>${esc(n.title)}</b>${esc(n.text)}</div>`).join("") || '<p class="note">This page has no implementation notes.</p>';
  els.notelist.querySelectorAll(".ncard").forEach((c) => {
    c.addEventListener("mouseenter", () => {
      const n = notes.find((x) => String(x.id) === c.dataset.n);
      const a = n && anchorOf(n.anchor);
      if (a) a.classList.add("anchored");
    });
    c.addEventListener("mouseleave", () => document.querySelectorAll(".anchored").forEach((a) => a.classList.remove("anchored")));
  });
  on(ctx, els.notesBtn, "click", () => toggleNotes());
  on(ctx, window, "scroll", () => {
    if (document.body.classList.contains("notes")) placeMarkers();
  }, { passive: true });
  const markdown = () => {
    const out = [`# ${model.meta.title}`, "", model.meta.help, "", `As of ${model.meta.asOf}. Source: ${model.meta.source}`, "", "## States"];
    for (const [id, s] of Object.entries(model.states)) out.push(`- **${s.word}** (${id}): tone ${s.tone}, border ${s.border}, link ${s.edge}, motion ${s.motion}, bucket ${s.bucket}`);
    out.push("", "## Columns", ...model.columns.filter((c) => !c.continues).map((c, i) => `${i + 1}. ${c.title}${c.phase ? ` (${c.phase})` : ""}`));
    out.push("", "## Lanes", ...model.lanes.map((l) => `- ${l.title}${l.badge ? ` [${l.badge}]` : ""}${l.note ? `: ${l.note}` : ""}`));
    out.push("", `## Size`, `${model.nodes.length} nodes, ${model.links.length} links.`);
    if (notes.length) out.push("", "## Notes", ...notes.map((n) => `${n.id}. **${n.title}**: ${n.text}`));
    return out.join("\n");
  };
  const rows = (items) => `<ul>${items.map((i) => `<li>${i}</li>`).join("")}</ul>`;
  els.specbody.innerHTML = `<div class="specbtns"><button type="button" id="cpMd">Copy as Markdown</button><button type="button" id="cpJson">Copy model JSON</button><span class="note" id="cpMsg" style="margin:0"></span></div>
    <h3>States</h3>${rows(Object.entries(model.states).map(([id, s]) => `<b>${esc(s.word)}</b> (<code>${esc(id)}</code>): tone ${esc(s.tone)}, border ${esc(s.border)}, link ${esc(s.edge)}, motion ${esc(s.motion)}, bucket ${esc(s.bucket)}`))}
    <h3>Columns</h3>${rows(model.columns.map((c) => `${esc(c.title)}${c.phase ? ` (${esc(c.phase)})` : ""}`))}
    <h3>Lanes</h3>${rows(model.lanes.map((l) => `${esc(l.title)}${l.badge ? ` [${esc(l.badge)}]` : ""}${l.note ? `: ${esc(l.note)}` : ""}`))}
    <h3>Size</h3><p>${model.nodes.length} nodes, ${model.links.length} links.</p>`;
  const msg = (t) => {
    const m = document.getElementById("cpMsg");
    if (m) m.textContent = t;
  };
  const copy = async (text, what) => {
    try {
      await navigator.clipboard.writeText(text);
      msg(`${what} copied.`);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
        msg(`${what} copied.`);
      } catch {
        msg("Copy is blocked here: select the text instead.");
      }
      ta.remove();
    }
  };
  document.getElementById("cpMd")?.addEventListener("click", () => void copy(markdown(), "Markdown"));
  document.getElementById("cpJson")?.addEventListener("click", () => void copy(JSON.stringify(model, null, 2), "JSON"));
  ctx.fn.toggleNotes = toggleNotes;
  ctx.fn.placeMarkers = placeMarkers;
}

// src/playback.ts
var playback_exports = {};
__export(playback_exports, {
  buildManualRoute: () => buildManualRoute,
  exitsOf: () => exitsOf,
  extendScenarioWithRoute: () => extendScenarioWithRoute,
  formatElapsed: () => formatElapsed,
  planScenario: () => planScenario,
  positionAt: () => positionAt,
  slaState: () => slaState,
  suggestedExit: () => suggestedExit
});
function planScenario(model, scenario) {
  const source = scenario.steps ?? [];
  const mode = source.some((s) => s?.at !== void 0) ? "elapsed" : "none";
  const start = source[0]?.at ?? 0;
  const scale = mode === "elapsed" ? Math.max(1, ...source.slice(1).map((s, i) => {
    const gap = ((s?.at ?? 0) - (source[i]?.at ?? 0)) * 1e3;
    return gap > 0 ? (source[i]?.dur ?? 900) / gap : 1;
  })) : 1;
  const steps = [];
  for (let i = 0; i < source.length; i++) {
    const s = source[i];
    if (!s || typeof s !== "object") continue;
    const link = model.links.find((l) => l.id === s.link);
    if (!link) continue;
    const from = model.nodes.find((n) => n.id === link.from);
    const to = model.nodes.find((n) => n.id === link.to);
    const dur = Number.isFinite(s.dur) && (s.dur ?? 0) > 0 ? s.dur : 900;
    const proposed = mode === "elapsed" ? Math.max(0, ((s.at ?? 0) - start) * 1e3 * scale) : 0;
    const at = steps.length === 0 ? 0 : Math.max(proposed, steps.at(-1).at + steps.at(-1).dur);
    steps.push({ link: s.link, from: from?.ref ?? link.from, to: to?.ref ?? link.to, at, dur, caption: s.caption ?? `${from?.title ?? link.from} to ${to?.title ?? link.to}`, index: i });
  }
  return { steps, mode, totalMs: steps.length ? steps.at(-1).at + steps.at(-1).dur : 0 };
}
function positionAt(plan, tMs) {
  if (!plan.steps.length) return { stepIndex: -1, progress: 0, done: true };
  const t = Number.isNaN(tMs) ? 0 : Math.max(0, tMs);
  if (t >= plan.totalMs) return { stepIndex: plan.steps.length - 1, progress: 1, done: true };
  let i = plan.steps.length - 1;
  while (i > 0 && t < plan.steps[i].at) i--;
  const s = plan.steps[i];
  return { stepIndex: i, progress: Math.max(0, Math.min(1, (t - s.at) / s.dur)), done: false };
}
function slaState(elapsedSec, sla) {
  if (elapsedSec >= sla) return "breach";
  return elapsedSec >= sla * 0.8 ? "warn" : "ok";
}
function formatElapsed(sec) {
  const n = Math.max(0, Math.round(Number.isFinite(sec) ? sec : 0));
  const m = Math.floor(n / 60), s = String(n % 60).padStart(2, "0");
  return n < 3600 ? `${m}:${s}` : `${Math.floor(n / 3600)}:${String(m % 60).padStart(2, "0")}:${s}`;
}
function exitsOf(model, nodeId) {
  const canon = (id) => model.nodes.find((n) => n.id === id)?.ref ?? id;
  return model.links.filter((l) => canon(l.from) === canon(nodeId));
}
function suggestedExit(exits, nextLink) {
  return exits.find((l) => l.id === nextLink);
}
function buildManualRoute(model, choiceLink) {
  const route = [choiceLink];
  const seen = /* @__PURE__ */ new Set([choiceLink.id]);
  let at = choiceLink.to;
  while (exitsOf(model, at).length === 1) {
    const next = exitsOf(model, at)[0];
    if (seen.has(next.id)) break;
    route.push(next);
    seen.add(next.id);
    at = next.to;
  }
  return route;
}
function extendScenarioWithRoute(scenario, plan, stepIndex, route) {
  const isElapsed = plan.mode === "elapsed" || scenario.steps.some((s) => s?.at !== void 0);
  const prefix = scenario.steps.slice(0, stepIndex + 1).map((s) => ({ ...s }));
  for (let i = prefix.length; i <= stepIndex && i < plan.steps.length; i++) {
    const ps = plan.steps[i];
    prefix.push({ link: ps.link, dur: ps.dur, caption: ps.caption });
  }
  let lastAt = 0;
  if (isElapsed) {
    const lastWithAt = [...prefix].reverse().find((s) => s?.at !== void 0);
    lastAt = lastWithAt?.at ?? 0;
  }
  const newSteps = route.map((l) => {
    const step = { link: l.id };
    if (isElapsed) {
      lastAt += 1;
      step.at = lastAt;
    }
    return step;
  });
  return {
    ...scenario,
    steps: [...prefix, ...newSteps]
  };
}

// src/playbackui.ts
function install7(ctx) {
  const e = ctx.els;
  const scenarios = ctx.model.scenarios ?? [];
  e.playbar.hidden = !scenarios.length;
  e.pbScenario.replaceChildren(...scenarios.map((s) => {
    const o = document.createElement("option");
    o.value = s.id;
    o.textContent = s.label;
    return o;
  }));
  let scenario = scenarios[0];
  let plan = scenario ? planScenario(ctx.model, scenario) : { steps: [], mode: "none", totalMs: 0 };
  let t = 0, idx = -1, playing = false, frame = 0, timer = 0, stamp = 0, choicesKey = "";
  let markedEdges = [];
  let markedNodes = [];
  const token = sv("circle", { id: "token", class: "token", r: "6" });
  e.layer.appendChild(token);
  const pathOf = (link) => ctx.edgeEls[ctx.links.findIndex((l) => l.id === link)];
  const nodeOf = (id) => ctx.nodeEls.get(id);
  const clearMarks = () => {
    for (const p of markedEdges) p.classList.remove("playing", "visited");
    for (const n of markedNodes) n.classList.remove("playing", "visited");
    markedEdges = [];
    markedNodes = [];
  };
  function stop() {
    playing = false;
    cancelAnimationFrame(frame);
    clearTimeout(timer);
    document.body.classList.remove("playing");
    e.pbPlay.setAttribute("aria-label", "Play");
    e.pbPlay.textContent = "\u25B6";
  }
  function pause() {
    if (!playing) return;
    stop();
    const p = positionAt(plan, t);
    draw(p.stepIndex, ctx.reduced ? 1 : p.progress);
  }
  function choices(step2) {
    if (playing || !step2) {
      if (choicesKey !== "") {
        e.pbChoices.replaceChildren();
        choicesKey = "";
      }
      return;
    }
    const key = `${scenario?.id ?? ""}|${idx}|${plan.steps.length}|${plan.steps[idx + 1]?.link ?? ""}`;
    if (key === choicesKey) return;
    choicesKey = key;
    e.pbChoices.replaceChildren();
    const exits = exitsOf(ctx.model, step2.to);
    if (exits.length < 2) return;
    const suggested = suggestedExit(exits, plan.steps[idx + 1]?.link);
    for (const link of exits) {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = link.label ?? ctx.nodes.get(link.to)?.title ?? link.to;
      b.dataset.link = link.id;
      if (link.id === suggested?.id) b.classList.add("suggested");
      b.addEventListener("click", () => {
        if (!scenario) return;
        const route = buildManualRoute(ctx.model, link);
        scenario = extendScenarioWithRoute(scenario, plan, idx, route);
        plan = planScenario(ctx.model, scenario);
        t = plan.steps[idx + 1]?.at ?? 0;
        play();
      });
      e.pbChoices.appendChild(b);
    }
  }
  function draw(stepIndex, progress) {
    const step2 = plan.steps[stepIndex];
    clearMarks();
    if (!step2) {
      token.style.display = "none";
      return;
    }
    token.style.display = "";
    for (let i = 0; i < stepIndex; i++) {
      const s = plan.steps[i];
      const p = pathOf(s.link);
      if (p) {
        p.classList.add("visited");
        markedEdges.push(p);
      }
      const n = nodeOf(s.to);
      if (n) {
        n.classList.add("visited");
        markedNodes.push(n);
      }
    }
    const path = pathOf(step2.link);
    if (path) {
      path.classList.add("playing");
      markedEdges.push(path);
    }
    const node = nodeOf(step2.to);
    if (node) {
      node.classList.add("playing");
      markedNodes.push(node);
    }
    if (path && !path.classList.contains("off")) {
      const p = path.getPointAtLength(path.getTotalLength() * progress);
      token.setAttribute("cx", String(p.x));
      token.setAttribute("cy", String(p.y));
    } else token.style.display = "none";
    e.pbCaption.textContent = step2.caption;
    e.pbScrub.value = String(plan.totalMs ? Math.round(t / plan.totalMs * 1e3) : 0);
    e.pbScrub.setAttribute("aria-valuetext", `Step ${stepIndex + 1} of ${plan.steps.length}: ${step2.caption}`);
    e.pbCounter.className = "";
    e.pbCounter.hidden = plan.mode === "none";
    if (plan.mode === "elapsed") {
      const sec = scenario?.steps[step2.index]?.at ?? 0;
      const sla = ctx.nodes.get(step2.to)?.sla;
      e.pbCounter.textContent = sla === void 0 ? formatElapsed(sec) : `${formatElapsed(sec)} / ${formatElapsed(sla)}`;
      if (sla !== void 0) e.pbCounter.classList.add(slaState(sec, sla));
    }
    if (idx !== stepIndex) ctx.fn.announce(step2.caption);
    idx = stepIndex;
    choices(step2);
  }
  function rewind() {
    stop();
    t = 0;
    idx = -1;
    clearMarks();
    choicesKey = "";
    e.pbCaption.textContent = "";
    e.pbCounter.hidden = true;
    e.pbCounter.className = "";
    e.pbChoices.replaceChildren();
    token.style.display = "none";
    e.pbScrub.value = "0";
    e.pbScrub.setAttribute("aria-valuetext", "");
  }
  function select(id) {
    scenario = scenarios.find((s) => s.id === id) ?? scenarios[0];
    plan = scenario ? planScenario(ctx.model, scenario) : { steps: [], mode: "none", totalMs: 0 };
    e.pbScenario.value = scenario?.id ?? "";
    rewind();
  }
  function seek(value) {
    stop();
    t = Math.max(0, Math.min(plan.totalMs, Number.isFinite(value) ? value : 0));
    const p = positionAt(plan, t);
    draw(p.stepIndex, ctx.reduced ? 1 : p.progress);
  }
  function tick(now) {
    if (!playing) return;
    if (!stamp) stamp = now;
    const delta = (now - stamp) * Number(e.pbSpeed.value || 1);
    stamp = now;
    t = Math.min(plan.totalMs, t + delta);
    const p = positionAt(plan, t);
    if (p.done) {
      stop();
      draw(p.stepIndex, 1);
      return;
    }
    draw(p.stepIndex, p.progress);
    frame = requestAnimationFrame(tick);
  }
  function reducedStep() {
    if (!playing) return;
    const next = Math.min(plan.steps.length - 1, idx + 1);
    if (next < 0) {
      stop();
      return;
    }
    t = plan.steps[next].at + plan.steps[next].dur;
    if (next === plan.steps.length - 1) stop();
    draw(next, 1);
    if (playing) timer = window.setTimeout(reducedStep, 1e3 / Number(e.pbSpeed.value || 1));
  }
  function play(id) {
    if (id && id !== scenario?.id) select(id);
    stop();
    if (!plan.steps.length) return;
    if (t >= plan.totalMs) {
      t = 0;
      idx = -1;
    }
    playing = true;
    document.body.classList.add("playing");
    e.pbPlay.setAttribute("aria-label", "Pause");
    e.pbPlay.textContent = "\u275A\u275A";
    e.pbChoices.replaceChildren();
    choicesKey = "";
    if (ctx.reduced) reducedStep();
    else {
      stamp = 0;
      frame = requestAnimationFrame(tick);
    }
  }
  function step() {
    stop();
    const next = Math.min(idx + 1, plan.steps.length - 1);
    if (next < 0) return;
    t = plan.steps[next].at + plan.steps[next].dur;
    draw(next, 1);
  }
  on(ctx, e.pbScenario, "change", () => select(e.pbScenario.value));
  on(ctx, e.pbPlay, "click", () => playing ? pause() : play());
  on(ctx, e.pbStep, "click", step);
  on(ctx, e.pbReset, "click", () => rewind());
  on(ctx, e.pbScrub, "input", () => seek(Number(e.pbScrub.value) / 1e3 * plan.totalMs));
  on(ctx, document, "keydown", (event) => {
    if (event.ctrlKey || event.metaKey || event.altKey || event.target instanceof HTMLElement && (event.target.isContentEditable || /INPUT|TEXTAREA|SELECT/.test(event.target.tagName))) return;
    if (event.key.toLowerCase() === "p") {
      event.preventDefault();
      playing ? pause() : play();
    }
    if (event.key === ".") {
      event.preventDefault();
      step();
    }
  });
  ctx.disposers.push(() => {
    stop();
    token.remove();
  });
  select(scenario?.id ?? "");
  return {
    play,
    pause,
    step,
    seek,
    playback: () => ({ scenario: scenario?.id ?? null, step: idx, playing, t }),
    restore: (state) => {
      if (!state.scenario || !scenarios.some((s) => s.id === state.scenario)) return;
      select(state.scenario);
      const current = plan.steps[state.step];
      if (!current) return;
      t = Math.max(current.at, Math.min(current.at + current.dur, state.t));
      draw(state.step, ctx.reduced ? 1 : current.dur > 0 ? (t - current.at) / current.dur : 1);
      if (state.playing) play();
    },
    reset: () => rewind()
  };
}

// src/diff.ts
var diff_exports = {};
__export(diff_exports, {
  diffModels: () => diffModels
});
var fields = ["state", "stateIn", "title", "subtitle", "weight", "metrics", "visibleIn", "lane", "sla"];
function stableStringify(val) {
  if (val === void 0) return "undefined";
  if (val === null) return "null";
  if (typeof val === "number") return Number.isFinite(val) ? JSON.stringify(val) : String(val);
  if (typeof val === "bigint") return String(val);
  if (typeof val === "object") {
    if (Array.isArray(val)) return `[${val.map(stableStringify).join(",")}]`;
    const rec = val;
    const keys = Object.keys(rec).filter((k) => rec[k] !== void 0).sort();
    return `{${keys.map((k) => `${JSON.stringify(k)}:${stableStringify(rec[k])}`).join(",")}}`;
  }
  return JSON.stringify(val) ?? "undefined";
}
function diffModels(a, b) {
  const old = new Map(a.nodes.map((n) => [n.id, n]));
  const now = new Map(b.nodes.map((n) => [n.id, n]));
  return {
    added: b.nodes.filter((n) => !old.has(n.id)).map((n) => n.id),
    removed: a.nodes.filter((n) => !now.has(n.id)).map((n) => n.id),
    changed: b.nodes.filter((n) => {
      const prev = old.get(n.id);
      return prev && fields.some((k) => stableStringify(prev[k]) !== stableStringify(n[k]));
    }).map((n) => n.id)
  };
}

// src/engine.ts
var IDS = {
  vp: "viewport",
  world: "world",
  svg: "edges",
  layer: "edgeLayer",
  cols: "cols",
  tools: "tools",
  zoom: "zoomLabel",
  inspector: "inspector",
  workspace: "workspace",
  live: "live",
  strip: "layerstrip",
  tiles: "kpis",
  legend: "legend",
  ledger: "ledger",
  table: "tbl",
  q: "q",
  hops: "hops",
  matchinfo: "matchinfo",
  modeSwitch: "modeSwitch",
  drawer: "drawer",
  notelist: "notelist",
  notesBtn: "notesBtn",
  theme: "theme",
  specbody: "specbody",
  spec: "spec",
  title: "title",
  readat: "readat",
  help: "help",
  footer: "footer",
  playbar: "playbar",
  pbScenario: "pbScenario",
  pbPlay: "pbPlay",
  pbStep: "pbStep",
  pbReset: "pbReset",
  pbSpeed: "pbSpeed",
  pbScrub: "pbScrub",
  pbCaption: "pbCaption",
  pbCounter: "pbCounter",
  pbChoices: "pbChoices",
  banner: "banner"
};
function findEls(root) {
  const out = {};
  for (const [key, id] of Object.entries(IDS)) {
    const e = root.querySelector("#" + id);
    if (!e) throw new Error(`flow-studio: the page has no element #${id}`);
    out[key] = e;
  }
  return out;
}
function mount(root, model, opts = {}) {
  if (!model || !Array.isArray(model.columns) || !Array.isArray(model.lanes) || !Array.isArray(model.nodes) || !Array.isArray(model.links) || !model.states) {
    throw new Error("flow-studio: the model needs columns, lanes, states, nodes and links");
  }
  if (model.layout === "auto") model = autoLayout(model);
  const els = findEls(root);
  const issues = validateModel(model);
  const errors = issues.filter((i) => i.level === "error");
  for (const i of issues) (i.level === "error" ? console.error : console.warn)(`flow-studio ${i.code} ${i.where}: ${i.message}`);
  if (errors.length) els.help.textContent = `${errors.length} model error(s). See the console. The page shows what it can.`;
  const rm = matchMedia("(prefers-reduced-motion: reduce)");
  const ctx = {
    model,
    root,
    els,
    onSelect: opts.onSelect,
    notes: opts.notes && opts.notes.length ? opts.notes : model.notes ?? [],
    nodes: new Map(model.nodes.map((n) => [n.id, n])),
    links: model.links,
    geom: { xs: [], nodes: {}, lanes: {}, loops: {}, bounds: { x: 0, y: 0, w: 1, h: 1 }, world: { w: 1, h: 1 } },
    view: { x: 0, y: 0, k: 1 },
    reduced: rm.matches,
    mode: opts.restore && (model.views?.some((v) => v.id === opts.restore.mode) || !model.views?.length && opts.restore.mode === "all") ? opts.restore.mode : defaultView(model),
    collapsed: opts.restore ? new Set(model.nodes.filter((n) => n.kind === "group" && n.contains && (opts.restore.collapsed.has(n.id) || !opts.restore.knownGroups.has(n.id) && n.collapsed !== false)).map((n) => n.id)) : initialCollapsed(model),
    selected: opts.restore?.selected && model.nodes.some((n) => n.id === opts.restore.selected) ? opts.restore.selected : null,
    hl: null,
    query: opts.restore?.query ?? "",
    hops: opts.restore?.hops ?? 0,
    filter: opts.restore?.filter ?? null,
    tool: "select",
    spaceDown: false,
    userMoved: false,
    dismissed: false,
    simActive: false,
    moved: 0,
    nodeEls: /* @__PURE__ */ new Map(),
    laneEls: /* @__PURE__ */ new Map(),
    edgeEls: [],
    labelEls: [],
    overlays: [],
    simTimers: [],
    disposers: [],
    fn: {}
  };
  const onRm = (e) => {
    ctx.reduced = e.matches;
  };
  rm.addEventListener("change", onRm);
  ctx.disposers.push(() => rm.removeEventListener("change", onRm));
  let style = document.getElementById("state-css");
  if (!style) {
    style = document.createElement("style");
    style.id = "state-css";
    document.head.prepend(style);
  }
  style.textContent = stateCss(model.states);
  install(ctx);
  install2(ctx);
  install3(ctx);
  install4(ctx);
  install5(ctx);
  install6(ctx);
  els.q.value = ctx.query;
  els.hops.value = String(ctx.hops);
  ctx.fn.buildWorld();
  ctx.fn.paint(false);
  const playback = install7(ctx);
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
    document.body.classList.add("intro");
    const introTimer = window.setTimeout(() => document.body.classList.remove("intro"), 2100);
    ctx.disposers.push(() => {
      window.clearTimeout(introTimer);
      document.body.classList.remove("intro");
    });
    ctx.fn.fitWidth(false);
    const fitTimer = window.setTimeout(() => {
      if (!ctx.userMoved) ctx.fn.fitWidth(false);
    }, 120);
    ctx.disposers.push(() => window.clearTimeout(fitTimer));
  }
  const api = {
    model,
    geometry: () => ctx.geom,
    view: () => ({ ...ctx.view }),
    setView: (v, animate) => ctx.fn.setView(v, animate),
    fit: (animate) => {
      ctx.userMoved = false;
      ctx.fn.fit(animate);
    },
    select: (id) => ctx.fn.select(id),
    selected: () => ctx.selected,
    mode: () => ctx.mode,
    setMode: (id) => ctx.fn.setMode(id),
    simulate: (id) => ctx.fn.simulate(id),
    resetSimulation: () => {
      ctx.fn.clearSim();
      ctx.fn.renderInspector();
    },
    play: (id) => playback.play(id),
    pause: () => playback.pause(),
    step: () => playback.step(),
    seek: (t) => playback.seek(t),
    playback: () => playback.playback(),
    update: (nextModel, updateOpts) => {
      const prepared = nextModel.layout === "auto" ? autoLayout(nextModel) : nextModel;
      const nextIssues = validateModel(prepared);
      const count = nextIssues.filter((i) => i.level === "error").length;
      if (count) {
        els.banner.textContent = `Update failed: ${count} errors. Showing the last good graph.`;
        els.banner.hidden = false;
        return { ok: false, issues: nextIssues };
      }
      const changes = diffModels(ctx.model, prepared);
      const saved = { view: { ...ctx.view }, mode: ctx.mode, selected: ctx.selected, inspectorOpen: els.inspector.classList.contains("open"), query: ctx.query, hops: ctx.hops, filter: ctx.filter, collapsed: new Set(ctx.collapsed), knownGroups: new Set(ctx.model.nodes.filter((n) => n.kind === "group").map((n) => n.id)), playback: playback.playback() };
      api.destroy();
      const replacement = mount(root, prepared, { notes: opts.notes, onSelect: opts.onSelect, restore: saved });
      notifySelection(saved.selected, replacement.selected(), opts.onSelect);
      Object.assign(api, replacement);
      window.FlowStudio = api;
      els.banner.hidden = true;
      els.banner.textContent = "";
      if (updateOpts?.animate !== false && !ctx.reduced) {
        for (const id of changes.changed) root.querySelector(`#n_${CSS.escape(id)}`)?.classList.add("updated");
        for (const id of changes.added) root.querySelector(`#n_${CSS.escape(id)}`)?.classList.add("added");
      }
      return { ok: true, issues: nextIssues };
    },
    destroy: () => {
      ctx.fn.clearSim();
      ctx.disposers.forEach((d) => d());
      ctx.disposers = [];
      style?.remove();
      if (window.FlowStudio === api || window.FlowStudio?.model === api.model) delete window.FlowStudio;
    }
  };
  window.FlowStudio = api;
  return api;
}

// src/lib.ts
var SHELL_BODY_HTML = "<header class=\"top\">\r\n  <span class=\"brand\"><i></i>flow-studio</span>\r\n  <span class=\"spacer\"></span>\r\n  <button id=\"notesBtn\" type=\"button\" aria-pressed=\"false\">Implementation notes (N)</button>\r\n  <button id=\"theme\" type=\"button\" aria-label=\"Toggle light and dark\">☀ / ☾</button>\r\n</header>\r\n<main>\r\n  <div class=\"titlerow\"><h1 id=\"title\"></h1><span class=\"readline\" id=\"readat\"></span></div>\r\n  <p class=\"help\" id=\"help\"></p>\r\n  <div id=\"banner\" role=\"alert\" hidden></div>\r\n\r\n  <section class=\"summary\"><div class=\"layerstrip\" id=\"layerstrip\" aria-label=\"Completeness by column\"></div><div class=\"tiles\" id=\"kpis\" aria-label=\"Summary\"></div></section>\r\n\r\n  <div class=\"toolbar\">\r\n    <div class=\"seggrp\" role=\"tablist\" aria-label=\"View\" id=\"modeSwitch\"></div>\r\n    <input id=\"q\" type=\"search\" placeholder=\"Find a group or member…  ( / )\" aria-label=\"Find a group or member\">\r\n    <select id=\"hops\" aria-label=\"Search radius\"><option value=\"0\">This group</option><option value=\"1\">+1 hop</option><option value=\"2\">+2 hops</option><option value=\"3\">+3 hops</option></select>\r\n    <span id=\"matchinfo\" class=\"note\" style=\"margin:0\"></span>\r\n  </div>\r\n\r\n  <div class=\"workspace\" id=\"workspace\">\r\n    <section class=\"canvaswrap\">\r\n      <div id=\"viewport\" tabindex=\"0\" role=\"application\" aria-label=\"Flow canvas. Scroll to zoom, drag to pan. Keys: V select, H hand, plus and minus zoom, 0 fit, 1 actual size, F zoom to selection, arrows pan.\">\r\n        <div id=\"world\"><svg id=\"edges\" aria-hidden=\"true\"><defs><marker id=\"arr\" viewBox=\"0 0 8 8\" refX=\"7\" refY=\"4\" markerWidth=\"9\" markerHeight=\"9\" markerUnits=\"userSpaceOnUse\" orient=\"auto\"><path d=\"M0 0 L8 4 L0 8 z\" fill=\"context-stroke\"/></marker></defs><g id=\"edgeLayer\"></g></svg></div>\r\n        <div id=\"cols\" aria-hidden=\"true\"></div>\r\n        <div id=\"tools\" role=\"toolbar\" aria-label=\"Canvas controls\" aria-orientation=\"vertical\"></div>\r\n        <div id=\"zoomLabel\" aria-hidden=\"true\">100%</div>\r\n      </div>\r\n      <div id=\"playbar\" hidden aria-label=\"Scenario playback\">\r\n        <select id=\"pbScenario\" aria-label=\"Scenario\"></select>\r\n        <button id=\"pbPlay\" type=\"button\" aria-label=\"Play\">▶</button>\r\n        <button id=\"pbStep\" type=\"button\" aria-label=\"Step\">Step</button>\r\n        <button id=\"pbReset\" type=\"button\" aria-label=\"Reset\">Reset</button>\r\n        <select id=\"pbSpeed\" aria-label=\"Speed\"><option value=\"0.5\">0.5x</option><option value=\"1\" selected>1x</option><option value=\"2\">2x</option></select>\r\n        <input id=\"pbScrub\" type=\"range\" min=\"0\" max=\"1000\" value=\"0\" aria-label=\"Playback position\" aria-valuetext=\"Step 1 of 1\">\r\n        <span id=\"pbCaption\"></span><span id=\"pbCounter\"></span><span id=\"pbChoices\"></span>\r\n      </div>\r\n      <div class=\"keyline\" id=\"legend\" aria-label=\"Legend\"></div>\r\n      <aside class=\"insp\" id=\"inspector\" aria-label=\"Inspector\" aria-hidden=\"true\"></aside>\r\n    </section>\r\n  </div>\r\n  <div id=\"live\" class=\"sr\" role=\"status\" aria-live=\"polite\"></div>\r\n\r\n  <div class=\"ledger\" id=\"ledger\"></div>\r\n  <details class=\"tableview\"><summary>Table view</summary><table class=\"sources\" id=\"tbl\"></table></details>\r\n  <details class=\"spec\" id=\"spec\"><summary>Model reference (for the person or agent who builds this)</summary><div id=\"specbody\"></div></details>\r\n</main>\r\n<footer id=\"footer\"></footer>\r\n<aside id=\"drawer\" aria-label=\"Implementation notes\"><h2>Implementation notes</h2><p class=\"note\">Numbered markers on the page match these cards. Hover a card to find its place; click a marker to jump to its card.</p><div id=\"notelist\"></div></aside>\r\n\r\n";
export {
  K_MAX,
  K_MIN,
  NODE_HEIGHT,
  SHELL_BODY_HTML,
  autoLayout,
  baselineView,
  bucketOf,
  buildManualRoute,
  canonOf,
  clampK,
  clampPan,
  columnTitle,
  computeGeometry,
  connected,
  defaultView,
  diff_exports as diff,
  diffModels,
  effectiveLinks,
  elbow,
  esc,
  exitsOf,
  extendScenarioWithRoute,
  fitRect,
  fitWidth,
  formatElapsed,
  groupFor,
  initialCollapsed,
  isImproved,
  isNew,
  linkStateId,
  linkVisible,
  loopBack,
  mount,
  nodeStateId,
  nodeVisible,
  planScenario,
  playback_exports as playback,
  positionAt,
  relatives,
  routing_exports as routing,
  rules_exports as rules,
  slaState,
  stateCss,
  stripHeads,
  suggestedExit,
  toggleGroupState,
  trace_exports as trace,
  validateModel,
  viewport_exports as viewport,
  withinHops,
  zoomAt
};
