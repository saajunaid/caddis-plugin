// Build one self-contained HTML page from a model.
//   node --experimental-strip-types scripts/build.mjs <model.json> <out.html> [--notes notes.json]
// The model is validated first. Any error stops the build (exit 1). Warnings are printed.

import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { validateModel } from "../src/model.ts";
import { embedModel } from "./lib/embed.mjs";
import { loadModel, report } from "./validate.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const notesAt = args.indexOf("--notes");
const notesPath = notesAt >= 0 ? args.splice(notesAt, 2)[1] : null;
const [modelPath, outPath] = args;
if (!modelPath || !outPath) {
  console.error("usage: node --experimental-strip-types scripts/build.mjs <model.json> <out.html> [--notes notes.json]");
  process.exit(2);
}

const model = loadModel(modelPath);
const errors = report(validateModel(model));
if (errors) {
  console.error(`${errors} error(s): not building.`);
  process.exit(1);
}
const extra = notesPath ? loadModel(notesPath) : [];
if (notesPath && !Array.isArray(extra)) {
  console.error(`${notesPath} must be a JSON array of notes.`);
  process.exit(2);
}
const notes = [...(Array.isArray(model.notes) ? model.notes : []), ...(Array.isArray(extra) ? extra : [])].map((n, i) => ({ ...n, id: i + 1 }));
const shell = readFileSync(resolve(here, "../templates/engine.html"), "utf8");
mkdirSync(dirname(resolve(outPath)), { recursive: true });
writeFileSync(outPath, embedModel(shell, model, notes), "utf8");
console.log(`wrote ${outPath}`);
