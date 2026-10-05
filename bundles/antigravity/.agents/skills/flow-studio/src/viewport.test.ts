import { test } from "node:test";
import assert from "node:assert/strict";
import { zoomAt, fitRect, fitWidth, clampPan, clampK, K_MIN, K_MAX } from "./viewport.ts";

const close = (a: number, b: number, e = 1e-6) => assert.ok(Math.abs(a - b) < e, `${a} vs ${b}`);

test("zoomAt keeps the point under the cursor fixed", () => {
  const v = { x: 40, y: -20, k: 0.8 }, cx = 300, cy = 200;
  const w = { x: (cx - v.x) / v.k, y: (cy - v.y) / v.k };
  const z = zoomAt(v, 1.7, cx, cy);
  close(z.x + w.x * z.k, cx);
  close(z.y + w.y * z.k, cy);
});
test("zoom is clamped to 0.25 and 2.5", () => {
  assert.equal(zoomAt({ x: 0, y: 0, k: 2.4 }, 10, 0, 0).k, K_MAX);
  assert.equal(zoomAt({ x: 0, y: 0, k: 0.3 }, 0.01, 0, 0).k, K_MIN);
  assert.ok(Number.isFinite(clampK(NaN)));
});
test("zoomAt returns finite numbers even from a bad scale", () => {
  for (const k of [0, NaN, -1]) {
    const z = zoomAt({ x: 5, y: 5, k }, 1.2, 100, 100);
    assert.ok([z.x, z.y, z.k].every(Number.isFinite), `k=${k}`);
  }
});
test("fitRect centres, never enlarges above 1 and never goes below 0.25", () => {
  const v = fitRect({ x: 0, y: 0, w: 100, h: 50 }, { w: 1000, h: 800 }, 28, 52);
  assert.equal(v.k, 1);
  const w = fitRect({ x: 0, y: 0, w: 100000, h: 50 }, { w: 1000, h: 800 }, 28, 52);
  assert.equal(w.k, K_MIN);
});
test("fitRect gives finite numbers for a zero-size container (review focus 5)", () => {
  const v = fitRect({ x: 0, y: 0, w: 500, h: 400 }, { w: 0, h: 0 }, 28, 52);
  assert.ok([v.x, v.y, v.k].every(Number.isFinite));
});
test("fitRect gives finite numbers for an empty rectangle (review focus 2)", () => {
  const v = fitRect({ x: 0, y: 0, w: 0, h: 0 }, { w: 1000, h: 800 }, 28, 52);
  assert.ok([v.x, v.y, v.k].every(Number.isFinite));
});
test("fitWidth fits the width and starts at the top", () => {
  const v = fitWidth({ x: 10, y: 20, w: 2000, h: 5000 }, { w: 1056, h: 600 }, 28, 52);
  close(v.k, 1000 / 2000);
  close(v.x, 28 - 10 * v.k);
  close(v.y, 52 - 20 * v.k);
});
test("fitWidth is finite for an empty rectangle and a zero width", () => {
  const a = fitWidth({ x: 0, y: 0, w: 0, h: 0 }, { w: 800, h: 600 }, 28, 52);
  const b = fitWidth({ x: 0, y: 0, w: 900, h: 400 }, { w: 0, h: 0 }, 28, 52);
  assert.ok([a.x, a.y, a.k, b.x, b.y, b.k].every(Number.isFinite));
});
test("clampPan keeps 80 px of the graph visible", () => {
  const b = { x: 0, y: 0, w: 1000, h: 800 }, size = { w: 1000, h: 700 };
  const far = clampPan({ x: -99999, y: 99999, k: 1 }, b, size);
  assert.equal(far.x, 80 - 1000);
  assert.equal(far.y, 700 - 80);
});
