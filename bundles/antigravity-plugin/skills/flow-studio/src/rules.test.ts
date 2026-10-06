import { test } from "node:test";
import assert from "node:assert/strict";
import type { Model } from "./model.ts";
import { baselineView, defaultView, nodeVisible, nodeStateId, linkVisible, linkStateId, isNew, isImproved, bucketOf, canonOf, effectiveLinks, initialCollapsed, columnTitle, toggleGroupState } from "./rules.ts";

const m = (): Model => ({
  version: 1,
  meta: { title: "t", help: "", asOf: "", source: "" },
  layout: "columns-lanes",
  columns: [{ id: "c0", title: "A", width: 150 }, { id: "c1", title: "B", width: 150 }],
  lanes: [{ id: "l1", title: "L" }],
  states: {
    good: { word: "GOOD", tone: "ok", border: "solid", edge: "flow", motion: "flow", bucket: "good" },
    gap: { word: "GAP", tone: "warn", border: "dotted", edge: "dot", motion: "breathe", bucket: "gap" },
  },
  views: [{ id: "today", label: "Today" }, { id: "full", label: "Full", default: true }],
  nodes: [
    { id: "a", kind: "card", lane: "l1", col: 0, row: 0, state: "good", title: "A" },
    { id: "b", kind: "card", lane: "l1", col: 1, row: 0, state: "good", stateIn: { today: "gap" }, title: "B" },
    { id: "c", kind: "card", lane: "l1", col: 1, row: 1.8, state: "good", visibleIn: ["full"], title: "C" },
    { id: "k", kind: "chip", lane: "l1", col: 0, row: 3.6, state: "good", ref: "a", title: "k" },
  ],
  links: [
    { id: "a-b", from: "a", to: "b", state: "good" },
    { id: "a-c", from: "a", to: "c", state: "good", stateIn: { today: "gap" } },
    { id: "only-today", from: "a", to: "b", state: "gap", visibleIn: ["today"] },
  ],
});
const byId = (mm: Model) => new Map(mm.nodes.map(n => [n.id, n]));

