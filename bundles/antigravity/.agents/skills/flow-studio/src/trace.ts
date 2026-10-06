// Path tracing over links. A portal chip is an alias of its real node: pass canonOf to map ids.

export interface Edge { from: string; to: string }

export function relatives(edges: Edge[], canonOf: (id: string) => string, start: string, dir: "up" | "down"): Set<string> {
  const set = new Set<string>([canonOf(start)]);
  let grew = true;
  while (grew) {
    grew = false;
    for (const e of edges) {
      const a = canonOf(e.from);
      const b = canonOf(e.to);
      if (dir === "up" && set.has(b) && !set.has(a)) { set.add(a); grew = true; }
      if (dir === "down" && set.has(a) && !set.has(b)) { set.add(b); grew = true; }
    }
  }
  return set;
}

export function connected(edges: Edge[], canonOf: (id: string) => string, start: string): Set<string> {
  return new Set([...relatives(edges, canonOf, start, "up"), ...relatives(edges, canonOf, start, "down")]);
}

/** Undirected breadth-first radius around one or more nodes. */
export function withinHops(edges: Edge[], canonOf: (id: string) => string, starts: string[], n: number): Set<string> {
  const found = new Set(starts.map(canonOf));
  const radius = Number.isFinite(n) ? Math.max(0, Math.floor(n)) : 0;
  let frontier = [...found];
  for (let hop = 0; hop < radius && frontier.length; hop++) {
    const next: string[] = [];
    const current = new Set(frontier);
    for (const edge of edges) {
      const a = canonOf(edge.from), b = canonOf(edge.to);
      if (current.has(a) && !found.has(b)) { found.add(b); next.push(b); }
      if (current.has(b) && !found.has(a)) { found.add(a); next.push(a); }
    }
    frontier = next;
  }
  return found;
}
