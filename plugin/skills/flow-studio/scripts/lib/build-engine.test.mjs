import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { buildEngine, resolveEsbuild } from "../build-engine.mjs";

const normalise = t => t.replace(/\r\n/g, "\n");
test("esbuild resolution chooses the first candidate and respects order", () => {
  const dir = mkdtempSync(new URL("./flow-studio-esbuild-", import.meta.url));
  try {
    const candidates = [join(dir, "first"), join(dir, "second")];
    for (const [i, candidate] of candidates.entries()) {
      const pkg = join(candidate, "node_modules", "esbuild");
      mkdirSync(pkg, { recursive: true });
      writeFileSync(join(pkg, "package.json"), JSON.stringify({ name: "esbuild", main: "index.js" }));
      writeFileSync(join(pkg, "index.js"), `module.exports = { source: ${JSON.stringify(i)} };`);
    }
    assert.equal(resolveEsbuild(candidates).source, 0);
    assert.equal(resolveEsbuild(candidates.toReversed()).source, 1);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("empty candidate folders give an actionable esbuild error", () => {
  const dir = mkdtempSync(new URL("./flow-studio-esbuild-", import.meta.url));
  try {
    const empty = [join(dir, "one"), join(dir, "two")];
    empty.forEach(p => mkdirSync(p));
    assert.throws(() => resolveEsbuild(empty), /FLOW_STUDIO_NODE_MODULES.*npm i -D esbuild/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

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
