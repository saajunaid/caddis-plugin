// Playwright check harness for a flow-studio page. Model-agnostic: it reads the model from the page.
//   node scripts/check.mjs <page.html> [--out dir] [--viewports 1600x900,1280x720,820x900]
//        [--channel msedge] [--hostile hostile.html] [--json report.json] [--skip-perf]
// Run it from a folder that can resolve "playwright" (the project's node_modules). Exit 0: every check passed.

import { createRequire } from "node:module";
import { isDeepStrictEqual } from "node:util";
import { mkdirSync, writeFileSync } from "node:fs";
import { resolve, join } from "node:path";
import { pageUrl, skippedGroups } from "./lib/check-args.mjs";

const argv = process.argv.slice(2);
const opt = (name, dflt) => { const i = argv.indexOf(name); return i >= 0 ? argv[i + 1] : dflt; };
const flag = name => argv.includes(name);
const pageArg = argv[0];
if (!pageArg || pageArg.startsWith("--")) { console.error("usage: node scripts/check.mjs <page.html|URL> [--out dir] [--viewports WxH,...] [--channel msedge] [--hostile page.html|URL] [--json file] [--skip-perf] [--skip notes,playback,update,hostile]"); process.exit(2); }
let skip;
try { skip = skippedGroups(opt("--skip", "")); } catch (error) { console.error(error.message); process.exit(2); }
const outDir = resolve(opt("--out", "check-out"));
const viewports = opt("--viewports", "1600x900,1280x720,820x900").split(",").map(v => v.split("x").map(Number));
const channel = opt("--channel", undefined);
const hostilePath = opt("--hostile", undefined);
mkdirSync(outDir, { recursive: true });

let chromium;
for (const base of [process.cwd(), process.env.FLOW_STUDIO_NODE_MODULES && resolve(process.env.FLOW_STUDIO_NODE_MODULES, "..")].filter(Boolean)) {
  try { ({ chromium } = createRequire(join(base, "x.js"))("playwright")); break; } catch { /* try next location */ }
}
if (!chromium) { console.error("Cannot resolve 'playwright'. Run this from a folder whose node_modules has it (npm i -D playwright)."); process.exit(2); }

const results = [];
const check = (group, name, ok, detail = "") => { results.push({ group, name, ok: !!ok, detail: String(detail) }); console.log(`${ok ? "PASS" : "FAIL"}  [${group}] ${name}${detail ? "  " + detail : ""}`); };

// ---- helpers that run in the page
const inPage = {
  state: () => {
    const f = window.FlowStudio;
    return { view: f.view(), selected: f.selected(), mode: f.mode() };
  },
};
const url = pageUrl;
const targetUrl = url(pageArg);
const localOrigin = new URL(targetUrl).protocol.startsWith("http") ? new URL(targetUrl).origin : null;

// ---- model-side helpers (run here, from the model the page reports)
function modelRules(model) {
  const view = (model.views?.find(v => v.default) ?? model.views?.[0])?.id ?? "all";
  const nodes = new Map(model.nodes.map(n => [n.id, n]));
  const canon = id => nodes.get(id)?.ref ?? id;
  const collapsed = new Set(model.nodes.filter(n => n.kind === "group" && n.contains?.length && n.collapsed !== false).map(n => n.id));
  const owner = id => model.nodes.find(n => n.kind === "group" && n.contains?.includes(id));
  const nv = (n, v = view) => !!n && (!n.visibleIn || n.visibleIn.includes(v))
    && (n.kind === "group" && n.contains ? collapsed.has(n.id) : !collapsed.has(owner(n.id)?.id));
  const endpoint = id => collapsed.has(owner(id)?.id) ? owner(id).id : id;
  const lv = (l, v = view) => (!l.visibleIn || l.visibleIn.includes(v)) && nodes.get(l.from) && nodes.get(l.to)
    && nv(nodes.get(endpoint(l.from)), v) && nv(nodes.get(endpoint(l.to)), v) && endpoint(l.from) !== endpoint(l.to);
  const down = (start, v = view) => {
    const s = new Set([canon(start)]); let grew = true;
    while (grew) { grew = false; for (const l of model.links) { if (!lv(l, v)) continue; const a = canon(endpoint(l.from)), b = canon(endpoint(l.to)); if (s.has(a) && !s.has(b)) { s.add(b); grew = true; } } }
    return s;
  };
  return { view, nodes, canon, nv, lv, down, collapsed, endpoint };
}

const browser = await chromium.launch(channel ? { channel } : {});

