// Deterministic placement for models without authored grid positions. No DOM and no input mutation.
import type { Model, NodeDef, LinkDef } from "./model.ts";

export function autoLayout(input: Model): Model {
  const nodes = input.nodes.map(n => ({ ...n }));
  const links = input.links.map(l => ({ ...l }));
  const columns = input.columns.map(c => ({ ...c }));
  const lanes = input.lanes.map(l => ({ ...l }));
  const byId = new Map(nodes.map(n => [n.id, n]));
  const index = new Map(nodes.map((n, i) => [n.id, i]));
  const outgoing = new Map(nodes.map(n => [n.id, [] as LinkDef[]]));
  const incoming = new Map(nodes.map(n => [n.id, [] as LinkDef[]]));
  const neighbours = new Map(nodes.map(n => [n.id, [] as string[]]));
  for (const link of links) {
    if (!byId.has(link.from) || !byId.has(link.to)) continue;
    outgoing.get(link.from)!.push(link);
    incoming.get(link.to)!.push(link);
    neighbours.get(link.from)!.push(link.to);
    neighbours.get(link.to)!.push(link.from);
  }

  // A gray target is on the active DFS stack. Mark that edge as feedback.
  const color = new Map<string, number>();
  const post: string[] = [];
  for (const root of nodes) {
    if (color.has(root.id)) continue;
    color.set(root.id, 1);
    const stack: { id: string; next: number }[] = [{ id: root.id, next: 0 }];
    while (stack.length) {
      const frame = stack[stack.length - 1]!;
      const edges = outgoing.get(frame.id)!;
      if (frame.next >= edges.length) {
        color.set(frame.id, 2); post.push(frame.id); stack.pop(); continue;
      }
      const link = edges[frame.next++]!;
      if (link.kind === "loop-back") continue;
      const state = color.get(link.to) ?? 0;
      if (state === 1) link.kind = "loop-back";
      else if (state === 0) { color.set(link.to, 1); stack.push({ id: link.to, next: 0 }); }
    }
  }

  // Reverse finishing order is topological after feedback edges are removed.
  for (const id of post.reverse()) {
    const n = byId.get(id)!;
    if (n.col !== undefined) continue;
    let col = 0;
    for (const edge of incoming.get(id)!) {
      if (edge.kind === "loop-back") continue;
      const parent = byId.get(edge.from)!;
      col = Math.max(col, (parent.col ?? 0) + (parent.colSpan ?? 1));
    }
    n.col = col;
  }

  // Missing lane membership is grouped by weak connection, including feedback edges.
  const seen = new Set<string>();
  const usedLaneIds = new Set(lanes.map(l => l.id));
  let group = 0;
  for (const first of nodes) {
    if (seen.has(first.id)) continue;
    const queue = [first.id]; seen.add(first.id);
    for (let q = 0; q < queue.length; q++) {
      for (const id of neighbours.get(queue[q]!)!) if (!seen.has(id)) { seen.add(id); queue.push(id); }
    }
    const missing = queue.map(id => byId.get(id)!).filter(n => !n.lane);
    if (!missing.length) continue;
    group++;
    let laneId = `group-${group}`;
    while (usedLaneIds.has(laneId)) laneId += "-auto";
    usedLaneIds.add(laneId);
    lanes.push({ id: laneId, title: `Group ${group}` });
    for (const n of missing) n.lane = laneId;
  }

  // Start in input order. Four alternating sweeps sort each lane and layer by
  // neighbour barycentre. Stable input order resolves every tie.
  const rank = new Map(nodes.map((n, i) => [n.id, i]));
  const laneOrder = lanes.map(l => l.id);
  const cells = new Map<string, NodeDef[]>();
  for (const n of nodes) {
    const key = `${n.lane}\0${n.col}`;
    if (!cells.has(key)) cells.set(key, []);
    cells.get(key)!.push(n);
  }
  const maxCol = Math.max(0, ...nodes.map(n => (n.col ?? 0) + (n.colSpan ?? 1) - 1));
  for (let sweep = 0; sweep < 4; sweep++) {
    const forward = sweep % 2 === 0;
    const layers = Array.from({ length: maxCol + 1 }, (_, i) => forward ? i : maxCol - i);
    for (const lane of laneOrder) for (const col of layers) {
      const groupNodes = cells.get(`${lane}\0${col}`);
      if (!groupNodes || groupNodes.length < 2) continue;
      const score = (n: NodeDef): number => {
        const edges = forward ? incoming.get(n.id)! : outgoing.get(n.id)!;
        const ns = edges.filter(e => e.kind !== "loop-back").map(e => forward ? e.from : e.to);
        return ns.length ? ns.reduce((sum, id) => sum + (rank.get(id) ?? 0), 0) / ns.length : (rank.get(n.id) ?? 0);
      };
      groupNodes.sort((a, b) => score(a) - score(b) || (index.get(a.id)! - index.get(b.id)!));
      groupNodes.forEach((n, i) => rank.set(n.id, i));
    }
  }

  // Place lanes in separate row ranges. A cell can share a row with another
  // column, but nodes whose column spans intersect need a full row of space.
  let nextBase = 0;
  const placed: NodeDef[] = nodes.filter(n => n.row !== undefined);
  for (const lane of laneOrder) {
    const members = nodes.filter(n => n.lane === lane);
    if (!members.length) continue;
    const ordered = [...members].sort((a, b) => (a.col ?? 0) - (b.col ?? 0) || (rank.get(a.id) ?? 0) - (rank.get(b.id) ?? 0) || index.get(a.id)! - index.get(b.id)!);
    const rowAtCol = new Map<number, number>();
    for (const n of ordered) {
      if (n.row !== undefined) continue;
      let row = Math.max(nextBase, rowAtCol.get(n.col ?? 0) ?? nextBase);
      while (placed.some(p => (n.col ?? 0) < (p.col ?? 0) + (p.colSpan ?? 1)
        && (p.col ?? 0) < (n.col ?? 0) + (n.colSpan ?? 1) && Math.abs(row - (p.row ?? 0)) < 1)) row += 1;
      n.row = row;
      placed.push(n);
      rowAtCol.set(n.col ?? 0, row + 1);
    }
    const last = Math.max(nextBase - 1, ...members.map(n => n.row ?? 0));
    const loops = links.filter(l => l.kind === "loop-back" && byId.get(l.from)?.lane === lane && byId.get(l.to)?.lane === lane).length;
    nextBase = last + 1.75 + loops * 0.35;
  }

  const needed = Math.max(0, ...nodes.map(n => (n.col ?? 0) + (n.colSpan ?? 1)));
  while (columns.length < needed) {
    const i = columns.length + 1;
    columns.push({ id: `stage-${i}`, title: `Stage ${i}`, width: 190 });
  }
  return { ...input, nodes, links, columns, lanes };
}
