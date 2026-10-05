// Validate a flow-studio model.
//   node --experimental-strip-types scripts/validate.mjs <model.json>
// Exit 0: no errors (warnings are printed). Exit 1: at least one error. Exit 2: cannot read the file.

import { readFileSync } from "node:fs";
import { validateModel } from "../src/model.ts";

export function loadModel(path) {
  let text;
  try {
    text = readFileSync(path, "utf8");
  } catch (e) {
    console.error(`cannot read ${path}: ${e.message}`);
    process.exit(2);
  }
  try {
    return JSON.parse(text);
  } catch (e) {
    console.error(`${path} is not valid JSON: ${e.message}`);
    process.exit(2);
  }
}

export function report(issues) {
  for (const i of issues) console.log(`${i.level.toUpperCase().padEnd(5)} ${i.code.padEnd(16)} ${i.where}: ${i.message}`);
  return issues.filter(i => i.level === "error").length;
}

if (process.argv[1]?.endsWith("validate.mjs")) {
  const path = process.argv[2];
  if (!path) {
    console.error("usage: node --experimental-strip-types scripts/validate.mjs <model.json>");
    process.exit(2);
  }
  const errors = report(validateModel(loadModel(path)));
  console.log(errors ? `${errors} error(s)` : "OK");
  process.exit(errors ? 1 : 0);
}
