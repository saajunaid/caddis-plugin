import { test } from "node:test";
import assert from "node:assert/strict";
import { validateModel, esc, type Model } from "./model.ts";

const base = (): Model => ({
  version: 1,
  meta: { title: "T", help: "h", asOf: "2026-01-01", source: "s" },
  layout: "columns-lanes",
  columns: [{ id: "c0", title: "A", width: 150 }, { id: "c1", title: "B", width: 150 }],
  lanes: [{ id: "l1", title: "Lane 1" }],
  states: { ok: { word: "OK", tone: "ok", border: "solid", edge: "flow", motion: "flow", bucket: "good" } },
  nodes: [
    { id: "a", kind: "card", lane: "l1", col: 0, row: 0, state: "ok", title: "A" },
    { id: "b", kind: "card", lane: "l1", col: 1, row: 0, state: "ok", title: "B" },
  ],
  links: [{ id: "a-b", from: "a", to: "b", state: "ok" }],
});
const codes = (m: unknown) => validateModel(m).filter(i => i.level === "error").map(i => i.code);

test("a valid model has no errors", () => assert.deepEqual(codes(base()), []));
test("not an object", () => assert.deepEqual(codes(null), ["model-shape"]));
test("link to a missing node names the link", () => {
  const m = base(); m.links[0]!.to = "zzz";
  const issues = validateModel(m);
  assert.ok(issues.some(i => i.code === "link-endpoint" && i.where === "links[a-b]"));
});
test("duplicate node id", () => { const m = base(); m.nodes[1]!.id = "a"; assert.ok(codes(m).includes("node-duplicate")); });
test("undefined state on a node", () => { const m = base(); m.nodes[0]!.state = "nope"; assert.ok(codes(m).includes("state-undefined")); });
test("node in an unknown lane", () => { const m = base(); m.nodes[0]!.lane = "zz"; assert.ok(codes(m).includes("lane-undefined")); });
test("column out of range", () => { const m = base(); m.nodes[0]!.col = 5; assert.ok(codes(m).includes("column-range")); });
test("colSpan that runs past the last column", () => { const m = base(); m.nodes[1]!.colSpan = 3; assert.ok(codes(m).includes("column-range")); });
test("two nodes in the same cell overlap", () => {
  const m = base(); m.nodes[1]!.col = 0; m.links = [];
  assert.ok(codes(m).includes("cell-overlap"));
});
test("rows less than one apart in the same column overlap", () => {
  const m = base(); m.nodes[1]!.col = 0; m.nodes[1]!.row = 0.5;
  assert.ok(codes(m).includes("cell-overlap"));
});
test("an orphan node is an error unless allowed", () => {
  const m = base(); m.links = [];
  assert.equal(codes(m).filter(c => c === "orphan").length, 2);
  m.nodes[0]!.allowIsolated = true; m.nodes[1]!.allowIsolated = true;
  assert.deepEqual(codes(m), []);
});
test("a chip must point at a real node", () => {
  const m = base(); m.nodes.push({ id: "c", kind: "chip", lane: "l1", col: 0, row: 1, state: "ok", title: "c", ref: "zzz" });
  assert.ok(codes(m).includes("chip-ref"));
});
test("empty model is reported, not thrown", () => {
  const m = base(); m.nodes = []; m.links = [];
  const issues = validateModel(m);
  assert.ok(issues.some(i => i.code === "model-empty"));
});
test("duplicate link id", () => { const m = base(); m.links.push({ ...m.links[0]! }); assert.ok(codes(m).includes("link-duplicate")); });
test("a state with an unknown tone is rejected", () => {
  const m = base(); (m.states.ok as any).tone = "purple";
  assert.ok(codes(m).includes("state-shape"));
});
test("only the columns-lanes layout exists in this stage", () => {
  const m = base(); (m as any).layout = "free";
  assert.ok(codes(m).includes("layout-unsupported"));
});
test("a link that goes backward or sideways is a warning, not silence", () => {
  const m = base(); m.links[0]!.from = "b"; m.links[0]!.to = "a";
  const issues = validateModel(m);
  assert.ok(issues.some(i => i.level === "warn" && i.code === "link-direction" && i.where === "links[a-b]"));
  assert.deepEqual(codes(m), []);
});
test("a forward link has no direction warning", () => {
  assert.ok(!validateModel(base()).some(i => i.code === "link-direction"));
});
test("a model with no meta is an error, not a crash later", () => {
  const m = base(); delete (m as any).meta;
  assert.ok(codes(m).includes("meta-missing"));
});
test("a node row that is not a finite number is an error (it would draw NaN)", () => {
  const m = base(); (m.nodes[0] as any).row = "zero"; (m.nodes[1] as any).row = NaN;
  assert.equal(codes(m).filter(c => c === "row-invalid").length, 2);
});
test("a node that is not an object is reported, never thrown (review focus 1)", () => {
  const m = base(); (m.nodes as any[]).push(null, 7, "x");
  assert.doesNotThrow(() => validateModel(m));
  assert.equal(codes(m).filter(c => c === "node-shape").length, 3);
});
test("a link that is not an object is reported, never thrown", () => {
  const m = base(); (m.links as any[]).push(null);
  assert.doesNotThrow(() => validateModel(m));
  assert.ok(codes(m).includes("link-shape"));
});
test("a node id that is not a string is an error", () => {
  const m = base(); (m.nodes[0] as any).id = 5;
  assert.ok(codes(m).includes("node-shape"));
});
test("lanes that are not an array do not make the validator throw", () => {
  const m = base(); (m as any).lanes = "abc";
  assert.doesNotThrow(() => validateModel(m));
  assert.ok(codes(m).includes("lanes-missing"));
});
test("a state id must be usable as a CSS class", () => {
  const m = base(); m.states['bad id"'] = m.states.ok!;
  assert.ok(codes(m).includes("state-id"));
});
test("esc turns markup into text", () => {
  assert.equal(esc(`<img src=x onerror="a()">&'`), "&lt;img src=x onerror=&quot;a()&quot;&gt;&amp;&#39;");
  assert.equal(esc(undefined), "");
});
