import type { Model, NodeDef } from "./model.ts";

const fields: Array<keyof NodeDef> = ["state", "stateIn", "title", "subtitle", "weight", "metrics", "visibleIn", "lane", "sla"];

// A stable serializer for the diff. Unlike JSON.stringify it never returns undefined, and values
// JSON cannot hold stay distinct: undefined, NaN and Infinity each get their own text, so a real
// change between them cannot be hidden by "null" conflation.
function stableStringify(val: unknown): string {
  if (val === undefined) return "undefined";
  if (val === null) return "null";
  if (typeof val === "number") return Number.isFinite(val) ? JSON.stringify(val) : String(val);
  if (typeof val === "bigint") return String(val);
  if (typeof val === "object") {
    if (Array.isArray(val)) return `[${val.map(stableStringify).join(",")}]`;
    // A model comes from JSON, which cannot hold an undefined property, so an explicit one counts as absent.
    const rec = val as Record<string, unknown>;
    const keys = Object.keys(rec).filter(k => rec[k] !== undefined).sort();
    return `{${keys.map(k => `${JSON.stringify(k)}:${stableStringify(rec[k])}`).join(",")}}`;
  }
  return JSON.stringify(val) ?? "undefined";
}

export function diffModels(a: Model, b: Model): { added: string[]; removed: string[]; changed: string[] } {
  const old = new Map(a.nodes.map(n => [n.id, n]));
  const now = new Map(b.nodes.map(n => [n.id, n]));
  return {
    added: b.nodes.filter(n => !old.has(n.id)).map(n => n.id),
    removed: a.nodes.filter(n => !now.has(n.id)).map(n => n.id),
    changed: b.nodes.filter(n => {
      const prev = old.get(n.id);
      return prev && fields.some(k => stableStringify(prev[k]) !== stableStringify(n[k]));
    }).map(n => n.id),
  };
}
