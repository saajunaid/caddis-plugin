// Build templates/engine.html from the TypeScript sources.
//   node --experimental-strip-types scripts/build-engine.mjs           write templates/engine.html
//   node --experimental-strip-types scripts/build-engine.mjs --check   exit 1 if the committed file is stale
// esbuild is a dev-time tool. It is looked up in FLOW_STUDIO_NODE_MODULES first, then this folder,
// the caddis cli folder, and the current directory. The built page has no dependency on it.

import { createRequire } from "node:module";
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { dirname, resolve, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");

export function resolveEsbuild(candidateDirs, requireFactory = createRequire) {
  for (const dir of candidateDirs) {
    if (!existsSync(dir)) continue;
    try { return requireFactory(join(dir, "package.json"))("esbuild"); } catch { /* try the next place */ }
  }
  throw new Error("esbuild was not found. Check FLOW_STUDIO_NODE_MODULES or run `npm i -D esbuild` in the skill folder.");
}

function loadEsbuild() {
  const configured = process.env.FLOW_STUDIO_NODE_MODULES;
  const candidates = [
    ...(configured ? [configured] : []),
    root,
    resolve(root, "../../../../cli"),
    process.cwd(),
  ];
  return resolveEsbuild(candidates);
}

const normalise = text => text.replace(/\r\n/g, "\n");

export async function buildEngine() {
  const esbuild = loadEsbuild();
  const out = await esbuild.build({
    entryPoints: [join(root, "src/page.ts")],
    bundle: true, format: "iife", target: "es2022", minify: false, write: false, legalComments: "none", logLevel: "silent",
  });
  const js = out.outputFiles[0].text;
  if (/<\/script/i.test(js)) throw new Error("The bundle contains a closing script tag; it would end the page's script early.");
  const css = readFileSync(join(root, "src/styles.css"), "utf8");
  if (/<\/style/i.test(css)) throw new Error("The stylesheet contains a closing style tag; it would end the page style early.");
  if (css.includes("/*__ENGINE__*/") || css.includes("/*__MODEL__*/") || css.includes("/*__NOTES__*/")) throw new Error("The stylesheet contains a template slot marker.");
  const shell = readFileSync(join(root, "templates/engine.shell.html"), "utf8");
  for (const slot of ["/*__CSS__*/", "/*__SHELL_BODY__*/", "/*__ENGINE__*/", "/*__MODEL__*/{}", "/*__NOTES__*/[]"]) {
    if (!shell.includes(slot)) throw new Error(`The shell is missing the slot ${slot}`);
  }
  const body = readFileSync(join(root, "templates/shell-body.html"), "utf8");
  return normalise(shell.replace("/*__CSS__*/", () => css).replace("/*__SHELL_BODY__*/", () => body).replace("/*__ENGINE__*/", () => js));
}

export async function buildLibrary() {
  const esbuild = loadEsbuild();
  const out = await esbuild.build({
    entryPoints: [join(root, "src/lib.ts")], bundle: true, format: "esm", target: "es2022",
    minify: false, write: false, legalComments: "none", logLevel: "silent",
  });
  const marker = JSON.stringify("/*__SHELL_BODY__*/");
  const bundled = out.outputFiles[0].text;
  if (bundled.split(marker).length !== 2) throw new Error("The library must contain one shell body slot.");
  const body = readFileSync(join(root, "templates/shell-body.html"), "utf8");
  const js = bundled.replace(marker, () => JSON.stringify(body));
  const css = readFileSync(join(root, "src/styles.css"), "utf8");
  return { js: normalise(js), css };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const target = join(root, "templates/engine.html");
  const libTarget = join(root, "templates/flow-studio.lib.mjs");
  const cssTarget = join(root, "templates/flow-studio.css");
  if (process.argv.includes("--check")) {
    const html = await buildEngine();
    const { js, css } = await buildLibrary();
    const have = existsSync(target) ? normalise(readFileSync(target, "utf8")) : "";
    const haveLib = existsSync(libTarget) ? normalise(readFileSync(libTarget, "utf8")) : "";
    const haveCss = existsSync(cssTarget) ? readFileSync(cssTarget, "utf8") : "";
    if (have !== html || haveLib !== js || haveCss !== css) {
      console.error("Generated engine or library files are stale. Run `node --experimental-strip-types scripts/build-engine.mjs` and `node --experimental-strip-types scripts/build-engine.mjs --lib`.");
      process.exit(1);
    }
    console.log("engine and library files are up to date");
  } else if (process.argv.includes("--lib")) {
    const { js, css } = await buildLibrary();
    writeFileSync(libTarget, js, "utf8");
    writeFileSync(cssTarget, css, "utf8");
    console.log(`wrote templates/flow-studio.lib.mjs and templates/flow-studio.css`);
  } else {
    const html = await buildEngine();
    writeFileSync(target, html, "utf8");
    console.log(`wrote templates/engine.html (${html.length} bytes)`);
  }
}
