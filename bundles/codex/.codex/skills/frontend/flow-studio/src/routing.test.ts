import { test } from "node:test";
import assert from "node:assert/strict";
import { elbow } from "./routing.ts";

test("same height is a straight line", () => assert.equal(elbow(0, 50, 100, 50, 50), "M0,50 H100"));
test("a small vertical step is a gentle S curve", () => assert.equal(elbow(0, 50, 100, 60, 50), "M0,50 C50,50 50,60 100,60"));
test("a large step is an elbow with a trunk at tx and rounded corners", () => {
  assert.equal(elbow(0, 50, 100, 150, 40), "M0,50 H32 Q40,50 40,58 V142 Q40,150 48,150 H100");
});
test("going up mirrors the corners", () => {
  assert.equal(elbow(0, 150, 100, 50, 40), "M0,150 H32 Q40,150 40,142 V58 Q40,50 48,50 H100");
});
test("every number in a path is finite", () => assert.ok(!/NaN|Infinity/.test(elbow(0, 0, 10, 300, 5))));
