import { test } from "node:test";
import assert from "node:assert/strict";
import { notifySelection } from "./selection.ts";

test("selection callback reports changes and clears once", () => {
  const seen: Array<string | null> = [];
  const notify = (id: string | null) => seen.push(id);
  notifySelection(null, "a", notify);
  notifySelection("a", "a", notify);
  notifySelection("a", null, notify);
  assert.deepEqual(seen, ["a", null]);
});
