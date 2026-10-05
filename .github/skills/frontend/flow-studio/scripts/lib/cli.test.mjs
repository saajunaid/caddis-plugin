import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(fileURLToPath(import.meta.url), "../../..");
const run = (script, ...args) =>
  spawnSync(process.execPath, ["--experimental-strip-types", "--no-warnings", join(root, "scripts", script), ...args], { encoding: "utf8" });

const good = {
  version: 1,
  meta: { title: "T", help: "h", asOf: "2026-01-01", source: "s" },
  layout: "columns-lanes",
  columns: [{ id: "c0", title: "A", width: 150 }, { id: "c1", title: "B", width: 150 }],
  lanes: [{ id: "l1", title: "Lane" }],
  states: { ok: { word: "OK", tone: "ok", border: "solid", edge: "flow", motion: "flow", bucket: "good" } },
  nodes: [
    { id: "a", kind: "card", lane: "l1", col: 0, row: 0, state: "ok", title: "A" },
    { id: "b", kind: "card", lane: "l1", col: 1, row: 0, state: "ok", title: "B" },
  ],
  links: [{ id: "a-b", from: "a", to: "b", state: "ok" }],
};
const dir = mkdtempSync(join(tmpdir(), "flow-studio-"));
const write = (name, value) => { const p = join(dir, name); writeFileSync(p, typeof value === "string" ? value : JSON.stringify(value)); return p; };

test("validate: a good model exits 0 and prints OK", () => {
  const r = run("validate.mjs", write("good.json", good));
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stdout, /OK/);
});
test("validate: a missing file exits 2", () => assert.equal(run("validate.mjs", join(dir, "nope.json")).status, 2));
test("validate: invalid JSON exits 2", () => assert.equal(run("validate.mjs", write("bad.json", "{not json")).status, 2));
test("validate: a link to a missing node exits 1 and names the link", () => {
  const m = structuredClone(good);
  m.links[0].to = "zzz";
  const r = run("validate.mjs", write("broken.json", m));
  assert.equal(r.status, 1);
  assert.match(r.stdout, /links\[a-b\]/);
});
test("build: a note file cannot override the numbering and must be an array", () => {
  const out = join(dir, "out-notes.html");
  const p = write("notes-model.json", good);
  const notes = write("notes.json", [{ id: 99, anchor: "#viewport", title: "One", text: "t" }, { anchor: "#tools", title: "Two", text: "t" }]);
  // the build needs the generated engine; this test only needs it to exist
  const r = run("build.mjs", p, out, "--notes", notes);
  assert.equal(r.status, 0, r.stderr);
  const html = readFileSync(out, "utf8");
  const m = html.match(/id="flow-notes">(.*?)<\/script>/s);
  const parsed = JSON.parse(m[1]);
  assert.deepEqual(parsed.map(n => n.id), [1, 2]);
  const bad = write("notes-bad.json", { not: "an array" });
  assert.equal(run("build.mjs", p, join(dir, "out-bad.html"), "--notes", bad).status, 2);
});
test("build: refuses a model with errors and writes nothing", () => {
  const m = structuredClone(good);
  m.nodes[0].lane = "nope";
  const out = join(dir, "out-refused.html");
  const r = run("build.mjs", write("refused.json", m), out);
  assert.equal(r.status, 1);
  assert.equal(existsSync(out), false);
});
