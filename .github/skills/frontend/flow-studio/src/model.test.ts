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
test("free layout needs finite position and positive size but no columns", () => {
  const m = base(); m.layout = "free"; m.columns = [];
  m.nodes[0] = { id: "a", kind: "card", lane: "l1", x: 0, y: 0, w: 100, h: 40, state: "ok", title: "A" };
  m.nodes[1] = { id: "b", kind: "card", lane: "l1", x: 200, y: 0, state: "ok", title: "B" };
  assert.deepEqual(codes(m), []);
  delete m.nodes[0]!.x;
  assert.ok(codes(m).includes("position-invalid"));
  m.nodes[0]!.x = 0; m.nodes[0]!.w = -1;
  assert.ok(codes(m).includes("size-invalid"));
});
test("free layout detects rectangle intersections", () => {
  const m = base(); m.layout = "free"; m.columns = [];
  m.nodes[0] = { id: "a", kind: "card", lane: "l1", x: 0, y: 0, w: 100, h: 50, state: "ok", title: "A" };
  m.nodes[1] = { id: "b", kind: "card", lane: "l1", x: 90, y: 49, w: 100, h: 50, state: "ok", title: "B" };
  assert.ok(codes(m).includes("rect-overlap"));
  m.nodes[1]!.x = 100;
  assert.ok(!codes(m).includes("rect-overlap"));
});
test("unsupported layout is an error; auto permits missing positions before layout", () => {
  const m = base(); (m as any).layout = "timeline";
  assert.ok(codes(m).includes("layout-unsupported"));
  m.layout = "auto"; m.columns = []; m.lanes = [];
  m.nodes.forEach(n => { delete n.col; delete n.row; delete n.lane; });
  assert.ok(!codes(m).includes("layout-unsupported"));
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
test("a branching gateway requires a label on every exit", () => {
  const m = base(); m.nodes[0]!.kind = "gateway";
  m.nodes.push({ id: "c", kind: "card", lane: "l1", col: 1, row: 1, state: "ok", title: "C" });
  m.links.push({ id: "a-c", from: "a", to: "c", state: "ok", label: "No" });
  assert.ok(validateModel(m).some(i => i.level === "warn" && i.code === "gateway-exit-label" && i.where === "nodes[a]"));
  m.links[0]!.label = "Yes";
  assert.ok(!validateModel(m).some(i => i.code === "gateway-exit-label"));
});
test("a gateway with no exit warns", () => {
  const m = base(); m.nodes[1]!.kind = "gateway";
  assert.ok(validateModel(m).some(i => i.level === "warn" && i.code === "gateway-no-exit" && i.where === "nodes[b]"));
});
test("an explicit loop-back suppresses backward direction warning", () => {
  const m = base(); m.links[0]!.from = "b"; m.links[0]!.to = "a"; m.links[0]!.kind = "loop-back";
  assert.ok(!validateModel(m).some(i => i.code === "link-direction" || i.code === "loop-back-forward"));
});
test("a loop-back that runs forward warns", () => {
  const m = base(); m.links[0]!.kind = "loop-back";
  assert.ok(validateModel(m).some(i => i.level === "warn" && i.code === "loop-back-forward"));
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
test("a metric max of null means no maximum; a non-numeric max is still an error", () => {
  const m = base();
  m.nodes[0]!.metrics = { value: 5, max: null };
  assert.ok(!codes(m).includes("metric-invalid"), "null max is the author's way to say there is no maximum");
  m.nodes[0]!.metrics = { value: 5, max: "10" as unknown as number };
  assert.ok(codes(m).includes("metric-invalid"));
});
test("esc turns markup into text", () => {
  assert.equal(esc(`<img src=x onerror="a()">&'`), "&lt;img src=x onerror=&quot;a()&quot;&gt;&amp;&#39;");
  assert.equal(esc(undefined), "");
});
test("group containment validates ids, ownership, self-reference, and skips group-member overlap", () => {
  const m = base();
  const group = { id: "g", kind: "group" as const, lane: "l1", col: 0, row: 0, state: "ok", title: "G", contains: ["a"] };
  m.nodes.push(group);
  assert.ok(!codes(m).includes("cell-overlap"));
  group.contains = ["a", "g", "missing"];
  m.nodes.push({ ...group, id: "g2", contains: ["a"], row: 2 });
  const found = codes(m);
  assert.ok(found.includes("contains-self"));
  assert.ok(found.includes("contains-undefined"));
  assert.ok(found.includes("contains-duplicate"));
});
