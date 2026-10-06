import { test } from "node:test";
import assert from "node:assert/strict";
import { elbow, loopBack } from "./routing.ts";

test("same height is a straight line", () => assert.equal(elbow(0, 50, 100, 50, 50), "M0,50 H100"));
test("a small vertical step is a gentle S curve", () => assert.equal(elbow(0, 50, 100, 60, 50), "M0,50 C50,50 50,60 100,60"));
test("a large step is an elbow with a trunk at tx and rounded corners", () => {
  assert.equal(elbow(0, 50, 100, 150, 40), "M0,50 H32 Q40,50 40,58 V142 Q40,150 48,150 H100");
});
test("going up mirrors the corners", () => {
  assert.equal(elbow(0, 150, 100, 50, 40), "M0,150 H32 Q40,150 40,142 V58 Q40,50 48,50 H100");
});
test("every number in a path is finite", () => assert.ok(!/NaN|Infinity/.test(elbow(0, 0, 10, 300, 5))));
test("loop-back leaves and enters bottom edges for either horizontal direction", () => {
  for (const [x1, x2] of [[100, 20], [20, 100], [20, 20]]) {
    const p = loopBack(x1, 40, x2, 50, 90);
    assert.match(p, new RegExp(`^M${x1},40\\b`));
    assert.match(p, new RegExp(`50$`));
    assert.ok(!/NaN|Infinity/.test(p));
    assert.match(p, /Q/);
  }
});
test("loop-back clamps its corner radius for short channels", () => {
  const p = loopBack(10, 20, 10, 20, 23);
  assert.ok(!/NaN|Infinity/.test(p));
  assert.match(p, /^M10,20/);
});
test("a loop-back can detour around a node below its source", () => {
  const path = loopBack(100, 50, 20, 50, 120, { from: { x: 60, y: 54 } });
  assert.match(path, /^M100,50 V54 H60 V/);
  assert.match(path, /V50$/);
  assert.ok(!/NaN|Infinity/.test(path));
});
