import { test } from "node:test";
import assert from "node:assert/strict";
import { placeHover } from "./hover.ts";
import { validateModel, type Model } from "./model.ts";

const vp = { x: 20, y: 40, w: 800, h: 600 };

test("placeHover places the card 8 px below the node aligned to its left edge", () => {
  const pos = placeHover({ x: 120, y: 140, w: 180, h: 54 }, vp, { w: 220, h: 80 });
  assert.deepEqual(pos, { left: 100, top: 162, side: "below" });
});

test("placeHover flips above the node when placing below would overflow the viewport", () => {
  const pos = placeHover({ x: 120, y: 560, w: 180, h: 54 }, vp, { w: 220, h: 90 });
  assert.deepEqual(pos, { left: 100, top: 422, side: "above" });
});

test("placeHover clamps left and right to 8 px inside the viewport", () => {
  const leftClamped = placeHover({ x: 22, y: 140, w: 180, h: 54 }, vp, { w: 220, h: 80 });
  assert.equal(leftClamped.left, 8);
  assert.equal(leftClamped.side, "below");

  const rightClamped = placeHover({ x: 700, y: 140, w: 180, h: 54 }, vp, { w: 220, h: 80 });
  assert.equal(rightClamped.left, 800 - 8 - 220);
  assert.equal(rightClamped.side, "below");
});

test("placeHover places a card wider than the viewport at left 8", () => {
  const narrowVp = { x: 10, y: 10, w: 260, h: 600 };
  const pos = placeHover({ x: 100, y: 90, w: 180, h: 54 }, narrowVp, { w: 320, h: 80 });
  assert.equal(pos.left, 8);
});

const base = (): Model => ({
  version: 1,
  meta: { title: "T", help: "h", asOf: "2026-01-01", source: "s" },
  layout: "columns-lanes",
  columns: [{ id: "c0", title: "A", width: 150 }],
  lanes: [{ id: "l1", title: "Lane 1" }],
  states: { ok: { word: "OK", tone: "ok", border: "solid", edge: "flow", motion: "flow", bucket: "good" } },
  nodes: [{ id: "a", kind: "card", lane: "l1", col: 0, row: 0, state: "ok", title: "A", allowIsolated: true }],
  links: [],
});
const codes = (m: unknown) => validateModel(m).filter(i => i.level === "error").map(i => i.code);

test("validator accepts an empty hover array and up to 12 strings of up to 240 characters", () => {
  const empty = base();
  (empty.nodes[0] as unknown as { hover: unknown }).hover = [];
  assert.deepEqual(codes(empty), []);

  const twelve = base();
  (twelve.nodes[0] as unknown as { hover: unknown }).hover = Array.from({ length: 12 }, (_, i) => i === 0 ? "x".repeat(240) : `line ${i + 1}`);
  assert.deepEqual(codes(twelve), []);
});

test("validator reports hover-invalid for a non-array string", () => {
  const m = base();
  (m.nodes[0] as unknown as { hover: unknown }).hover = "not an array";
  assert.ok(codes(m).includes("hover-invalid"));
});

test("validator reports hover-invalid for a non-string item", () => {
  const m = base();
  (m.nodes[0] as unknown as { hover: unknown }).hover = ["ok", 42];
  assert.ok(codes(m).includes("hover-invalid"));
});

test("validator reports hover-invalid for more than 12 items", () => {
  const m = base();
  (m.nodes[0] as unknown as { hover: unknown }).hover = Array.from({ length: 13 }, (_, i) => `line ${i}`);
  assert.ok(codes(m).includes("hover-invalid"));
});

test("validator reports hover-invalid for an item longer than 240 characters", () => {
  const m = base();
  (m.nodes[0] as unknown as { hover: unknown }).hover = ["x".repeat(241)];
  assert.ok(codes(m).includes("hover-invalid"));
});
