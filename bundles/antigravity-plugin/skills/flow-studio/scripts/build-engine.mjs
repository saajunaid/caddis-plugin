// Build templates/engine.html from the TypeScript sources.
//   node --experimental-strip-types scripts/build-engine.mjs           write templates/engine.html
//   node --experimental-strip-types scripts/build-engine.mjs --check   exit 1 if the committed file is stale
// esbuild is a dev-time tool. It is looked up in this folder, in the caddis cli folder, then in the
// current directory. The built page has no dependency on it.

import { createRequire } from "node:module";
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { dirname, resolve, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");

function loadEsbuild() {
  const candidates = [join(root, "package.json"), resolve(root, "../../../../cli/package.json"), join(process.cwd(), "package.json")];
  for (const c of candidates) {
    if (!existsSync(dirname(c))) continue;
    try { return createRequire(c)("esbuild"); } catch { /* try the next place */ }
  }
  throw new Error("esbuild was not found. Run `npm i -D esbuild` in the skill folder, or run this from the caddis checkout (cli/node_modules has it).");
}

const normalise = text => text.replace(/\r\n/g, "\n");

export async function buildEngine() {
  const esbuild = loadEsbuild();
  const out = await esbuild.build({
    entryPoints: [join(root, "src/engine.ts")],
    bundle: true, format: "iife", target: "es2022", minify: false, write: false, legalComments: "none", logLevel: "silent",
  });
  const js = out.outputFiles[0].text;
  if (/<\/script/i.test(js)) throw new Error("The bundle contains a closing script tag; it would end the page's script early.");
  const css = readFileSync(join(root, "src/styles.css"), "utf8");
  if (/<\/style/i.test(css)) throw new Error("The stylesheet contains a closing style tag; it would end the page style early.");
  if (css.includes("/*__ENGINE__*/") || css.includes("/*__MODEL__*/") || css.includes("/*__NOTES__*/")) throw new Error("The stylesheet contains a template slot marker.");
  const shell = readFileSync(join(root, "templates/engine.shell.html"), "utf8");
  for (const slot of ["/*__CSS__*/", "/*__ENGINE__*/", "/*__MODEL__*/{}", "/*__NOTES__*/[]"]) {
    if (!shell.includes(slot)) throw new Error(`The shell is missing the slot ${slot}`);
  }
  return normalise(shell.replace("/*__CSS__*/", () => css).replace("/*__ENGINE__*/", () => js));
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const target = join(root, "templates/engine.html");
  const html = await buildEngine();
  if (process.argv.includes("--check")) {
    const have = existsSync(target) ? normalise(readFileSync(target, "utf8")) : "";
    if (have !== html) { console.error("templates/engine.html is stale. Run: node --experimental-strip-types scripts/build-engine.mjs"); process.exit(1); }
    console.log("templates/engine.html is up to date");
  } else {
    writeFileSync(target, html, "utf8");
    console.log(`wrote templates/engine.html (${html.length} bytes)`);
  }
}
