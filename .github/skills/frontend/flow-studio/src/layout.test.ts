import { test } from "node:test";
import assert from "node:assert/strict";
import { computeGeometry } from "./layout.ts";
import type { Model } from "./model.ts";

const m = (): Model => ({
  version: 1,
  meta: { title: "t", help: "", asOf: "", source: "" },
  layout: "columns-lanes",
  columns: [{ id: "c0", title: "A", width: 150 }, { id: "c1", title: "B", width: 200 }],
  lanes: [{ id: "l1", title: "One" }, { id: "l2", title: "Two" }],
  states: { ok: { word: "OK", tone: "ok", border: "solid", edge: "flow", motion: "flow", bucket: "good" } },
  nodes: [
    { id: "a", kind: "card", lane: "l1", col: 0, row: 0, state: "ok", title: "A" },
    { id: "b", kind: "card", lane: "l1", col: 1, row: 0, state: "ok", title: "B" },
    { id: "c", kind: "card", lane: "l2", col: 0, row: 1.8, state: "ok", title: "C" },
    { id: "w", kind: "placeholder", lane: "l2", col: 0, colSpan: 2, row: 2.8, state: "ok", title: "W" },
  ],
  links: [{ id: "a-b", from: "a", to: "b", state: "ok" }],
});

test("columns are laid out left to right with the gap", () => {
  const g = computeGeometry(m());
  assert.equal(g.xs[0], 24);
  assert.equal(g.xs[1], 24 + 150 + 34);
});
test("a node sits at its column and its row", () => {
  const g = computeGeometry(m());
  assert.equal(g.nodes.a!.x, 24);
  assert.equal(g.nodes.a!.w, 150);
  assert.ok(g.nodes.c!.y > g.nodes.a!.y);
});
test("a wide node spans its columns", () => {
  const g = computeGeometry(m());
  assert.equal(g.nodes.w!.w, 150 + 34 + 200);
});
test("a chip is shorter than a card", () => {
  const mm = m();
  mm.nodes.push({ id: "k", kind: "chip", lane: "l1", col: 0, row: 3.8, state: "ok", title: "k", ref: "a" });
  const g = computeGeometry(mm);
  assert.ok(g.nodes.k!.h < g.nodes.a!.h);
});
test("lane rectangles are computed from their nodes and do not overlap", () => {
  const g = computeGeometry(m());
  const a = g.lanes.l1!, b = g.lanes.l2!;
  assert.ok(a.y + a.h <= b.y, `${a.y + a.h} <= ${b.y}`);
});
test("a lane without visible nodes has no rectangle", () => {
  const g = computeGeometry(m(), { visible: id => id !== "c" && id !== "w" });
  assert.equal(g.lanes.l2, undefined);
});
test("bounds cover every lane and the world is finite", () => {
  const g = computeGeometry(m());
  assert.ok(Object.values(g.lanes).every(l => l.y >= g.bounds.y && l.y + l.h <= g.bounds.y + g.bounds.h + 1e-6));
  assert.ok(Number.isFinite(g.world.w) && Number.isFinite(g.world.h));
});
test("an empty model has a finite, empty geometry (review focus 2)", () => {
  const mm = m();
  mm.nodes = [];
  mm.links = [];
  const g = computeGeometry(mm);
  assert.ok(Number.isFinite(g.bounds.w) && Number.isFinite(g.bounds.h) && Number.isFinite(g.world.h));
});
test("a node whose column is out of range does not produce NaN", () => {
  const mm = m();
  mm.nodes[0]!.col = 9;
  const g = computeGeometry(mm);
  assert.ok(Object.values(g.nodes).every(n => [n.x, n.y, n.w, n.h].every(Number.isFinite)));
});
