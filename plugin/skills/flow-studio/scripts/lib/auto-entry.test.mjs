import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const validateScript = fileURLToPath(new URL("../validate.mjs", import.meta.url));
const buildScript = fileURLToPath(new URL("../build.mjs", import.meta.url));

test("validate and build lay out an auto model before checking it", () => {
  const dir = mkdtempSync(join(fileURLToPath(new URL(".", import.meta.url)), ".auto-entry-"));
  try {
    const modelPath = join(dir, "model.json"), pagePath = join(dir, "page.html");
    const model = {
      version: 1, meta: { title: "Auto", help: "", asOf: "", source: "" }, layout: "auto", columns: [], lanes: [],
      states: { ok: { word: "OK", tone: "ok", border: "solid", edge: "flow", motion: "flow", bucket: "good" } },
      nodes: ["a", "b"].map(id => ({ id, kind: "card", state: "ok", title: id })),
      links: [{ id: "ab", from: "a", to: "b", state: "ok" }],
    };
    writeFileSync(modelPath, JSON.stringify(model));
    const run = (script, extra = []) => spawnSync(process.execPath, ["--experimental-strip-types", "--no-warnings", script, modelPath, ...extra], { cwd: dir, encoding: "utf8" });
    const valid = run(validateScript);
    assert.equal(valid.status, 0, valid.stdout + valid.stderr);
    const built = run(buildScript, [pagePath]);
    assert.equal(built.status, 0, built.stdout + built.stderr);
    const page = readFileSync(pagePath, "utf8");
    assert.match(page, /"layout":"auto"/);
    assert.match(page, /"title":"Stage 2"/);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
