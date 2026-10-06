import { test } from "node:test";
import assert from "node:assert/strict";
import { diffModels } from "./diff.ts";
import type { Model } from "./model.ts";

const base = { nodes: [{ id: "a", state: "ok", title: "A", kind: "card", sla: 30 }, { id: "b", state: "ok", title: "B", kind: "card" }] } as Model;
test("diff reports added, removed, and specified field changes", () => {
  const next = { nodes: [{ ...base.nodes[0], metrics: { value: 2 } }, { id: "c", state: "ok", title: "C", kind: "card" }] } as Model;
  assert.deepEqual(diffModels(base, next), { added: ["c"], removed: ["b"], changed: ["a"] });
  assert.deepEqual(diffModels(base, structuredClone(base)), { added: [], removed: [], changed: [] });
});
test("diff detects change in sla", () => {
  const next = { nodes: [{ ...base.nodes[0], sla: 60 }, base.nodes[1]] } as Model;
  assert.deepEqual(diffModels(base, next), { added: [], removed: [], changed: ["a"] });
});
test("diff is invariant to key order in objects", () => {
  const m1 = { nodes: [{ id: "a", state: "ok", title: "A", kind: "card", metrics: { value: 10, unit: "ms", label: "latency" } }] } as Model;
  const m2 = { nodes: [{ id: "a", state: "ok", title: "A", kind: "card", metrics: { label: "latency", unit: "ms", value: 10 } }] } as Model;
  assert.deepEqual(diffModels(m1, m2), { added: [], removed: [], changed: [] });
});
test("an undefined-valued property counts as absent (a model comes from JSON, which cannot hold one)", () => {
  const m1 = { nodes: [{ id: "a", state: "ok", title: "A", kind: "card", metrics: { value: 1, unit: undefined } }] } as unknown as Model;
  const m2 = { nodes: [{ id: "a", state: "ok", title: "A", kind: "card", metrics: { value: 1 } }] } as Model;
  assert.deepEqual(diffModels(m1, m2), { added: [], removed: [], changed: [] });
});
test("null, undefined and NaN stay distinct values in a diff", () => {
  const mk = (metrics: unknown) => ({ nodes: [{ id: "a", state: "ok", title: "A", kind: "card", metrics }] }) as unknown as Model;
  assert.deepEqual(diffModels(mk({ value: 1, series: [null] }), mk({ value: 1, series: [undefined] })).changed, ["a"]);
  assert.deepEqual(diffModels(mk({ value: NaN }), mk({ value: null })).changed, ["a"]);
  assert.deepEqual(diffModels(mk({ value: NaN }), mk({ value: NaN })).changed, []);
});
