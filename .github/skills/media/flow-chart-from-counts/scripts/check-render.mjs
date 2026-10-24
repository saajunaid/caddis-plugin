// Render check for a flow chart page made with the flow-chart-from-counts skill.
//
// Opens the page headless, waits for every .fv chart to draw, and fails when a chart has no SVG,
// shows an error message, has fewer nodes than --min-nodes, or the page throws. It saves one
// screenshot per chart and one of the first chart in full screen, then prints a JSON report.
// Node overlaps and edge labels that sit on a box are reported as warnings: open the screenshots
// to judge them, because some overlaps are harmless.
//
// Usage (run from a folder whose node_modules resolves "playwright"):
//   node <skill folder>/scripts/check-render.mjs page.html --out shots [--channel msedge]
//        [--min-nodes 3] [--width 1280] [--height 900] [--timeout 30000]
//
// Exit code: 0 pass, 1 a check failed, 2 bad arguments or Playwright not found.

import { createRequire } from 'node:module';
import { existsSync, mkdirSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

function parseArgs(argv) {
  const opts = { out: 'shots', channel: '', minNodes: 3, width: 1280, height: 900, timeout: 30000 };
  const rest = [];
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    const next = () => { if (i + 1 >= argv.length) throw new Error(`${a} needs a value`); return argv[++i]; };
    if (a === '--out') opts.out = next();
    else if (a === '--channel') opts.channel = next();
    else if (a === '--min-nodes') opts.minNodes = Number(next());
    else if (a === '--width') opts.width = Number(next());
    else if (a === '--height') opts.height = Number(next());
    else if (a === '--timeout') opts.timeout = Number(next());
    else if (a.startsWith('--')) throw new Error(`unknown option ${a}`);
    else rest.push(a);
  }
  if (rest.length !== 1) throw new Error('give exactly one page path');
  opts.page = path.resolve(rest[0]);
  return opts;
}

let opts;
try { opts = parseArgs(process.argv.slice(2)); }
catch (e) { console.error(`error: ${e.message}`); process.exit(2); }

if (!existsSync(opts.page)) {
  console.error(`error: page file not found: ${opts.page}`);
  process.exit(2);
}

let chromium;
try {
  // Resolve playwright from the current folder, not from this script's folder (the skill folder has none).
  ({ chromium } = createRequire(path.join(process.cwd(), 'noop.js'))('playwright'));
} catch (e) {
  console.error('error: playwright not found from the current folder. Run this from a folder whose node_modules has playwright.');
  process.exit(2);
}

mkdirSync(opts.out, { recursive: true });
const browser = await chromium.launch(opts.channel ? { channel: opts.channel } : {});
const failures = [];
const warnings = [];
try {
  const page = await browser.newPage({ viewport: { width: opts.width, height: opts.height } });
  const pageErrors = [];
  page.on('pageerror', (e) => pageErrors.push(e.message));
  await page.goto(pathToFileURL(opts.page).href);

  const total = await page.locator('.fv[data-src]').count();
  if (total === 0) failures.push('no .fv[data-src] chart blocks on the page');

  // Wait until every chart has an SVG or a message that is not the loading text.
  await page.waitForFunction(() => [...document.querySelectorAll('.fv[data-src]')].every((fv) => {
    const st = fv.querySelector('.fv-stage');
    const p = st && st.querySelector(':scope > p');
    return st && (st.querySelector('svg') || (p && !/Drawing/.test(p.textContent)));
  }), null, { timeout: opts.timeout }).catch(() => failures.push(`charts not drawn within ${opts.timeout} ms`));

  const report = await page.evaluate(() => {
    const rect = (el) => el.getBoundingClientRect();
    const overlap = (a, b) => !(a.right <= b.left || b.right <= a.left || a.bottom <= b.top || b.bottom <= a.top);
    return [...document.querySelectorAll('.fv[data-src]')].map((fv) => {
      const stage = fv.querySelector('.fv-stage');
      const svg = stage.querySelector('svg');
      const msg = stage.querySelector(':scope > p');
      const nodes = svg ? [...svg.querySelectorAll('g.node')] : [];
      const boxes = nodes.map((n) => rect(n));
      let nodeOverlaps = 0;
      for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) if (overlap(boxes[i], boxes[j])) nodeOverlaps++;
      const labels = svg ? [...svg.querySelectorAll('g.edgeLabel')].filter((l) => l.textContent.trim()) : [];
      let labelsOnBoxes = 0;
      for (const l of labels) { const r = rect(l); if (r.width && boxes.some((b) => overlap(r, b))) labelsOnBoxes++; }
      const text = svg ? svg.textContent : '';
      return {
        src: fv.dataset.src,
        title: fv.dataset.title || '',
        sub: fv.dataset.sub || '',
        svg: !!svg,
        nodes: nodes.length,
        edges: svg ? svg.querySelectorAll('.edgePaths path, path.flowchart-link').length : 0,
        edgeLabels: labels.length,
        nodeOverlaps,
        labelsOnBoxes,
        errorText: (msg && msg.textContent) || (/Syntax error|Parse error/i.test(text) ? 'Mermaid error text in the SVG' : ''),
      };
    });
  });

  for (const c of report) {
    if (!c.svg) failures.push(`${c.src}: no SVG (${c.errorText || 'no message'})`);
    else if (c.errorText) failures.push(`${c.src}: ${c.errorText}`);
    if (c.svg && c.nodes < opts.minNodes) failures.push(`${c.src}: ${c.nodes} nodes, fewer than --min-nodes ${opts.minNodes}`);
    if (!/\b(UTC|GMT|BST|IST|CET|CEST|EET|EEST|WET|WEST|EST|EDT|CST|CDT|MST|MDT|PST|PDT|JST|AEST|AEDT)\b|time ?zone|[+-]\d{2}:?\d{2}\b/i.test(`${c.title} ${c.sub}`))
      warnings.push(`${c.src}: the title has no time-zone text (add the zone to data-title or data-sub)`);
    if (c.nodeOverlaps) warnings.push(`${c.src}: ${c.nodeOverlaps} pairs of boxes overlap`);
    if (c.labelsOnBoxes) warnings.push(`${c.src}: ${c.labelsOnBoxes} arrow labels sit on a box`);
  }
  for (const e of pageErrors) failures.push(`page error: ${e}`);

  const charts = page.locator('.fv[data-src]');
  for (let i = 0; i < total; i++) {
    await charts.nth(i).screenshot({ path: path.join(opts.out, `chart-${i + 1}.png`) });
  }
  if (total > 0) {
    const fullBtn = charts.nth(0).locator('button[data-z="full"]');
    if (await fullBtn.count()) {
      await fullBtn.click();
      await page.waitForTimeout(300);
      await page.screenshot({ path: path.join(opts.out, 'chart-1-full.png') });
    }
  }
  console.log(JSON.stringify({ page: opts.page, charts: report, failures, warnings, shots: path.resolve(opts.out) }, null, 2));
} finally {
  await browser.close();
}
if (failures.length) {
  console.error(`FAIL: ${failures.length} check(s) failed`);
  process.exit(1);
}
console.error(`PASS${warnings.length ? ` with ${warnings.length} warning(s): open the screenshots` : ''}`);
