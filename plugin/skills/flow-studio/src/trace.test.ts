import { test } from "node:test";
import assert from "node:assert/strict";
import { relatives, connected } from "./trace.ts";

const edges = [{ from: "a", to: "b" }, { from: "b", to: "c" }, { from: "x", to: "c" }, { from: "c", to: "d" }];
const id = (s: string) => s;

test("downstream follows links forward", () => assert.deepEqual([...relatives(edges, id, "b", "down")].sort(), ["b", "c", "d"]));
test("upstream follows links backward", () => assert.deepEqual([...relatives(edges, id, "c", "up")].sort(), ["a", "b", "c", "x"]));
test("connected is up plus down", () => assert.deepEqual([...connected(edges, id, "b")].sort(), ["a", "b", "c", "d"]));
test("a chip is an alias of its real node", () => {
  const canon = (s: string) => (s === "b2" ? "b" : s);
  const e = [...edges, { from: "b2", to: "z" }];
  assert.ok(relatives(e, canon, "b", "down").has("z"));
});
test("a cycle terminates", () => {
  const cyc = [{ from: "a", to: "b" }, { from: "b", to: "a" }];
  assert.deepEqual([...relatives(cyc, id, "a", "down")].sort(), ["a", "b"]);
});
test("an unknown start returns only itself", () => assert.deepEqual([...relatives(edges, id, "nope", "down")], ["nope"]));
