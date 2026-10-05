// Playwright check harness for a flow-studio page. Model-agnostic: it reads the model from the page.
//   node scripts/check.mjs <page.html> [--out dir] [--viewports 1600x900,1280x720,820x900]
//        [--channel msedge] [--hostile hostile.html] [--json report.json] [--skip-perf]
// Run it from a folder that can resolve "playwright" (the project's node_modules). Exit 0: every check passed.

import { createRequire } from "node:module";
import { mkdirSync, writeFileSync } from "node:fs";
import { resolve, join } from "node:path";
import { pathToFileURL } from "node:url";

const argv = process.argv.slice(2);
const opt = (name, dflt) => { const i = argv.indexOf(name); return i >= 0 ? argv[i + 1] : dflt; };
const flag = name => argv.includes(name);
const pageArg = argv[0];
if (!pageArg || pageArg.startsWith("--")) { console.error("usage: node scripts/check.mjs <page.html> [--out dir] [--viewports WxH,...] [--channel msedge] [--hostile page.html] [--json file] [--skip-perf]"); process.exit(2); }
const pagePath = resolve(pageArg ?? "");
const outDir = resolve(opt("--out", "check-out"));
const viewports = opt("--viewports", "1600x900,1280x720,820x900").split(",").map(v => v.split("x").map(Number));
const channel = opt("--channel", undefined);
const hostilePath = opt("--hostile", undefined);
mkdirSync(outDir, { recursive: true });

let chromium;
try { ({ chromium } = createRequire(join(process.cwd(), "x.js"))("playwright")); }
catch { console.error("Cannot resolve 'playwright'. Run this from a folder whose node_modules has it (npm i -D playwright)."); process.exit(2); }

const results = [];
const check = (group, name, ok, detail = "") => { results.push({ group, name, ok: !!ok, detail: String(detail) }); console.log(`${ok ? "PASS" : "FAIL"}  [${group}] ${name}${detail ? "  " + detail : ""}`); };

// ---- helpers that run in the page
const inPage = {
  state: () => {
    const f = window.FlowStudio;
    return { view: f.view(), selected: f.selected(), mode: f.mode() };
  },
};
const url = p => pathToFileURL(p).href;

// ---- model-side helpers (run here, from the model the page reports)
function modelRules(model) {
  const view = (model.views?.find(v => v.default) ?? model.views?.[0])?.id ?? "all";
  const nodes = new Map(model.nodes.map(n => [n.id, n]));
  const canon = id => nodes.get(id)?.ref ?? id;
  const nv = (n, v = view) => !n.visibleIn || n.visibleIn.includes(v);
  const lv = (l, v = view) => (!l.visibleIn || l.visibleIn.includes(v)) && nodes.get(l.from) && nodes.get(l.to) && nv(nodes.get(l.from), v) && nv(nodes.get(l.to), v);
  const down = (start, v = view) => {
    const s = new Set([canon(start)]); let grew = true;
    while (grew) { grew = false; for (const l of model.links) { if (!lv(l, v)) continue; const a = canon(l.from), b = canon(l.to); if (s.has(a) && !s.has(b)) { s.add(b); grew = true; } } }
    return s;
  };
  return { view, nodes, canon, nv, lv, down };
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
  page.on("request", r => { const u = r.url(); if (!u.startsWith("file:") && !u.startsWith("data:")) requests.push(u); });
  await page.goto(url(pagePath));
  await page.waitForFunction(() => !!window.FlowStudio, null, { timeout: 10000 });
  await page.waitForTimeout(900);
  const model = await page.evaluate(() => window.FlowStudio.model);
  const R = modelRules(model);
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
      const okA = a && Math.abs(s.x - (a.x + a.w)) <= 2 && s.y >= a.y - 2 && s.y <= a.y + a.h + 2;
      const okB = b && Math.abs(e.x - (b.x - 1)) <= 2 && e.y >= b.y - 2 && e.y <= b.y + b.h + 2;
      if (!okA || !okB) bad.push(p.dataset.a + ">" + p.dataset.b);
    });
    return bad;
  });
  check("structural", `${tag} every link end touches its node box (within 2 px)`, ends.length === 0, ends.join(","));

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
  await page.mouse.move(vp.x + 900, vp.y + 600); await page.mouse.down(); await page.mouse.move(vp.x + 700, vp.y + 520, { steps: 6 }); await page.mouse.up();
  const p1 = (await page.evaluate(inPage.state)).view;
  check("interaction", "dragging the background pans", Math.abs(p1.x - p0.x) > 100, `${p0.x.toFixed(0)} -> ${p1.x.toFixed(0)}`);
  await page.keyboard.press("0"); await page.waitForTimeout(450);

  // choose a card with the most links
  const deg = new Map();
  for (const l of model.links) if (R.lv(l)) { deg.set(R.canon(l.from), (deg.get(R.canon(l.from)) ?? 0) + 1); deg.set(R.canon(l.to), (deg.get(R.canon(l.to)) ?? 0) + 1); }
  const pick = [...deg.entries()].filter(([id]) => R.nodes.get(id)?.kind !== "chip" && !((R.nodes.get(id)?.colSpan ?? 1) > 1)).sort((a, b) => b[1] - a[1])[0]?.[0];
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
  const probe = model.nodes.find(n => n.members?.length && R.nv(n));
  if (probe) {
    const term = probe.members[0].slice(0, 6).toLowerCase();
    await page.fill("#q", term); await page.waitForTimeout(250);
    check("interaction", "search dims the groups that do not match", await page.evaluate(() => document.querySelectorAll(".node.dim").length > 0));
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
  await page.keyboard.press("n"); await page.waitForTimeout(500);
  const markers = await page.locator(".marker").count();
  check("interaction", "notes mode shows numbered markers", (model.notes?.length ?? 0) === 0 || markers > 0, `markers=${markers}`);
  await page.screenshot({ path: join(outDir, "06-notes.png") });
  await page.keyboard.press("n");

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
  await ctx.close();
}

// ---------- reduced motion
{
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 900 }, reducedMotion: "reduce" });
  const page = await ctx.newPage();
  await page.goto(url(pagePath)); await page.waitForFunction(() => !!window.FlowStudio); await page.waitForTimeout(600);
  const moving = await page.evaluate(() => {
    let n = 0;
    document.querySelectorAll("#viewport *, .tile, .lcell").forEach(e => { const s = getComputedStyle(e); if (s.animationName !== "none" && s.animationDuration !== "0s") n++; if (s.transitionDuration.split(",").some(d => parseFloat(d) > 0)) n++; });
    return n;
  });
  check("a11y", "reduced motion removes every animation and transition", moving === 0, `moving=${moving}`);
  await ctx.close();
}

// ---------- hostile text
if (hostilePath) {
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 900 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", e => errors.push(String(e)));
  await page.goto(url(resolve(hostilePath))); await page.waitForFunction(() => !!window.FlowStudio); await page.waitForTimeout(600);
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
  await page.goto(url(pagePath)); await page.waitForFunction(() => !!window.FlowStudio); await page.waitForTimeout(400);
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
