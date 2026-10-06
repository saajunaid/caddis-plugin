import { test } from "node:test";
import assert from "node:assert/strict";
import { prepareModel } from "./auto-entry-guard.mjs";

test("auto layout runs only when its four input arrays exist", () => {
  const model = { layout: "auto", nodes: [], links: [], columns: [], lanes: [] };
  const laidOut = { ...model, applied: true };
  const layout = input => { assert.equal(input, model); return laidOut; };
  assert.equal(prepareModel(model, layout), laidOut);
  for (const field of ["nodes", "links", "columns", "lanes"]) {
    assert.equal(prepareModel({ ...model, [field]: null }, () => { throw Error("called"); })[field], null);
  }
  assert.equal(prepareModel({ ...model, layout: "free" }, () => { throw Error("called"); }).layout, "free");
});
