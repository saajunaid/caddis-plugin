// Safe embedding of a model into the engine template.
// JSON placed inside a <script> tag must not be able to close it or start markup, so the
// characters < > & and the two Unicode line separators are written as \u escapes. The result is
// still valid JSON and parses back to the same value.

export function escapeJson(value) {
  return JSON.stringify(value)
    .replace(/</g, "\\u003c")
    .replace(/>/g, "\\u003e")
    .replace(/&/g, "\\u0026")
    .replace(/\u2028/g, "\\u2028")
    .replace(/\u2029/g, "\\u2029");
}

const MODEL_SLOT = "/*__MODEL__*/{}";
const NOTES_SLOT = "/*__NOTES__*/[]";

export function embedModel(shell, model, notes = []) {
  if (!shell.includes(MODEL_SLOT) || !shell.includes(NOTES_SLOT)) {
    throw new Error("The shell is missing a model slot or a notes slot.");
  }
  // Replacer functions: a "$" in the data must never act as a replacement pattern.
  return shell.replace(MODEL_SLOT, () => escapeJson(model)).replace(NOTES_SLOT, () => escapeJson(notes));
}