// ================================================================= per viewport
for (const [w, h] of viewports) {
  const tag = `${w}x${h}`;
  const ctx = await browser.newContext({ viewport: { width: w, height: h }, colorScheme: "light" });
  const page = await ctx.newPage();
  const errors = [], requests = [];
  page.on("pageerror", e => errors.push(String(e)));
  page.on("console", m => { if (m.type() === "error") errors.push(m.text()); });
  page.on("request", r => { const u = r.url(); if (!u.startsWith("file:") && !u.startsWith("data:") && (!localOrigin || new URL(u).origin !== localOrigin)) requests.push(u); });
  await page.goto(targetUrl);
  await page.waitForFunction(() => !!window.FlowStudio, null, { timeout: 10000 });
  await page.waitForTimeout(900);
  const model = await page.evaluate(() => window.FlowStudio.model);
  const R = modelRules(model);
  const paintedHidden = await page.evaluate(() => [...document.querySelectorAll(".node.off")].filter(d => {
    const style = getComputedStyle(d);
    return style.visibility !== "hidden" && Number(style.opacity) > 0;
  }).map(d => d.id.slice(2)));
  check("structural", `${tag} hidden nodes are not painted`, paintedHidden.length === 0, paintedHidden.join(","));
  await page.screenshot({ path: join(outDir, `01-fit-${tag}.png`) });

  check("safety", `${tag} no page errors`, errors.length === 0, errors.join(" | "));
  check("safety", `${tag} no network requests`, requests.length === 0, requests.join(","));

  // ---------- structural
  const geo = await page.evaluate(() => {
    const g = window.FlowStudio.geometry();
    const vis = [...document.querySelectorAll(".node")].filter(d => !d.classList.contains("off")).map(d => d.id.slice(2));
    const lanes = Object.entries(g.lanes).map(([id, r]) => ({ id, ...r }));
    const nodes = vis.map(id => ({ id, ...g.nodes[id] }));
    return { nodes, lanes };
  });
  let overlaps = [];
  for (let i = 0; i < geo.nodes.length; i++) for (let j = i + 1; j < geo.nodes.length; j++) {
    const a = geo.nodes[i], b = geo.nodes[j];
    if (a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h) overlaps.push(`${a.id}/${b.id}`);
  }
  check("structural", `${tag} zero node-box intersections`, overlaps.length === 0, overlaps.join(","));
  let outside = [];
  for (const n of geo.nodes) {
    const def = R.nodes.get(n.id), lane = geo.lanes.find(l => l.id === def.lane);
    if (!lane || n.x < lane.x || n.y < lane.y || n.x + n.w > lane.x + lane.w || n.y + n.h > lane.y + lane.h) outside.push(n.id);
  }
  check("structural", `${tag} every node sits inside its lane`, outside.length === 0, outside.join(","));
  let laneOverlap = 0;
  for (let i = 0; i < geo.lanes.length; i++) for (let j = i + 1; j < geo.lanes.length; j++) { const a = geo.lanes[i], b = geo.lanes[j]; if (a.y < b.y + b.h && b.y < a.y + a.h) laneOverlap++; }
  check("structural", `${tag} no lane overlap`, laneOverlap === 0, `overlaps=${laneOverlap}`);

  const ends = await page.evaluate(() => {
    const g = window.FlowStudio.geometry(), bad = [];
    document.querySelectorAll("path.edge:not(.off)").forEach(p => {
      const a = g.nodes[p.dataset.a], b = g.nodes[p.dataset.b], len = p.getTotalLength();
      const s = p.getPointAtLength(0), e = p.getPointAtLength(len);
      const loop = p.classList.contains("loop");
      const okA = loop
        ? a && Math.abs(s.x - (a.x + a.w / 2)) <= 2 && Math.abs(s.y - (a.y + a.h)) <= 2
        : a && Math.abs(s.x - (a.x + a.w)) <= 2 && s.y >= a.y - 2 && s.y <= a.y + a.h + 2;
      const okB = loop
        ? b && Math.abs(e.x - (b.x + b.w / 2)) <= 2 && Math.abs(e.y - (b.y + b.h)) <= 2
        : b && Math.abs(e.x - (b.x - 1)) <= 2 && e.y >= b.y - 2 && e.y <= b.y + b.h + 2;
      if (!okA || !okB) bad.push(p.dataset.a + ">" + p.dataset.b);
    });
    return bad;
  });
  check("structural", `${tag} every link end touches its node box (within 2 px)`, ends.length === 0, ends.join(","));

  const crossedLoops = await page.evaluate(() => {
    const boxes = [...document.querySelectorAll(".node:not(.off)")].map(d => ({
      id: d.id.slice(2), x: parseFloat(d.style.left), y: parseFloat(d.style.top),
      w: parseFloat(d.style.width), h: parseFloat(d.style.height),
    }));
    const bad = [];
    document.querySelectorAll("path.edge.loop:not(.off)").forEach(path => {
      const len = path.getTotalLength();
      if (!Number.isFinite(len)) { bad.push(`${path.dataset.a}>${path.dataset.b}:nonfinite`); return; }
      for (const box of boxes) {
        if (box.id === path.dataset.a || box.id === path.dataset.b) continue;
        let crossed = false;
        for (let distance = 0; distance <= len; distance += 2) {
          const point = path.getPointAtLength(distance);
          if (point.x > box.x && point.x < box.x + box.w && point.y > box.y && point.y < box.y + box.h) { crossed = true; break; }
        }
        if (crossed) bad.push(`${path.dataset.a}>${path.dataset.b}/${box.id}`);
      }
    });
    return bad;
  });
  check("structural", `${tag} no loop-back path passes through a visible node`, crossedLoops.length === 0, crossedLoops.join(","));

  const gateways = geo.nodes.filter(n => R.nodes.get(n.id)?.kind === "gateway");
  if (gateways.length) {
    const missingPolygons = await page.evaluate(ids => ids.filter(id => !document.getElementById("n_" + id)?.querySelector("svg.gw polygon")), gateways.map(g => g.id));
    check("structural", `${tag} every visible gateway has a polygon`, missingPolygons.length === 0, missingPolygons.join(","));
    const missingExitLabels = await page.evaluate(exits => exits.filter(({ i, label }) => {
      const el = document.querySelector(`.elabel[data-i="${i}"]:not(.off)`);
      return !label || !el || el.textContent !== label;
    }).map(({ id }) => id), model.links.map((l, i) => ({ ...l, i })).filter(l => gateways.some(g => g.id === l.from) && R.lv(l)));
    check("structural", `${tag} every visible gateway exit has a label`, missingExitLabels.length === 0, missingExitLabels.join(","));
  }

  const spill = await page.evaluate(() => {
    const bad = [];
    document.querySelectorAll(".node:not(.off):not(.wide)").forEach(d => {
      const r = d.getBoundingClientRect();
      for (const sel of [".name", ".s"]) {
        const c = d.querySelector(sel);
        if (c) { const cr = c.getBoundingClientRect(); if (cr.bottom > r.bottom + 1 || cr.right > r.right + 1) { bad.push(d.id.slice(2)); break; } }
      }
    });
    return bad;
  });
  check("structural", `${tag} no text spills out of a card`, spill.length === 0, spill.join(","));
  const metricProbe = await page.evaluate(() => {
    const visible = [...document.querySelectorAll(".node:not(.off)")];
    const badges = visible.flatMap(n => [...n.querySelectorAll(".metric-badge")]);
    return {
      badges: badges.length,
      sparks: visible.reduce((count, n) => count + n.querySelectorAll(".spark").length, 0),
      overlap: badges.some(b => {
        const name = b.closest(".node")?.querySelector(".name");
        if (!name) return false;
        const a = name.getBoundingClientRect(), c = b.getBoundingClientRect();
        return a.left < c.right - 1 && c.left < a.right - 1 && a.top < c.bottom - 1 && c.top < a.bottom - 1;
      }),
    };
  });
  const visibleNodes = geo.nodes.map(n => R.nodes.get(n.id)).filter(Boolean);
  const metricCount = visibleNodes.filter(n => n.metrics).length;
  check("structural", `${tag} metric badges show without title overlap`, metricProbe.badges === metricCount && !metricProbe.overlap);
  check("structural", `${tag} metric series show a sparkline`, metricProbe.sparks === visibleNodes.filter(n => (n.metrics?.series?.length ?? 0) >= 2).length);

  const visibleGroups = geo.nodes.length;
  const st0 = await page.evaluate(inPage.state);
  if (w === 1600) check("structural", `${tag} first view is readable (zoom at least 0.6 for up to 60 groups)`, visibleGroups > 60 || st0.view.k >= 0.6, `groups=${visibleGroups} k=${st0.view.k.toFixed(2)}`);
  const inside = await page.evaluate(() => {
    const v = document.getElementById("viewport").getBoundingClientRect(); window.FlowStudio.fit(false);
    return new Promise(res => setTimeout(() => {
      let n = 0;
      document.querySelectorAll(".node:not(.off)").forEach(d => { const r = d.getBoundingClientRect(); if (r.left < v.left - 2 || r.right > v.right + 2 || r.top < v.top - 2 || r.bottom > v.bottom + 2) n++; });
      res(n);
    }, 120));
  });
  check("structural", `${tag} fit shows every node`, inside === 0, `outside=${inside}`);

  // ---------- accessibility (static)
  const names = await page.evaluate(() => {
    const bad = [];
    document.querySelectorAll("button, [role=button], input, [role=application]").forEach(e => {
      const name = e.getAttribute("aria-label") || e.textContent?.trim() || e.getAttribute("title") || e.getAttribute("placeholder");
      if (!name) bad.push(e.id || e.className || e.tagName);
    });
    return bad;
  });
  check("a11y", `${tag} every control has an accessible name`, names.length === 0, names.slice(0, 5).join(","));
  const tabs = await page.evaluate(() => ({
    visibleFocusable: [...document.querySelectorAll(".node:not(.off)")].every(d => d.tabIndex === 0),
    hiddenFocusable: [...document.querySelectorAll(".node.off")].some(d => d.tabIndex !== -1),
  }));
  check("a11y", `${tag} visible nodes are focusable, hidden ones are not`, tabs.visibleFocusable && !tabs.hiddenFocusable);
  const tableRows = await page.evaluate(() => document.querySelectorAll("#tbl tbody tr").length);
  const expectRows = model.nodes.filter(n => R.nv(n) && n.kind !== "chip").length;
  check("a11y", `${tag} table view lists exactly the visible groups`, tableRows === expectRows, `rows=${tableRows} expected=${expectRows}`);

  const fold = model.nodes.find(n => n.kind === "group" && n.contains?.length);
  if (fold) {
    const count = () => page.evaluate(() => document.querySelectorAll(".node:not(.off)").length);
    const touchErrors = () => page.evaluate(() => {
      const g = window.FlowStudio.geometry(), bad = [];
      document.querySelectorAll("path.edge:not(.off)").forEach(p => {
        const a = g.nodes[p.dataset.a], b = g.nodes[p.dataset.b], len = p.getTotalLength();
        const s = p.getPointAtLength(0), e = p.getPointAtLength(len), loop = p.classList.contains("loop");
        const okA = loop ? a && Math.abs(s.x - a.x - a.w / 2) <= 2 && Math.abs(s.y - a.y - a.h) <= 2
          : a && Math.abs(s.x - a.x - a.w) <= 2 && s.y >= a.y - 2 && s.y <= a.y + a.h + 2;
        const okB = loop ? b && Math.abs(e.x - b.x - b.w / 2) <= 2 && Math.abs(e.y - b.y - b.h) <= 2
          : b && Math.abs(e.x - b.x + 1) <= 2 && e.y >= b.y - 2 && e.y <= b.y + b.h + 2;
        if (!okA || !okB) bad.push(p.dataset.a + ">" + p.dataset.b);
      });
      return bad;
    });
    const initial = await count();
    if (R.collapsed.has(fold.id)) {
      await page.evaluate(id => window.FlowStudio.select(id), fold.id);
      await page.locator('#inspector [data-toggle-group]').click();
      check("interaction", `${tag} expanding a group changes visible nodes by contained minus one`, (await count()) - initial === fold.contains.length - 1);
      check("structural", `${tag} expanded links touch their node boxes`, (await touchErrors()).length === 0);
      await page.locator('#inspector [data-toggle-group]').click();
      check("interaction", `${tag} collapsing restores visible nodes`, (await count()) === initial);
      check("structural", `${tag} collapsed links touch their node boxes`, (await touchErrors()).length === 0);
    } else {
      await page.evaluate(id => window.FlowStudio.select(id), fold.contains[0]);
      await page.locator('#inspector [data-toggle-group]').click();
      check("interaction", `${tag} collapsing a group changes visible nodes by contained minus one`, initial - (await count()) === fold.contains.length - 1);
      check("structural", `${tag} collapsed links touch their node boxes`, (await touchErrors()).length === 0);
      await page.locator('#inspector [data-toggle-group]').click();
      check("interaction", `${tag} expanding restores visible nodes`, (await count()) === initial);
      check("structural", `${tag} expanded links touch their node boxes`, (await touchErrors()).length === 0);
    }
    await page.keyboard.press("Escape");
  }

  if (w !== 1600) { await ctx.close(); continue; }

  // ---------- interaction (1600x900 only)
  const vp = await page.locator("#viewport").boundingBox();
  const cx = vp.x + 700, cy = vp.y + 400;
  const wp = () => page.evaluate(([x, y]) => { const r = document.getElementById("viewport").getBoundingClientRect(), v = window.FlowStudio.view(); return { wx: (x - r.left - v.x) / v.k, wy: (y - r.top - v.y) / v.k, k: v.k }; }, [cx, cy]);
  const before = await wp();
  await page.mouse.move(cx, cy); await page.mouse.wheel(0, -400); await page.waitForTimeout(120);
  const after = await wp();
  check("interaction", "wheel zooms in", after.k > before.k, `${before.k.toFixed(2)} -> ${after.k.toFixed(2)}`);
  check("interaction", "the point under the cursor stays fixed (within 1 px)", Math.abs(after.wx - before.wx) < 1 && Math.abs(after.wy - before.wy) < 1);
  for (let i = 0; i < 40; i++) await page.mouse.wheel(0, -600);
  await page.waitForTimeout(100);
  check("interaction", "zoom clamps at 2.5", (await page.evaluate(inPage.state)).view.k <= 2.5 + 1e-9);
  for (let i = 0; i < 80; i++) await page.mouse.wheel(0, 600);
  await page.waitForTimeout(100);
  check("interaction", "zoom clamps at 0.25", (await page.evaluate(inPage.state)).view.k >= 0.25 - 1e-9);
  await page.screenshot({ path: join(outDir, "02-min-zoom.png") });
  await page.locator("#viewport").focus(); await page.keyboard.press("0"); await page.waitForTimeout(450);
  const fit0 = (await page.evaluate(inPage.state)).view;
  check("interaction", "0 fits everything", fit0.k > 0 && fit0.k <= 1, `k=${fit0.k.toFixed(2)}`);
  // the gap tile counts groups (not their member weights), as its label says
  const gapTile = await page.evaluate(() => Number(document.querySelector("#kpis button.tile.warn .tn")?.textContent));
  const gapExpected = model.nodes.filter(n => R.nv(n) && n.kind !== "chip" && model.states[n.stateIn?.[R.view] ?? n.state]?.bucket === "gap").length;
  check("interaction", "the gap tile counts groups", gapTile === gapExpected, `tile=${gapTile} expected=${gapExpected}`);
  // browser shortcuts are left alone
  const kBefore = (await page.evaluate(inPage.state)).view;
  await page.keyboard.press("Control+Minus"); await page.keyboard.press("Control+0"); await page.waitForTimeout(450);
  const kAfter = (await page.evaluate(inPage.state)).view;
  check("interaction", "Ctrl+key combinations do not move the canvas", kBefore.k === kAfter.k && kBefore.x === kAfter.x);
  await page.keyboard.press("1"); await page.waitForTimeout(450);
  const p0 = (await page.evaluate(inPage.state)).view;
  const dragStart = await page.evaluate(() => {
    const viewport = document.getElementById("viewport");
    const r = viewport.getBoundingClientRect();
    for (const fy of [0.85, 0.7, 0.55, 0.4, 0.25, 0.1]) for (const fx of [0.85, 0.7, 0.55, 0.4, 0.25, 0.1]) {
      const x = r.left + r.width * fx, y = r.top + r.height * fy;
      const el = document.elementFromPoint(x, y);
      if (el && viewport.contains(el) && !el.closest(".node, .bandlabel, .elabel, #tools, #zoomLabel")) return { x, y };
    }
    return null;
  });
  check("interaction", "an empty canvas point is available for background drag", !!dragStart);
  const start = dragStart ?? { x: vp.x + vp.width / 2, y: vp.y + vp.height / 2 };
  const dx = start.x > vp.x + vp.width / 2 ? -200 : 200;
  const dy = start.y > vp.y + vp.height / 2 ? -80 : 80;
  await page.mouse.move(start.x, start.y); await page.mouse.down(); await page.mouse.move(start.x + dx, start.y + dy, { steps: 6 }); await page.mouse.up();
  const p1 = (await page.evaluate(inPage.state)).view;
  check("interaction", "dragging the background pans", Math.abs(p1.x - p0.x) > 100, `${p0.x.toFixed(0)} -> ${p1.x.toFixed(0)}`);
  await page.keyboard.press("0"); await page.waitForTimeout(450);

  // choose a card with the most links
  const deg = new Map();
  for (const l of model.links) if (R.lv(l)) { deg.set(R.canon(R.endpoint(l.from)), (deg.get(R.canon(R.endpoint(l.from))) ?? 0) + 1); deg.set(R.canon(R.endpoint(l.to)), (deg.get(R.canon(R.endpoint(l.to))) ?? 0) + 1); }
  const pick = [...deg.entries()].filter(([id]) => R.nv(R.nodes.get(id)) && R.nodes.get(id)?.kind !== "chip" && !((R.nodes.get(id)?.colSpan ?? 1) > 1)).sort((a, b) => b[1] - a[1])[0]?.[0];
  check("interaction", "the model has a selectable card with links", !!pick, pick ?? "none");
  if (pick) {
    await page.keyboard.press("h");
    const nb = await page.locator(`[id="n_${pick}"]`).boundingBox();
    const h0 = (await page.evaluate(inPage.state)).view;
    await page.mouse.move(nb.x + 20, nb.y + 20); await page.mouse.down(); await page.mouse.move(nb.x + 80, nb.y + 60, { steps: 5 }); await page.mouse.up();
    const h1 = (await page.evaluate(inPage.state)).view;
    check("interaction", "the hand tool pans from a node and does not select", Math.abs(h1.x - h0.x) > 20 && (await page.evaluate(inPage.state)).selected === null);
    await page.keyboard.press("v"); await page.keyboard.press("0"); await page.waitForTimeout(450);

    await page.locator("#viewport").focus(); const a0 = (await page.evaluate(inPage.state)).view; await page.keyboard.press("ArrowLeft");
    check("interaction", "an arrow key pans", (await page.evaluate(inPage.state)).view.x !== a0.x);
    await page.click("#tools [data-id='plus']"); await page.waitForTimeout(400); const z1 = (await page.evaluate(inPage.state)).view.k;
    await page.click("#tools [data-id='minus']"); await page.waitForTimeout(400); const z2 = (await page.evaluate(inPage.state)).view.k;
    check("interaction", "the zoom buttons work", z1 > z2, `${z1.toFixed(2)} ${z2.toFixed(2)}`);

    check("interaction", "the inspector is closed before a click", await page.evaluate(() => !document.getElementById("inspector").classList.contains("open")));
    await page.click(`[id="n_${pick}"]`);
    check("interaction", "a click selects the card and opens the inspector", await page.evaluate(id => window.FlowStudio.selected() === id && document.getElementById("inspector").classList.contains("open"), pick));
    check("interaction", "the draw-in trail runs on select", await page.evaluate(() => document.querySelectorAll("path.trail").length > 0 || matchMedia("(prefers-reduced-motion: reduce)").matches));
    await page.waitForTimeout(300);
    await page.screenshot({ path: join(outDir, "03-selected.png") });
    check("interaction", "the inspector has three relation buttons", (await page.locator("#inspector .counts .cbtn").count()) === 3);
    await page.click("#inspector [data-hl='down']");
    check("interaction", "a relation button highlights a set", await page.evaluate(() => document.querySelectorAll(".node.dim").length > 0));

    const act = model.inspector?.actions?.[0];
    if (act) {
      await page.click(`#inspector [data-act="${act.id}"]`); await page.waitForTimeout(1700);
      const expected = [...R.down(pick)].filter(id => id !== R.canon(pick) && R.nodes.get(id)).length;
      const failed = await page.evaluate(() => document.querySelectorAll(".node.fail").length);
      check("interaction", "the what-if action marks exactly the downstream set", failed === expected, `marked=${failed} expected=${expected}`);
      await page.screenshot({ path: join(outDir, "04-simulate.png") });
      await page.click("#simReset"); await page.waitForTimeout(200);
      check("interaction", "reset clears the what-if", await page.evaluate(() => document.querySelectorAll(".node.fail, path.ripple").length === 0));
    }
    await page.keyboard.press("Escape"); await page.waitForTimeout(400);
    check("interaction", "Escape clears the selection and closes the inspector", await page.evaluate(() => window.FlowStudio.selected() === null && !document.getElementById("inspector").classList.contains("open")));
  }

  // chip selects the real node
  const chip = model.nodes.find(n => n.kind === "chip" && R.nv(n));
  if (chip) {
    await page.click(`[id="n_${chip.id}"]`);
    check("interaction", "a portal chip selects the real node", await page.evaluate(id => window.FlowStudio.selected() === id, chip.ref));
    await page.keyboard.press("Escape");
  }

  // search
  const probe = model.nodes.find(n => R.nv(n) && (n.members?.some(Boolean) || n.title));
  if (probe) {
    const term = (probe.members?.find(Boolean) ?? probe.title).slice(0, 6).toLowerCase();
    await page.fill("#q", term); await page.waitForTimeout(250);
    check("interaction", "search dims the groups that do not match", await page.evaluate(() => document.querySelectorAll(".node.dim").length > 0));
    const dim0 = await page.evaluate(() => document.querySelectorAll(".node:not(.off).dim").length);
    const matched = new Set(model.nodes.filter(n => R.nv(n) && (n.title.toLowerCase().includes(term) || (n.members ?? []).some(m => m.toLowerCase().includes(term)))).map(n => n.id));
    const hasNeighbours = model.links.some(l => R.lv(l) && (matched.has(R.endpoint(l.from)) !== matched.has(R.endpoint(l.to))));
    await page.selectOption("#hops", "1"); await page.waitForTimeout(100);
    const dim1 = await page.evaluate(() => document.querySelectorAll(".node:not(.off).dim").length);
    check("interaction", "search radius +1 lights neighbouring groups", dim1 < dim0 || (dim1 === dim0 && !hasNeighbours), `hops0=${dim0} hops1=${dim1} neighbours=${hasNeighbours}`);
    await page.selectOption("#hops", "0");
    await page.fill("#q", ""); await page.keyboard.press("Escape");
  }

  // view switch
  if ((model.views ?? []).length > 1) {
    const other = model.views.find(v => v.id !== R.view);
    await page.click(`#modeSwitch [data-mode="${other.id}"]`); await page.waitForTimeout(900);
    const off = await page.evaluate(() => document.querySelectorAll(".node.off").length);
    const expectOff = model.nodes.filter(n => !R.nv(n, other.id)).length;
    check("interaction", "the view switch hides exactly the nodes that are not in that view", off === expectOff, `off=${off} expected=${expectOff}`);
    await page.screenshot({ path: join(outDir, "05-other-view.png") });
    await page.click(`#modeSwitch [data-mode="${R.view}"]`); await page.waitForTimeout(600);
  }

  // notes
  if (!skip.has("notes")) {
    await page.keyboard.press("n"); await page.waitForTimeout(500);
    const markers = await page.locator(".marker").count();
    check("interaction", "notes mode shows numbered markers", (model.notes?.length ?? 0) === 0 || markers > 0, `markers=${markers}`);
    const flowNotes = await page.evaluate(() => {
      try { return JSON.parse(document.getElementById("flow-notes")?.textContent || "[]"); }
      catch { return []; }
    });
    const isDemoPack = Array.isArray(flowNotes) && flowNotes.some(n => n.title === "Page frame" && n.anchor === "#title");
    if (isDemoPack) {
      // Per note, not by total: a note whose anchor resolves to a visible element must have a
      // marker; one whose anchor matches nothing (or is hidden) legitimately has none. This mirrors
      // the placement rules in src/notes.ts.
      const markerless = await page.evaluate(notes => {
        const have = new Set([...document.querySelectorAll(".marker")].map(m => m.dataset.n));
        return notes.filter(n => {
          let a = null; try { a = document.querySelector(n.anchor); } catch { return false; }
          if (!a) return false;
          let r = a.getBoundingClientRect();
          if (!r.width && !r.height) {
            let d = a.closest("details");
            while (d && d.open) d = d.parentElement?.closest("details") ?? null;
            if (d) r = d.getBoundingClientRect();
          }
          if (!r.width && !r.height) return false;
          if (a.closest("#world")) {
            const v = document.getElementById("viewport").getBoundingClientRect();
            if (r.right < v.left || r.left > v.right || r.bottom < v.top || r.top > v.bottom) return false;
          }
          return !have.has(String(n.id));
        }).map(n => n.id);
      }, flowNotes);
      check("interaction", "demo pack notes mode shows a marker for each anchored note", markerless.length === 0, `missing=${markerless.join(",")}`);
    }
    await page.screenshot({ path: join(outDir, "06-notes.png") });
    await page.keyboard.press("n");
  }

  // ---------- accessibility (dynamic)
  await page.locator("#viewport").focus();
  let trap = true;
  for (let i = 0; i < model.nodes.length + 60; i++) { await page.keyboard.press("Tab"); const inCanvas = await page.evaluate(() => !!document.activeElement?.closest("#viewport, #inspector")); if (!inCanvas) { trap = false; break; } }
  check("a11y", "no keyboard trap: Tab leaves the canvas", !trap);
  await page.evaluate(() => { const n = document.querySelector(".node:not(.off)"); n.focus(); });
  await page.keyboard.press("Tab"); await page.keyboard.press("Shift+Tab");
  const focusVisible = await page.evaluate(() => { const d = document.activeElement; if (!d) return false; const s = getComputedStyle(d); return (s.outlineStyle !== "none" && parseFloat(s.outlineWidth) > 0) || s.boxShadow !== "none"; });
  check("a11y", "focus is visible on a node", focusVisible);

  // contrast, light and dark
  const contrast = async scheme => {
    await page.emulateMedia({ colorScheme: scheme }); await page.waitForTimeout(250);
    return page.evaluate(() => {
      const parse = c => {
        let m = c.match(/rgba?\(([^)]+)\)/);
        if (m) { const p = m[1].split(/[ ,\/]+/).map(Number); return { r: p[0], g: p[1], b: p[2], a: p[3] ?? 1 }; }
        m = c.match(/color\(srgb ([^)]+)\)/);
        if (m) { const p = m[1].split(/[ \/]+/).map(Number); return { r: p[0] * 255, g: p[1] * 255, b: p[2] * 255, a: p[3] ?? 1 }; }
        return null;
      };
      const lum = ({ r, g, b }) => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
      const bgOf = el => { let e = el; while (e) { const c = parse(getComputedStyle(e).backgroundColor); if (c && c.a > 0.5) return c; e = e.parentElement; } return { r: 255, g: 255, b: 255, a: 1 }; };
      const worst = []; let min = 99;
      document.querySelectorAll(".node:not(.off):not(.dim) .name, .node:not(.off):not(.dim) .s").forEach(t => {
        const fg = parse(getComputedStyle(t).color), bg = bgOf(t); if (!fg) return;
        const a = lum(fg), b = lum(bg), r = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
        if (r < min) min = r; if (r < 4.5) worst.push(t.textContent.slice(0, 24) + " " + r.toFixed(2));
      });
      return { min, worst: worst.slice(0, 4) };
    });
  };
  const cl = await contrast("light"), cd = await contrast("dark");
  check("a11y", "text contrast is at least 4.5 in the light theme", cl.min >= 4.5, `min=${cl.min.toFixed(2)} ${cl.worst.join(" | ")}`);
  check("a11y", "text contrast is at least 4.5 in the dark theme", cd.min >= 4.5, `min=${cd.min.toFixed(2)} ${cd.worst.join(" | ")}`);
  await page.emulateMedia({ colorScheme: "dark" }); await page.waitForTimeout(200);
  await page.screenshot({ path: join(outDir, "07-dark.png") });
  if (!skip.has("playback") && model.scenarios?.length) {
    const playback = await page.evaluate(async () => {
      const f = window.FlowStudio;
      f.play(f.model.scenarios[0].id);
      await new Promise(r => setTimeout(r, 80));
      const first = document.querySelector("#token").getAttribute("cx");
      const link = document.querySelector("path.edge.playing")?.dataset.i;
      await new Promise(r => setTimeout(r, 160));
      const second = document.querySelector("#token").getAttribute("cx");
      f.pause(); document.querySelector("#pbReset").click(); f.step(); const a = document.querySelector("path.edge.playing")?.dataset.i;
      f.step(); const b = document.querySelector("path.edge.playing")?.dataset.i;
      const branches = document.querySelectorAll("#pbChoices button").length;
      const suggested = document.querySelectorAll("#pbChoices .suggested").length;
      document.querySelector("#pbScrub").value = "1000";
      document.querySelector("#pbScrub").dispatchEvent(new Event("input", { bubbles: true }));
      const scrub = f.playback().step, scrubLink = document.querySelector("path.edge.playing")?.dataset.i;
      return { moved: first !== second && getComputedStyle(document.querySelector("#token")).display !== "none", link, a, b, scrub, scrubLink, branches, suggested };
    });
    const s0 = model.scenarios[0];
    const expectedLink0 = String(model.links.findIndex(l => l.id === s0.steps[0]?.link));
    check("interaction", "Play moves the token along the current link", playback.moved && playback.link === expectedLink0);
    // A scenario may legally have a single step; comparing a second link needs two of them.
    if ((s0.steps?.length ?? 0) >= 2) {
      const expectedLink1 = String(model.links.findIndex(l => l.id === s0.steps[1]?.link));
      check("interaction", "Step follows scenario link order", playback.a === expectedLink0 && playback.b === expectedLink1);
    }
    check("interaction", "scrubber lands on the final scenario link", playback.scrub === s0.steps.length - 1 && playback.scrubLink === String(model.links.findIndex(l => l.id === s0.steps.at(-1)?.link)));
    const step1Link = model.links.find(l => l.id === s0.steps[1]?.link);
    const hasBranchAtStep2 = step1Link && model.links.filter(l => l.from === step1Link.to).length > 1;
    if (hasBranchAtStep2)
      check("interaction", "branch buttons show at a gateway in step mode", playback.branches > 1 && playback.suggested === 1);
    const sla = await page.evaluate(() => {
      const f = window.FlowStudio;
      const scenarios = f.model.scenarios ?? [];
      // Prefer the canonical "escalated", else the first scenario whose elapsed time passes the SLA
      // of a node it lands on. A model without any breach simply skips this check.
      const breaches = s => (s?.steps ?? []).some(st => {
        const link = f.model.links.find(l => l.id === st?.link);
        if (!link) return false;
        const target = f.model.nodes.find(n => n.id === link.to);
        const slaOf = f.model.nodes.find(n => n.id === (target?.ref ?? link.to))?.sla;
        return slaOf !== undefined && (st.at ?? 0) >= slaOf;
      });
      const scenario = scenarios.find(s => s.id === "escalated" && breaches(s)) ?? scenarios.find(breaches);
      if (!scenario) return { found: false, breached: false };
      f.play(scenario.id); f.pause();
      for (let i = 0; i < scenario.steps.length; i++) {
        f.step();
        if (document.querySelector("#pbCounter")?.classList.contains("breach")) {
          return { found: true, breached: true };
        }
      }
      return { found: true, breached: document.querySelector("#pbCounter")?.classList.contains("breach") ?? false };
    });
    // A model whose SLAs no scenario crosses is valid: the check is skipped. It fails only when a scenario does cross an SLA and the counter never reaches breach.
    if (sla.found) check("interaction", "an SLA-breaching scenario reaches breach", sla.breached, sla.breached ? "" : "did not reach breach");
    if (hasBranchAtStep2) {
      const pausedChoices = await page.evaluate(() => {
        const f = window.FlowStudio;
        const visible = sel => [...document.querySelectorAll(sel)].filter(b => b.offsetParent !== null).length;
        f.play(f.model.scenarios[0].id); f.pause();
        f.step();
        // Park the token just inside this step, so play() resumes it instead of rewinding at the plan's end.
        f.seek(f.playback().t - 1);
        // Play clears the branch buttons; pausing on this step must bring them back.
        f.play(); f.pause();
        return { step: f.playback().step, branches: visible("#pbChoices button"), suggested: visible("#pbChoices .suggested") };
      });
      check("interaction", "pausing at a gateway keeps the branch buttons", pausedChoices.branches > 1 && pausedChoices.suggested === 1, `step=${pausedChoices.step} branches=${pausedChoices.branches} suggested=${pausedChoices.suggested}`);
      const finishedChoices = await page.evaluate(async () => {
        const f = window.FlowStudio;
        const visible = sel => [...document.querySelectorAll(sel)].filter(b => b.offsetParent !== null).length;
        const btn = document.querySelector("#pbChoices button[data-link]");
        if (!(btn instanceof HTMLButtonElement)) return { finished: false, branches: 0 };
        btn.click();
        await new Promise(res => { const t0 = performance.now(); const iv = setInterval(() => { if (!f.playback().playing || performance.now() - t0 > 5000) { clearInterval(iv); res(); } }, 50); });
        const finished = !f.playback().playing, branches = visible("#pbChoices button");
        // Leave playback in a state a live update can restore exactly (a manual route lives only in the player).
        document.querySelector("#pbReset").click();
        return { finished, branches };
      });
      check("interaction", "playback that stops on its own shows the branch buttons", finishedChoices.finished && finishedChoices.branches > 1, finishedChoices.finished ? `branches=${finishedChoices.branches}` : "did not finish");
    }
  }

  if (!skip.has("update")) {
  const updateProbe = await page.evaluate(() => {
    const f = window.FlowStudio;
    const m = structuredClone(f.model), first = m.nodes.find(n => !["group", "chip", "gateway"].includes(n.kind)) ?? m.nodes[0], changed = first;
    f.pause(); f.select(changed.id);
    const qInput = document.querySelector("#q");
    if (qInput) {
      qInput.value = "verify";
      qInput.dispatchEvent(new Event("input", { bubbles: true }));
    }
    const before = { view: f.view(), selected: f.selected(), mode: f.mode(), playback: f.playback(), search: document.querySelector("#q")?.value ?? "" };
    changed.state = Object.keys(m.states).find(s => s !== changed.state) ?? changed.state;
    changed.title += " updated";
    const newId = "check-added-node";
    const newNode = { ...structuredClone(first), id: newId, title: "Added node", contains: undefined, ref: undefined, metrics: undefined };
    if (m.layout === "auto") { delete newNode.col; delete newNode.row; }
    if (m.layout === "columns-lanes") newNode.row = Math.max(...m.nodes.filter(n => n.col === first.col).map(n => n.row ?? 0)) + 2;
    if (m.layout === "free") newNode.x = Math.max(...m.nodes.map(n => (n.x ?? 0) + (n.w ?? 190))) + 50;
    m.nodes.push(newNode);
    m.links.push({ id: "check-added-link", from: first.id, to: newId, state: first.state });
    const good = f.update(m);
    const after = { view: f.view(), selected: f.selected(), mode: f.mode(), playback: f.playback(), search: document.querySelector("#q")?.value ?? "" };
    const updated = document.getElementById("n_" + changed.id)?.classList.contains("updated");
    const added = !!document.getElementById("n_" + newId);
    const nodeCount = document.querySelectorAll(".node").length;
    const edgeCount = document.querySelectorAll("path.edge").length;
    const invalid = structuredClone(m); invalid.links.push({ id: "bad", from: "missing", to: newId, state: first.state });
    const bad = f.update(invalid);
    const unchanged = document.querySelectorAll(".node").length === nodeCount && document.querySelectorAll("path.edge").length === edgeCount;
    const banner = !document.getElementById("banner").hidden;
    const recover = f.update(m);
    return { good: good.ok, bad: !bad.ok, recover: recover.ok, before, after, updated, added, unchanged, banner, hidden: document.getElementById("banner").hidden };
  });
  const stateKept = isDeepStrictEqual(updateProbe.before, updateProbe.after);
  check("interaction", "update keeps view, selection, search and playback", updateProbe.good && stateKept, stateKept ? "" : `before=${JSON.stringify(updateProbe.before)} after=${JSON.stringify(updateProbe.after)}`);
  check("interaction", "update marks changed and added nodes", updateProbe.updated && updateProbe.added);
  check("interaction", "invalid update keeps the DOM and shows a banner", updateProbe.bad && updateProbe.unchanged && updateProbe.banner);
  check("interaction", "valid update clears the failure banner", updateProbe.recover && updateProbe.hidden);
  }
  await ctx.close();
}

