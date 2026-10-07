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
test("a gateway has a 64 px diamond box", () => {
  const mm = m(); mm.nodes[0]!.kind = "gateway";
  assert.equal(computeGeometry(mm).nodes.a!.h, 64);
});
test("loop-back channels stay below nodes, inside their lane, and separate from the next lane", () => {
  const mm = m();
  mm.links.push({ id: "return", from: "b", to: "a", state: "ok", kind: "loop-back" });
  mm.links.push({ id: "again", from: "b", to: "a", state: "ok", kind: "loop-back" });
  const g = computeGeometry(mm);
  const y = g.loops.return!.channelY;
  assert.ok(y >= g.nodes.a!.y + g.nodes.a!.h + 10);
  assert.ok(y >= g.nodes.b!.y + g.nodes.b!.h + 10);
  assert.equal(g.loops.again!.channelY, y + 8);
  assert.ok(g.lanes.l1!.y + g.lanes.l1!.h > g.loops.again!.channelY);
  assert.ok(g.lanes.l1!.y + g.lanes.l1!.h <= g.lanes.l2!.y);
});

test("a loop clears a lower node within its horizontal span", () => {
  const mm = m();
  mm.columns.push({ id: "c2", title: "C", width: 150 });
  mm.nodes.find(n => n.id === "b")!.col = 2;
  mm.nodes.push({ id: "middle", kind: "card", lane: "l1", col: 1, row: 1, state: "ok", title: "Middle" });
  mm.links.push({ id: "return", from: "b", to: "a", state: "ok", kind: "loop-back" });
  const g = computeGeometry(mm);
  assert.equal(g.loops.return!.channelY, g.nodes.middle!.y + g.nodes.middle!.h + 10);
  assert.ok(g.lanes.l1!.y + g.lanes.l1!.h <= g.lanes.l2!.y);
});

test("a lower node outside the loop span does not lower its channel", () => {
  const mm = m();
  mm.columns.push({ id: "c2", title: "C", width: 150 });
  mm.nodes.push({ id: "outside", kind: "card", lane: "l1", col: 2, row: 1, state: "ok", title: "Outside" });
  mm.links.push({ id: "return", from: "b", to: "a", state: "ok", kind: "loop-back" });
  const g = computeGeometry(mm);
  assert.equal(g.loops.return!.channelY, g.nodes.a!.y + g.nodes.a!.h + 10);
});

test("interleaved lanes calculate channels after all endpoint shifts", () => {
  const mm = m();
  mm.nodes = [
    { id: "a", kind: "card", lane: "l1", col: 0, row: 0, state: "ok", title: "A" },
    { id: "deep", kind: "card", lane: "l1", col: 1, row: 5, state: "ok", title: "Deep" },
    { id: "b", kind: "card", lane: "l2", col: 0, row: 1, state: "ok", title: "B" },
  ];
  mm.links = [{ id: "return", from: "deep", to: "b", state: "ok", kind: "loop-back" }];
  const g = computeGeometry(mm);
  assert.ok(g.loops.return!.channelY >= g.nodes.b!.y + g.nodes.b!.h + 10);
  assert.ok(g.lanes.l1!.y + g.lanes.l1!.h <= g.lanes.l2!.y);
  assert.ok(Object.values(g.nodes).every(n => [n.x, n.y, n.w, n.h].every(Number.isFinite)));
  assert.ok(Object.values(g.loops).every(l => Number.isFinite(l.channelY)));
});

test("free layout uses explicit world rectangles and works without columns", () => {
  const mm = m();
  mm.layout = "free"; mm.columns = [];
  mm.nodes = [
    { id: "a", kind: "card", lane: "l1", x: 18, y: 70, w: 121, h: 47, state: "ok", title: "A" },
    { id: "b", kind: "card", lane: "l2", x: 250, y: 300, state: "ok", title: "B" },
  ];
  const g = computeGeometry(mm);
  assert.deepEqual(g.xs, []);
  assert.deepEqual(g.nodes.a, { id: "a", x: 18, y: 70, w: 121, h: 47 });
  assert.equal(g.nodes.b?.w, 190);
  assert.ok(g.world.w >= 440);
  assert.ok(g.lanes.l1 && g.lanes.l2);
});

test("free layout preserves finite negative node coordinates", () => {
  const mm = m(); mm.layout = "free"; mm.columns = [];
  mm.nodes = [{ id: "a", kind: "card", lane: "l1", x: -80, y: -40, w: 60, h: 30, state: "ok", title: "A" }];
  const g = computeGeometry(mm);
  assert.equal(g.nodes.a!.x, -80);
  assert.equal(g.nodes.a!.y, -40);
  assert.ok([g.bounds.x, g.bounds.y, g.bounds.w, g.bounds.h, g.world.w, g.world.h].every(Number.isFinite));
});

test("a node with bars is taller by default, so the chart does not sit on its text; an explicit height wins", () => {
  const model = m();
  model.nodes[0]!.bars = [{ key: "a", value: 1 }];
  const g = computeGeometry(model);
  assert.equal(g.nodes.a!.h, 54 + 26);
  assert.equal(g.nodes.b!.h, 54);
  const free = m();
  free.layout = "free";
  free.nodes = [
    { id: "x", kind: "card", lane: "l1", x: 0, y: 0, state: "ok", title: "X", bars: [{ key: "a", value: 1 }] },
    { id: "y", kind: "card", lane: "l1", x: 0, y: 200, h: 100, state: "ok", title: "Y", bars: [{ key: "a", value: 1 }] },
  ];
  const gf = computeGeometry(free);
  assert.equal(gf.nodes.x!.h, 54 + 26);
  assert.equal(gf.nodes.y!.h, 100);
});
