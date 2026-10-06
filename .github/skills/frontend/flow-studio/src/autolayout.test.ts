import { test } from "node:test";
import assert from "node:assert/strict";
import { autoLayout } from "./autolayout.ts";
import { validateModel, type Model, type NodeDef } from "./model.ts";
import { computeGeometry } from "./layout.ts";

const node = (id: string, extra: Partial<NodeDef> = {}): NodeDef => ({ id, kind: "card", state: "ok", title: id, ...extra } as NodeDef);
const model = (ids: string[], pairs: [string, string][]): Model => ({
  version: 1, meta: { title: "t", help: "", asOf: "", source: "" }, layout: "auto", columns: [], lanes: [],
  states: { ok: { word: "OK", tone: "ok", border: "solid", edge: "flow", motion: "flow", bucket: "good" } },
  nodes: ids.map(id => node(id)), links: pairs.map(([from, to], i) => ({ id: `e${i}`, from, to, state: "ok" })),
});
const errors = (m: Model) => validateModel(m).filter(i => i.level === "error");

test("chain gets longest path columns and generated stages", () => {
  const out = autoLayout(model(["a", "b", "c"], [["a", "b"], ["b", "c"]]));
  assert.deepEqual(out.nodes.map(n => n.col), [0, 1, 2]);
  assert.deepEqual(out.columns.map(c => c.title), ["Stage 1", "Stage 2", "Stage 3"]);
  assert.deepEqual(errors(out), []);
});
test("fork and join ranks the join after both branches", () => {
  const out = autoLayout(model(["a", "b", "c", "d"], [["a", "b"], ["a", "c"], ["b", "d"], ["c", "d"]]));
  assert.equal(out.nodes.find(n => n.id === "d")?.col, 2);
  assert.equal(out.nodes.find(n => n.id === "b")?.col, 1);
  assert.equal(out.nodes.find(n => n.id === "c")?.col, 1);
  assert.deepEqual(errors(out), []);
});
test("a three cycle yields exactly one feedback edge and consistent ranks", () => {
  const out = autoLayout(model(["a", "b", "c"], [["a", "b"], ["b", "c"], ["c", "a"]]));
  assert.deepEqual(out.links.filter(l => l.kind === "loop-back").map(l => l.id), ["e2"]);
  assert.deepEqual(out.nodes.map(n => n.col), [0, 1, 2]);
  assert.deepEqual(errors(out), []);
});
test("disconnected parts get synthetic lanes in first appearance order", () => {
  const out = autoLayout(model(["a", "b", "c", "d"], [["a", "b"], ["c", "d"]]));
  assert.deepEqual(out.lanes.map(l => l.title), ["Group 1", "Group 2"]);
  assert.equal(out.nodes[0]?.lane, out.nodes[1]?.lane);
  assert.equal(out.nodes[2]?.lane, out.nodes[3]?.lane);
  assert.notEqual(out.nodes[0]?.lane, out.nodes[2]?.lane);
  const lanes = Object.values(computeGeometry(out).lanes).sort((a, b) => a.y - b.y);
  assert.ok(lanes[0]!.y + lanes[0]!.h <= lanes[1]!.y);
});
test("author fixed column and row stay fixed and successors rank from them", () => {
  const m = model(["a", "b", "c"], [["a", "b"], ["b", "c"]]);
  m.nodes[1]!.col = 4; m.nodes[1]!.row = 7;
  const out = autoLayout(m);
  assert.equal(out.nodes[1]?.col, 4);
  assert.equal(out.nodes[1]?.row, 7);
  assert.equal(out.nodes[2]?.col, 5);
  assert.equal(out.columns.length, 6);
  assert.deepEqual(errors(out), []);
});
test("ordering lowers crossings on a reversed two-edge example", () => {
  const m = model(["a", "b", "d", "c"], [["a", "c"], ["b", "d"]]);
  m.nodes[0]!.col = 0; m.nodes[1]!.col = 0; m.nodes[2]!.col = 1; m.nodes[3]!.col = 1;
  m.nodes.forEach(n => n.lane = "one"); m.lanes = [{ id: "one", title: "One" }];
  const out = autoLayout(m), byId = new Map(out.nodes.map(n => [n.id, n]));
  const crossing = (a: string, b: string, c: string, d: string): boolean =>
    ((byId.get(a)!.row! - byId.get(c)!.row!) * (byId.get(b)!.row! - byId.get(d)!.row!)) < 0;
  assert.equal(crossing("a", "c", "b", "d"), false);
  assert.deepEqual(errors(out), []);
});
test("same input gives equal output without changing input", () => {
  const m = model(["a", "b", "c"], [["a", "b"], ["b", "c"]]);
  const before = JSON.stringify(m);
  assert.deepEqual(autoLayout(m), autoLayout(m));
  assert.equal(JSON.stringify(m), before);
});
test("seeded 200 node graph finishes under 300ms and validates", () => {
  const ids = Array.from({ length: 200 }, (_, i) => `n${i}`);
  let seed = 39;
  const rnd = () => { seed = (1664525 * seed + 1013904223) >>> 0; return seed / 0x100000000; };
  const pairs: [string, string][] = ids.slice(1).map((id, i) => [ids[i]!, id]);
  for (let i = 0; i < 200; i++) pairs.push([ids[Math.floor(rnd() * ids.length)]!, ids[Math.floor(rnd() * ids.length)]!]);
  const m = model(ids, pairs), start = performance.now(), out = autoLayout(m);
  assert.ok(performance.now() - start < 300);
  assert.deepEqual(errors(out), []);
});