// ---------- reduced motion
{
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 900 }, reducedMotion: "reduce" });
  const page = await ctx.newPage();
  await page.goto(targetUrl); await page.waitForFunction(() => !!window.FlowStudio); await page.waitForTimeout(600);
  const moving = await page.evaluate(() => {
    let n = 0;
    document.querySelectorAll("#viewport *, .tile, .lcell").forEach(e => { const s = getComputedStyle(e); if (s.animationName !== "none" && s.animationDuration !== "0s") n++; if (s.transitionDuration.split(",").some(d => parseFloat(d) > 0)) n++; });
    return n;
  });
  check("a11y", "reduced motion removes every animation and transition", moving === 0, `moving=${moving}`);
  const reducedToken = await page.evaluate(() => {
    const token = document.getElementById("token");
    return !token || getComputedStyle(token).transitionDuration.split(",").every(d => parseFloat(d) === 0);
  });
  check("a11y", "reduced motion gives the token no transition", reducedToken);
  await ctx.close();
}

// ---------- hostile text
if (hostilePath && !skip.has("hostile")) {
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 900 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", e => errors.push(String(e)));
  await page.goto(url(hostilePath)); await page.waitForFunction(() => !!window.FlowStudio); await page.waitForTimeout(600);
  const probe = await page.evaluate(() => ({
    pwned: window.__pwned,
    scripts: document.querySelectorAll("script").length,
    imgs: document.querySelectorAll("img").length,
    title: document.getElementById("title").textContent,
    nodeText: document.querySelector(".node .name")?.textContent ?? "",
  }));
  check("safety", "hostile text executes nothing", probe.pwned === undefined && errors.length === 0, errors.join("|"));
  check("safety", "hostile text adds no script or image element", probe.scripts === 3 && probe.imgs === 0, `scripts=${probe.scripts} imgs=${probe.imgs}`);
  check("safety", "hostile text is shown as text", probe.title.includes("</script>") && probe.nodeText.length > 0);
  await page.click(".node:not(.off)"); await page.waitForTimeout(300);
  check("safety", "hostile text stays inert in the inspector", await page.evaluate(() => window.__pwned === undefined && document.querySelectorAll("#inspector img").length === 0));
  await ctx.close();
}