test("the baseline is the first view and the default is the marked one", () => {
  assert.equal(baselineView(m()), "today");
  assert.equal(defaultView(m()), "full");
});
test("a model with no views has one implicit view", () => {
  const mm = m(); delete mm.views;
  assert.equal(baselineView(mm), "all");
  assert.equal(defaultView(mm), "all");
  assert.equal(nodeVisible(mm, "all", mm.nodes[0]!), true);
});
test("visibleIn hides a node in other views", () => {
  const mm = m();
  assert.equal(nodeVisible(mm, "today", mm.nodes[2]!), false);
  assert.equal(nodeVisible(mm, "full", mm.nodes[2]!), true);
});
test("stateIn overrides the state in that view only", () => {
  const mm = m();
  assert.equal(nodeStateId(mm, "today", mm.nodes[1]!), "gap");
  assert.equal(nodeStateId(mm, "full", mm.nodes[1]!), "good");
});
test("a link is hidden when an end is hidden", () => {
  const mm = m(), nodes = byId(mm);
  assert.equal(linkVisible(mm, "today", mm.links[1]!, nodes), false);
  assert.equal(linkVisible(mm, "full", mm.links[1]!, nodes), true);
});
test("visibleIn on a link restricts it to those views", () => {
  const mm = m(), nodes = byId(mm);
  assert.equal(linkVisible(mm, "today", mm.links[2]!, nodes), true);
  assert.equal(linkVisible(mm, "full", mm.links[2]!, nodes), false);
});
test("a link state can differ per view", () => {
  const mm = m();
  assert.equal(linkStateId(mm, "today", mm.links[1]!), "gap");
  assert.equal(linkStateId(mm, "full", mm.links[1]!), "good");
});
test("isNew: visible now, not in the baseline view", () => {
  const mm = m();
  assert.equal(isNew(mm, "full", mm.nodes[2]!), true);
  assert.equal(isNew(mm, "today", mm.nodes[2]!), false);
  assert.equal(isNew(mm, "full", mm.nodes[0]!), false);
});
test("isImproved: a gap in the baseline that is not a gap now", () => {
  const mm = m();
  assert.equal(isImproved(mm, "full", mm.nodes[1]!), true);
  assert.equal(isImproved(mm, "today", mm.nodes[1]!), false);
  assert.equal(isImproved(mm, "full", mm.nodes[0]!), false);
});
test("bucketOf reads the bucket of a state, and an unknown state is a gap (never a good)", () => {
  const mm = m();
  assert.equal(bucketOf(mm, "good"), "good");
  assert.equal(bucketOf(mm, "nope"), "gap");
});
test("canonOf maps a chip to its real node and leaves others alone", () => {
  const mm = m(), nodes = byId(mm);
  assert.equal(canonOf(nodes, "k"), "a");
  assert.equal(canonOf(nodes, "b"), "b");
  assert.equal(canonOf(nodes, "missing"), "missing");
});
test("collapsed groups replace members and merge duplicate links with the worst state", () => {
  const mm = m();
  mm.nodes.push({ id: "group", kind: "group", lane: "l1", col: 0, row: 5, state: "good", title: "Group", contains: ["a", "b"] });
  mm.links.push({ id: "b-c", from: "b", to: "c", state: "gap" });
  mm.links.push({ id: "a-b", from: "a", to: "b", state: "good" });
  const collapsed = new Set(["group"]), nodes = byId(mm);
  assert.equal(nodeVisible(mm, "full", mm.nodes.find(n => n.id === "a")!, collapsed), false);
  assert.equal(nodeVisible(mm, "full", mm.nodes.find(n => n.id === "group")!, collapsed), true);
  const links = effectiveLinks(mm, "full", collapsed, nodes);
  assert.equal(links.filter(l => l.from === "group" && l.to === "c").length, 1);
  assert.equal(links.find(l => l.from === "group" && l.to === "c")?.state, "gap");
  assert.ok(!links.some(l => l.from === l.to));
  collapsed.clear();
  assert.equal(nodeVisible(mm, "full", mm.nodes.find(n => n.id === "a")!, collapsed), true);
  assert.equal(nodeVisible(mm, "full", mm.nodes.find(n => n.id === "group")!, collapsed), false);
});

test("groups with contains start collapsed unless collapsed is false", () => {
  const mm = m();
  mm.nodes.push({ id: "default", kind: "group", lane: "l1", state: "good", title: "Default", contains: ["a"] });
  mm.nodes.push({ id: "expanded", kind: "group", lane: "l1", state: "good", title: "Expanded", contains: ["b"], collapsed: false });
  const collapsed = initialCollapsed(mm);
  assert.deepEqual([...collapsed], ["default"]);
  assert.equal(nodeVisible(mm, "full", mm.nodes.find(n => n.id === "a")!, collapsed), false);
  assert.equal(nodeVisible(mm, "full", mm.nodes.find(n => n.id === "b")!, collapsed), true);
});
test("a free node with no column has an empty table column", () => {
  const mm = m(); mm.layout = "free";
  delete mm.nodes[0]!.col;
  assert.equal(columnTitle(mm, mm.nodes[0]!), "");
  assert.equal(columnTitle(mm, mm.nodes[1]!), "B");
});
test("toggleGroup selects a visible child on expansion and its group on collapse", () => {
  const mm = m();
  mm.nodes.push({ id: "group", kind: "group", lane: "l1", state: "good", title: "Group", contains: ["a", "b"] });
  const starting = new Set(["group"]);
  const expanded = toggleGroupState(mm, "full", starting, "group")!;
  assert.equal(expanded.expanding, true);
  assert.equal(expanded.selected, "a");
  assert.equal(expanded.collapsed.has("group"), false);
  assert.equal(starting.has("group"), true);
  const folded = toggleGroupState(mm, "full", expanded.collapsed, "group")!;
  assert.equal(folded.expanding, false);
  assert.equal(folded.selected, "group");
  assert.equal(folded.collapsed.has("group"), true);
  assert.equal(toggleGroupState(mm, "full", starting, "missing"), null);
});
