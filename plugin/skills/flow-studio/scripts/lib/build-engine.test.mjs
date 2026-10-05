import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { buildEngine } from "../build-engine.mjs";

const normalise = t => t.replace(/\r\n/g, "\n");

test("the generated engine has no external URL and keeps only the model and notes slots", async () => {
  const html = await buildEngine();
  const urls = html.match(/https?:\/\/[^\s"'<>)\\]+/g) ?? [];
  const external = urls.filter(u => u !== "http://www.w3.org/2000/svg");
  assert.deepEqual(external, [], "external URL found");
  assert.ok(!html.includes("/*__CSS__*/") && !html.includes("/*__ENGINE__*/"));
  assert.equal(html.split("/*__MODEL__*/{}").length - 1, 1);
  assert.equal(html.split("/*__NOTES__*/[]").length - 1, 1);
});
test("the engine bundle cannot end its own script tag", async () => {
  const html = await buildEngine();
  const scripts = html.match(/<\/script>/g) ?? [];
  assert.equal(scripts.length, 3, "exactly the three script tags of the shell");
});
test("the committed engine matches the sources", async () => {
  const fresh = await buildEngine();
  const committed = normalise(readFileSync(new URL("../../templates/engine.html", import.meta.url), "utf8"));
  assert.equal(committed, fresh, "run: node --experimental-strip-types scripts/build-engine.mjs");
});