// ---------- performance
if (!flag("--skip-perf")) {
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 900 } });
  const page = await ctx.newPage();
  await page.goto(targetUrl); await page.waitForFunction(() => !!window.FlowStudio); await page.waitForTimeout(400);
  const perf = await page.evaluate(() => {
    const base = window.FlowStudio.model;
    const cols = base.columns, lanes = [], nodes = [], links = [];
    const N = 200, perLane = 36;
    for (let i = 0; i < N; i++) {
      const col = i % cols.length, row = Math.floor(i / cols.length) * 1.2, lane = "p" + Math.floor(i / perLane);
      if (!lanes.find(l => l.id === lane)) lanes.push({ id: lane, title: "Lane " + lane });
      nodes.push({ id: "p" + i, kind: "card", lane, col, row, state: Object.keys(base.states)[0], title: "Node " + i, subtitle: "perf" });
      if (i >= cols.length) links.push({ id: "pl" + i, from: "p" + (i - cols.length + 1 > 0 ? i - 1 : i), to: "p" + i, state: Object.keys(base.states)[0] });
    }
    const model = { ...base, lanes, nodes: nodes.map(n => ({ ...n, lane: lanes[Math.min(lanes.length - 1, Math.floor(n.row / 7))].id })), links: [], views: undefined, notes: [], inspector: undefined };
    // links go forward in columns only
    for (let i = 0; i < nodes.length - 1; i++) if (nodes[i].col + 1 === nodes[i + 1].col) model.links.push({ id: "pl" + i, from: nodes[i].id, to: nodes[i + 1].id, state: nodes[i].state });
    model.lanes = lanes;
    window.FlowStudio.destroy();
    for (const id of ["cols", "layerstrip"]) document.getElementById(id).innerHTML = "";
    const t0 = performance.now();
    const api = window.flowStudioMount(document, model, { notes: [] });
    const first = performance.now() - t0;
    const times = [];
    const vp = document.getElementById("viewport");
    for (let i = 0; i < 50; i++) { const t = performance.now(); vp.dispatchEvent(new WheelEvent("wheel", { deltaY: i % 2 ? 120 : -120, clientX: 600, clientY: 400, bubbles: true, cancelable: true })); times.push(performance.now() - t); }
    times.sort((a, b) => a - b);
    return { nodes: nodes.length, first, p95: times[Math.floor(times.length * 0.95)], ok: !!api };
  });
  check("performance", `first render of ${perf.nodes} nodes under 500 ms`, perf.first < 500, `${perf.first.toFixed(0)} ms`);
  check("performance", "one wheel event under 16 ms at the 95th percentile", perf.p95 < 16, `${perf.p95.toFixed(1)} ms`);
  await ctx.close();
}

await browser.close();
const failed = results.filter(r => !r.ok);
console.log(`\n${results.length - failed.length} passed, ${failed.length} failed`);
if (opt("--json")) writeFileSync(resolve(opt("--json")), JSON.stringify(results, null, 2));
process.exit(failed.length ? 1 : 0);
