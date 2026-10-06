// Proves the checks can fail: each fixture is a page with one deliberate defect, and check.mjs must exit 1
// and name the matching check. Skipped when Playwright cannot be resolved from the current folder.
// Run it from a folder that has Playwright, for example:
//   FLOW_STUDIO_CHANNEL=msedge node --test <skill>/scripts/lib/check-selftest.test.mjs

import { test, after } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { embedModel } from "./embed.mjs";

const root = resolve(fileURLToPath(import.meta.url), "../../..");
let hasPlaywright = true;
try { createRequire(join(process.cwd(), "x.js")).resolve("playwright"); } catch { hasPlaywright = false; }
const skip = hasPlaywright ? false : "playwright is not resolvable from the current folder";

const engine = readFileSync(join(root, "templates/engine.html"), "utf8");
const base = JSON.parse(readFileSync(join(root, "examples/lineage.json"), "utf8"));
const order = JSON.parse(readFileSync(join(root, "examples/order-desk.json"), "utf8"));
const dir = mkdtempSync(join(root, ".flow-selftest-"));
after(() => rmSync(dir, { recursive: true, force: true }));

function page(name, { model = base, inject = "" } = {}) {
  const html = embedModel(engine, model, []).replace("</body>", `${inject}</body>`);
  const p = join(dir, name + ".html");
  writeFileSync(p, html);
  return p;
}
function run(p) {
  const args = [join(root, "scripts/check.mjs"), p, "--out", join(dir, "shots"), "--viewports", "1600x900", "--skip-perf"];
  if (process.env.FLOW_STUDIO_CHANNEL) args.push("--channel", process.env.FLOW_STUDIO_CHANNEL);
  return spawnSync(process.execPath, args, { encoding: "utf8", cwd: process.cwd(), timeout: 120000 });
}
const expectFail = (r, pattern) => {
  assert.equal(r.status, 1, r.stdout + r.stderr);
  assert.match(r.stdout, new RegExp("FAIL.*" + pattern, "i"), r.stdout);
};

test("a clean page passes every check", { skip }, () => {
  const r = run(page("clean"));
  assert.equal(r.status, 0, r.stdout + r.stderr);
});

test("a clean page with a metric on a collapsed child passes every check", { skip }, () => {
  const r = run(page("clean-order-desk", { model: order }));
  assert.equal(r.status, 0, r.stdout + r.stderr);
});

test("two nodes in one place fail the intersection check", { skip }, () => {
  const m = structuredClone(base);
  m.nodes.find(n => n.id === "T_WH").row = m.nodes.find(n => n.id === "D_WH").row; // same row, other column: move it onto a neighbour
  const a = m.nodes.find(n => n.id === "J_W47"), b = m.nodes.find(n => n.id === "J_BILL");
  b.row = a.row; // same column, same row
  expectFail(run(page("overlap", { model: m })), "zero node-box intersections");
});

test("a control with no name fails the accessible-name check", { skip }, () => {
  const inject = `<script>window.addEventListener("load", () => setTimeout(() => { const b = document.querySelector("#tools button"); b.removeAttribute("aria-label"); b.removeAttribute("title"); }, 300));</script>`;
  expectFail(run(page("noname", { inject })), "accessible name");
});

test("a remote image fails the no-network check", { skip }, () => {
  expectFail(run(page("remote", { inject: `<img src="https://example.invalid/x.png" alt="">` })), "no network requests");
});

test("faint text fails the contrast check", { skip }, () => {
  expectFail(run(page("faint", { inject: `<style>.node .s, .node .name { color:#d8d8d8 !important; }</style>` })), "contrast");
});

test("a looping animation under reduced motion fails the reduced-motion check", { skip }, () => {
  expectFail(run(page("motion", { inject: `<style>@media (prefers-reduced-motion: reduce) { .node { animation: rise 1s infinite !important; } }</style>` })), "reduced motion");
});

test("a canvas too wide to read fails the first-view check", { skip }, () => {
  const m = structuredClone(base);
  m.columns.forEach(c => { c.width = 700; });
  expectFail(run(page("wide", { model: m })), "first view is readable");
});
test("a moved loop path fails the link-endpoint check", { skip }, () => {
  const m = structuredClone(base);
  const link = m.links[0];
  link.from = "H_DB1";
  link.to = "ORD";
  link.kind = "loop-back";
  const inject = `<script>window.addEventListener("load", () => setTimeout(() => { document.querySelector("path.edge.loop")?.setAttribute("d", "M0,0 H10"); }, 300));</script>`;
  expectFail(run(page("moved-loop", { model: m, inject })), "every link end touches its node box");
});
test("a node moved onto a loop path fails the loop clearance check", { skip }, () => {
  const m = structuredClone(base);
  m.links.push({ id: "return-check", from: "H_DB1", to: "ORD", state: m.links[0].state, kind: "loop-back" });
  const inject = `<script>window.addEventListener("load", () => setTimeout(() => {
    const path = [...document.querySelectorAll("path.edge.loop")].find(p => !p.classList.contains("off"));
    const node = [...document.querySelectorAll(".node:not(.off)")].find(n => n.id !== "n_" + path?.dataset.a && n.id !== "n_" + path?.dataset.b);
    if (path && node) { const point = path.getPointAtLength(path.getTotalLength() / 2);
      node.style.left = (point.x - 20) + "px"; node.style.top = (point.y - 20) + "px"; }
  }, 300));</script>`;
  expectFail(run(page("blocked-loop", { model: m, inject })), "no loop-back path passes through a visible node");
});
test("a gateway without its diamond fails the gateway check", { skip }, () => {
  const m = structuredClone(base);
  const gate = m.nodes.find(n => n.id === "H_DB1");
  gate.kind = "gateway";
  const inject = `<script>window.addEventListener("load", () => setTimeout(() => { document.querySelector(".node.gateway polygon")?.remove(); }, 300));</script>`;
  expectFail(run(page("no-gateway-polygon", { model: m, inject })), "gateway.*polygon");
});

test("a hidden playback token fails the movement check", { skip }, () => {
  expectFail(run(page("hidden-token", { model: order, inject: `<style>#token { display:none !important; }</style>` })), "Play moves the token");
});

test("an update that does nothing fails the live update check", { skip }, () => {
  const inject = `<script>window.addEventListener("load", () => setTimeout(() => { window.FlowStudio.update = () => ({ ok:true, issues:[] }); }, 300));</script>`;
  expectFail(run(page("noop-update", { model: order, inject })), "update marks changed and added nodes");
});

test("a first scenario with a single step still passes every check", { skip }, () => {
  const m = structuredClone(order);
  m.scenarios[0].steps = m.scenarios[0].steps.slice(0, 1); // one step is legal (minItems 1)
  const r = run(page("one-step", { model: m }));
  assert.equal(r.status, 0, r.stdout + r.stderr);
});

test("an SLA breach is found without a scenario named escalated", { skip }, () => {
  const m = structuredClone(order);
  m.scenarios.find(s => s.id === "escalated").id = "surged";
  const r = run(page("renamed-escalated", { model: m }));
  assert.equal(r.status, 0, r.stdout + r.stderr);
});

test("hidden branch buttons fail the branch-button checks", { skip }, () => {
  expectFail(run(page("hidden-choices", { model: order, inject: `<style>#pbChoices { display:none !important; }</style>` })), "keeps the branch buttons");
});
