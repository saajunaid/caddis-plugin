// Browser proof for templates/flow-studio.scoped.css in an embedded mount (#host).
// Generates an untracked embed page under out/, serves the skill folder locally so ES module
// imports load without CORS errors, mounts examples/lineage.json (with a 1-step in-memory
// scenario on the clone) into #host, asserts computed styles, and saves a notes-open screenshot.
//   node scripts/check-embed.mjs [--page out/embed.html] [--out out/embed-shots] [--channel msedge] [--json file]

import { createServer } from "node:http";
import { createRequire } from "node:module";
import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { dirname, extname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");

const argv = process.argv.slice(2);
const opt = (name, dflt) => {
  const i = argv.indexOf(name);
  return i >= 0 ? argv[i + 1] : dflt;
};

const pagePath = resolve(root, opt("--page", "out/embed.html"));
const outDir = resolve(root, opt("--out", "out/embed-shots"));
const channel = opt("--channel", undefined);
const jsonOut = opt("--json", undefined);

const relFromRoot = relative(root, pagePath).replace(/\\/g, "/");
if (relFromRoot.startsWith("..") || relFromRoot.includes(":")) {
  console.error(`check-embed: --page must be inside ${root} (for example out/embed.html)`);
  process.exit(2);
}

let chromium;
const candidateBases = [
  process.cwd(),
  process.env.FLOW_STUDIO_NODE_MODULES && resolve(process.env.FLOW_STUDIO_NODE_MODULES, ".."),
  resolve(root, "../../../../cli"),
].filter(Boolean);
for (const base of candidateBases) {
  try {
    ({ chromium } = createRequire(join(base, "x.js"))("playwright"));
    break;
  } catch { /* try next */ }
}
if (!chromium) {
  console.error("Cannot resolve 'playwright'. Run with FLOW_STUDIO_NODE_MODULES pointing to cli/node_modules or from cli/.");
  process.exit(2);
}

const depth = relFromRoot.split("/").length - 1;
const prefixToRoot = depth > 0 ? "../".repeat(depth) : "./";

function buildEmbedHtml(relPrefix) {
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Flow Studio Scoped Embed Proof</title>
  <link rel="icon" href="data:,">
  <link rel="stylesheet" href="${relPrefix}templates/flow-studio.scoped.css">
</head>
<body>
  <section id="app-chrome">
    <h1 id="outside-h1">Host Application</h1>
    <p id="outside-p">Normal page content outside the flow-studio mount container.</p>
    <button id="outside-btn" type="button">Host Action</button>
  </section>
  <div id="host"></div>
  <script type="module">
    import { mount, SHELL_BODY_HTML } from "${relPrefix}templates/flow-studio.lib.mjs";

    const response = await fetch("${relPrefix}examples/lineage.json");
    if (!response.ok) throw new Error("Failed to load examples/lineage.json: " + response.status);
    const rawModel = await response.json();
    const model = structuredClone(rawModel);
    const stepLink = model.links.find(l => !l.visibleIn) ?? model.links[0];
    model.scenarios = [
      {
        id: "embed-check",
        label: "Embed check",
        steps: [{ link: stepLink.id, at: 0, dur: 4000, caption: "Scoped playback check" }],
      },
    ];

    const host = document.getElementById("host");
    host.innerHTML = SHELL_BODY_HTML;
    window.embedFlow = mount(host, model);
  </script>
</body>
</html>
`;
}

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
};

function startStaticServer(baseDir) {
  return new Promise((resolveServer, reject) => {
    const server = createServer((req, res) => {
      try {
        const pathname = decodeURIComponent(new URL(req.url ?? "/", "http://127.0.0.1").pathname);
        const filePath = resolve(baseDir, "." + pathname);
        const rel = relative(baseDir, filePath);
        if (rel.startsWith("..") || !existsSync(filePath) || !statSync(filePath).isFile()) {
          res.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
          res.end("Not found");
          return;
        }
        const contentType = MIME[extname(filePath).toLowerCase()] ?? "application/octet-stream";
        res.writeHead(200, { "Content-Type": contentType, "Cache-Control": "no-store" });
        res.end(readFileSync(filePath));
      } catch (err) {
        res.writeHead(500, { "Content-Type": "text/plain; charset=utf-8" });
        res.end(String(err));
      }
    });
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const addr = server.address();
      resolveServer({ server, port: typeof addr === "object" && addr ? addr.port : 0 });
    });
  });
}

mkdirSync(dirname(pagePath), { recursive: true });
mkdirSync(outDir, { recursive: true });
writeFileSync(pagePath, buildEmbedHtml(prefixToRoot), "utf8");

const results = [];
const check = (name, ok, detail = "") => {
  results.push({ group: "embed", name, ok: !!ok, detail: String(detail) });
  console.log(`${ok ? "PASS" : "FAIL"}  [embed] ${name}${detail ? "  " + detail : ""}`);
};

const { server, port } = await startStaticServer(root);
const browser = await chromium.launch(channel ? { channel } : {});

try {
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 900 }, colorScheme: "light" });
  const page = await ctx.newPage();
  const consoleErrors = [];
  const pageErrors = [];
  page.on("pageerror", e => pageErrors.push(String(e)));
  page.on("console", m => { if (m.type() === "error") consoleErrors.push(m.text()); });

  const targetUrl = `http://127.0.0.1:${port}/${relFromRoot}`;
  await page.goto(targetUrl);
  await page.waitForFunction(() => !!window.FlowStudio && !!window.embedFlow, null, { timeout: 10000 });
  await page.waitForTimeout(500);

  // 1. Only flow-studio.scoped.css is linked
  const sheets = await page.evaluate(() => {
    const links = [...document.querySelectorAll('link[rel="stylesheet"]')].map(l => l.getAttribute("href") ?? "");
    return { links, inlineStyles: [...document.querySelectorAll("style")].map(s => s.id) };
  });
  check(
    "embed page links ONLY templates/flow-studio.scoped.css",
    sheets.links.length === 1 && sheets.links[0].endsWith("templates/flow-studio.scoped.css") && sheets.inlineStyles.every(id => id === "state-css"),
    `links=${JSON.stringify(sheets.links)} styles=${JSON.stringify(sheets.inlineStyles)}`,
  );

  // 2. #host has position: relative and fs-root
  const hostStyle = await page.evaluate(() => {
    const host = document.getElementById("host");
    const cs = getComputedStyle(host);
    return {
      hasFsRoot: host.classList.contains("fs-root"),
      position: cs.position,
      fontFamily: cs.fontFamily,
    };
  });
  check(
    "#host has position: relative",
    hostStyle.hasFsRoot && hostStyle.position === "relative",
    `position=${hostStyle.position} fs-root=${hostStyle.hasFsRoot}`,
  );

  // 3. Page content outside #host keeps its own font and margin (scoped CSS does not leak)
  const outsideStyle = await page.evaluate(() => {
    const bodyCs = getComputedStyle(document.body);
    const h1Cs = getComputedStyle(document.getElementById("outside-h1"));
    const pCs = getComputedStyle(document.getElementById("outside-p"));
    const chromeCs = getComputedStyle(document.getElementById("app-chrome"));
    const hostCs = getComputedStyle(document.getElementById("host"));
    return {
      bodyClassName: document.body.className,
      bodyMarginTop: parseFloat(bodyCs.marginTop),
      bodyFont: bodyCs.fontFamily,
      hostFont: hostCs.fontFamily,
      pFont: pCs.fontFamily,
      pMarginTop: parseFloat(pCs.marginTop),
      pMarginBottom: parseFloat(pCs.marginBottom),
      h1Font: h1Cs.fontFamily,
      h1MarginTop: parseFloat(h1Cs.marginTop),
      h1BorderBottomStyle: h1Cs.borderBottomStyle,
      chromeBoxSizing: chromeCs.boxSizing,
    };
  });
  const noLeak =
    outsideStyle.bodyClassName === "" &&
    outsideStyle.bodyMarginTop > 0 &&
    !outsideStyle.pFont.includes("Inter") &&
    outsideStyle.hostFont.includes("Inter") &&
    outsideStyle.pMarginTop >= 14 &&
    outsideStyle.pMarginBottom >= 14 &&
    !outsideStyle.h1Font.includes("Inter") &&
    outsideStyle.h1MarginTop > 10 &&
    outsideStyle.h1BorderBottomStyle === "none" &&
    outsideStyle.chromeBoxSizing === "content-box";
  check(
    "page content outside #host keeps its own font and margin (scoped CSS does not leak)",
    noLeak,
    `bodyMargin=${outsideStyle.bodyMarginTop}px pMargin=${outsideStyle.pMarginTop}px pFont=${outsideStyle.pFont} hostFont=${outsideStyle.hostFont}`,
  );

  // 4. Alt view shows new-node dots (and baseline hides them)
  const altCheck = await page.evaluate(async () => {
    const host = document.getElementById("host");
    window.FlowStudio.setMode("today");
    await new Promise(r => setTimeout(r, 100));
    const baseHasAlt = host.classList.contains("alt");
    const baseVisibleDots = [...host.querySelectorAll(".node:not(.off) .newdot")].filter(d => getComputedStyle(d).display !== "none").length;

    window.FlowStudio.setMode("complete");
    await new Promise(r => setTimeout(r, 100));
    const altHasAlt = host.classList.contains("alt");
    const bodyHasAlt = document.body.classList.contains("alt");
    const newNodes = [...host.querySelectorAll(".node:not(.off).isnew")];
    const shownDots = newNodes.filter(n => {
      const dot = n.querySelector(".newdot");
      if (!dot) return false;
      const cs = getComputedStyle(dot);
      const r = dot.getBoundingClientRect();
      return cs.display !== "none" && dot.offsetWidth === 7 && dot.offsetHeight === 7 && r.width > 0 && r.height > 0;
    }).length;
    return { baseHasAlt, baseVisibleDots, altHasAlt, bodyHasAlt, newNodeCount: newNodes.length, shownDots };
  });
  check(
    "alt view sets alt on #host and shows the new-node dots",
    !altCheck.baseHasAlt &&
      altCheck.baseVisibleDots === 0 &&
      altCheck.altHasAlt &&
      !altCheck.bodyHasAlt &&
      altCheck.newNodeCount > 0 &&
      altCheck.shownDots === altCheck.newNodeCount,
    `newNodes=${altCheck.newNodeCount} shownDots=${altCheck.shownDots} baseDots=${altCheck.baseVisibleDots}`,
  );

  // 5. Playback sets playing on #host and .node.playing has a non-none animation-name starting with fs-
  const playCheck = await page.evaluate(async () => {
    const host = document.getElementById("host");
    window.FlowStudio.play("embed-check");
    await new Promise(r => setTimeout(r, 140));
    const hostPlaying = host.classList.contains("playing");
    const bodyPlaying = document.body.classList.contains("playing");
    const node = host.querySelector(".node.playing");
    const animationName = node ? getComputedStyle(node).animationName : "";
    const animationDuration = node ? getComputedStyle(node).animationDuration : "";
    window.FlowStudio.pause();
    return { hostPlaying, bodyPlaying, hasNode: !!node, animationName, animationDuration };
  });
  check(
    "during playback .node.playing has a non-none animation-name starting with fs-",
    playCheck.hostPlaying &&
      !playCheck.bodyPlaying &&
      playCheck.hasNode &&
      playCheck.animationName !== "none" &&
      playCheck.animationName.startsWith("fs-"),
    `animationName=${playCheck.animationName} duration=${playCheck.animationDuration}`,
  );

  // 6. Toggling notes puts notes on #host, drawer computed transform is none, and markers are inside #host
  const notesBefore = await page.evaluate(() => {
    const host = document.getElementById("host");
    const drawer = host.querySelector("#drawer");
    return {
      hasNotes: host.classList.contains("notes"),
      drawerTransform: getComputedStyle(drawer).transform,
    };
  });
  await page.click("#host #notesBtn");
  await page.waitForTimeout(500);
  const notesAfter = await page.evaluate(() => {
    const host = document.getElementById("host");
    const drawer = host.querySelector("#drawer");
    const hostMarkers = [...host.querySelectorAll(".marker")];
    const allMarkers = [...document.querySelectorAll(".marker")];
    return {
      hostHasNotes: host.classList.contains("notes"),
      bodyHasNotes: document.body.classList.contains("notes"),
      drawerTransform: getComputedStyle(drawer).transform,
      hostMarkerCount: hostMarkers.length,
      allMarkerCount: allMarkers.length,
      allInsideHost: allMarkers.every(m => m.closest("#host") === host),
      allAbsolute: hostMarkers.every(m => getComputedStyle(m).position === "absolute"),
    };
  });
  check(
    "toggling notes puts notes on #host and sets #drawer computed transform to none",
    !notesBefore.hasNotes &&
      notesBefore.drawerTransform !== "none" &&
      notesAfter.hostHasNotes &&
      !notesAfter.bodyHasNotes &&
      notesAfter.drawerTransform === "none",
    `before=${notesBefore.drawerTransform} after=${notesAfter.drawerTransform}`,
  );
  check(
    "note markers are rendered inside #host",
    notesAfter.hostMarkerCount > 0 &&
      notesAfter.hostMarkerCount === notesAfter.allMarkerCount &&
      notesAfter.allInsideHost &&
      notesAfter.allAbsolute,
    `markers=${notesAfter.hostMarkerCount}`,
  );

  const screenshotPath = join(outDir, "embed-notes.png");
  await page.screenshot({ path: screenshotPath });
  console.log(`SCREENSHOT  ${screenshotPath}`);

  // 7. 0 console errors and 0 page errors
  const allErrors = [...pageErrors, ...consoleErrors];
  check("0 console errors", allErrors.length === 0, allErrors.join(" | "));

  await ctx.close();
} finally {
  await browser.close();
  await new Promise(r => server.close(r));
}

const failed = results.filter(r => !r.ok);
console.log(`\n${results.length - failed.length} passed, ${failed.length} failed`);
if (jsonOut) writeFileSync(resolve(jsonOut), JSON.stringify(results, null, 2), "utf8");
process.exit(failed.length ? 1 : 0);
