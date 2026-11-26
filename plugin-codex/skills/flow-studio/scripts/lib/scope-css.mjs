// Pure CSS scoping transform for templates/flow-studio.scoped.css.
// Wraps all non-@keyframes rules in `@scope (<rootSelector>) { ... }`, rewrites :root and plain body
// selectors so custom properties and base styles bind to the scope host, and emits LF-only text.

function scanTopLevelSelectorList(selectorList) {
  const parts = [];
  let start = 0;
  let paren = 0;
  let bracket = 0;
  let quote = "";
  for (let i = 0; i < selectorList.length; i++) {
    const ch = selectorList[i];
    if (quote) {
      if (ch === "\\") i++;
      else if (ch === quote) quote = "";
      continue;
    }
    if (ch === '"' || ch === "'") { quote = ch; continue; }
    if (ch === "/" && selectorList[i + 1] === "*") {
      const end = selectorList.indexOf("*/", i + 2);
      i = end >= 0 ? end + 1 : selectorList.length;
      continue;
    }
    if (ch === "(") paren++;
    else if (ch === ")" && paren > 0) paren--;
    else if (ch === "[") bracket++;
    else if (ch === "]" && bracket > 0) bracket--;
    else if (ch === "," && paren === 0 && bracket === 0) {
      parts.push(selectorList.slice(start, i));
      start = i + 1;
    }
  }
  parts.push(selectorList.slice(start));
  return parts;
}

function splitLeadingComments(raw) {
  let i = 0;
  while (i < raw.length) {
    if (/\s/.test(raw[i])) { i++; continue; }
    if (raw[i] === "/" && raw[i + 1] === "*") {
      const end = raw.indexOf("*/", i + 2);
      if (end < 0) { i = raw.length; break; }
      i = end + 2;
      continue;
    }
    break;
  }
  return { leading: raw.slice(0, i), rest: raw.slice(i).trim() };
}

const HOST_STATE_COMPOUND_RE = /^(?:\.(?:intro|notes|playing|alt))+(?:[:\[][\s\S]*)?$/;

function splitFirstCompound(rest) {
  let i = 0;
  let paren = 0;
  let bracket = 0;
  let quote = "";
  while (i < rest.length) {
    const ch = rest[i];
    if (quote) {
      if (ch === "\\") i += 2;
      else { if (ch === quote) quote = ""; i++; }
      continue;
    }
    if (ch === '"' || ch === "'") { quote = ch; i++; continue; }
    if (ch === "/" && rest[i + 1] === "*") {
      const end = rest.indexOf("*/", i + 2);
      i = end >= 0 ? end + 2 : rest.length;
      continue;
    }
    if (ch === "(") { paren++; i++; continue; }
    if (ch === ")" && paren > 0) { paren--; i++; continue; }
    if (ch === "[") { bracket++; i++; continue; }
    if (ch === "]" && bracket > 0) { bracket--; i++; continue; }
    if (paren === 0 && bracket === 0 && (/\s/.test(ch) || ch === ">" || ch === "+" || ch === "~")) break;
    i++;
  }
  return { compound: rest.slice(0, i), tail: rest.slice(i) };
}

function rewriteSingleSelector(sel, rootSelector) {
  const { leading, rest } = splitLeadingComments(sel);
  if (rest === ":root" || rest === "body") return `${leading}:scope`;
  const { compound, tail } = splitFirstCompound(rest);
  if (/^(?:body|html)(?![A-Za-z0-9_-])/i.test(compound)) {
    throw new Error(`scopeCss: unsupported root element selector "${rest}"`);
  }
  if (/^:root(?![A-Za-z0-9_-])/.test(compound)) {
    return tail.trim() ? `${leading}${compound} :scope${tail}` : `${leading}${compound} :scope`;
  }
  if (
    rootSelector &&
    (compound === rootSelector ||
      (compound.startsWith(rootSelector) && !/^[A-Za-z0-9_-]/.test(compound.slice(rootSelector.length))))
  ) {
    const suffix = compound.slice(rootSelector.length);
    return `${leading}:scope${suffix}${tail}`;
  }
  if (HOST_STATE_COMPOUND_RE.test(compound)) {
    return `${leading}:scope${compound}${tail}`;
  }
  return `${leading}${rest}`;
}

function rewriteSelectorList(prelude, rootSelector) {
  const { leading, rest } = splitLeadingComments(prelude);
  const rewritten = scanTopLevelSelectorList(rest).map((part, idx) => {
    const out = rewriteSingleSelector(part, rootSelector);
    return idx === 0 ? out.trimStart() : " " + out.trimStart();
  }).join(",");
  return `${leading}${rewritten}`;
}

const SUPPORTED_GROUP_ATRULES = new Set(["@media", "@supports", "@starting-style"]);
const ANIMATION_KEYWORDS = new Set([
  "none", "initial", "inherit", "unset", "revert", "revert-layer",
  "linear", "ease", "ease-in", "ease-out", "ease-in-out", "step-start", "step-end",
  "normal", "reverse", "alternate", "alternate-reverse",
  "forwards", "backwards", "both",
  "running", "paused",
  "infinite",
]);

function splitTopLevelByChar(text, sep) {
  const parts = [];
  let start = 0;
  let paren = 0;
  let quote = "";
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quote) {
      if (ch === "\\") i++;
      else if (ch === quote) quote = "";
      continue;
    }
    if (ch === '"' || ch === "'") { quote = ch; continue; }
    if (ch === "(") paren++;
    else if (ch === ")" && paren > 0) paren--;
    else if (ch === sep && paren === 0) {
      parts.push(text.slice(start, i));
      start = i + 1;
    }
  }
  parts.push(text.slice(start));
  return parts;
}

function tokenizeAnimationSpec(spec) {
  const tokens = [];
  let cur = "";
  let paren = 0;
  let quote = "";
  for (let i = 0; i < spec.length; i++) {
    const ch = spec[i];
    if (quote) {
      cur += ch;
      if (ch === "\\" && i + 1 < spec.length) cur += spec[++i];
      else if (ch === quote) quote = "";
      continue;
    }
    if (ch === '"' || ch === "'") { quote = ch; cur += ch; continue; }
    if (ch === "(") { paren++; cur += ch; continue; }
    if (ch === ")" && paren > 0) { paren--; cur += ch; continue; }
    if (/\s/.test(ch) && paren === 0) {
      if (cur) { tokens.push(cur); cur = ""; }
      continue;
    }
    cur += ch;
  }
  if (cur) tokens.push(cur);
  return tokens;
}

export function extractAnimationRefs(bodyText) {
  const clean = bodyText.replace(/\/\*[\s\S]*?\*\//g, "");
  const refs = [];
  for (const decl of splitTopLevelByChar(clean, ";")) {
    const colon = decl.indexOf(":");
    if (colon < 0) continue;
    const prop = decl.slice(0, colon).trim().toLowerCase();
    if (prop !== "animation" && prop !== "animation-name") continue;
    const rawVal = decl.slice(colon + 1).replace(/!important\s*$/i, "").trim();
    if (!rawVal) continue;
    for (const spec of splitTopLevelByChar(rawVal, ",")) {
      if (prop === "animation-name") {
        const token = spec.trim();
        if (token && !ANIMATION_KEYWORDS.has(token.toLowerCase())) refs.push(token);
        continue;
      }
      for (const token of tokenizeAnimationSpec(spec)) {
        if (ANIMATION_KEYWORDS.has(token.toLowerCase())) continue;
        if (/^[+-]?(?:\d+|\d*\.\d+)(?:ms|s|%)?$/i.test(token)) continue;
        if (token.includes("(")) continue;
        refs.push(token);
      }
    }
  }
  return refs;
}

function extractKeyframeName(cleanPrelude) {
  const m = cleanPrelude.match(/^@(?:-[A-Za-z]+-)?keyframes\s+([^\s{]+)/i);
  return m ? m[1] : "";
}

export function parseCssBlocks(css) {
  const src = css.replace(/\r\n?/g, "\n");
  const blocks = [];
  let start = 0;
  let braceStart = -1;
  let depth = 0;
  let quote = "";
  for (let i = 0; i < src.length; i++) {
    const ch = src[i];
    if (quote) {
      if (ch === "\\") i++;
      else if (ch === quote) quote = "";
      continue;
    }
    if (ch === '"' || ch === "'") { quote = ch; continue; }
    if (ch === "/" && src[i + 1] === "*") {
      const end = src.indexOf("*/", i + 2);
      i = end >= 0 ? end + 1 : src.length;
      continue;
    }
    if (ch === ";" && depth === 0) {
      blocks.push({ prelude: src.slice(start, i + 1), body: null });
      start = i + 1;
    } else if (ch === "{") {
      if (depth === 0) braceStart = i;
      depth++;
    } else if (ch === "}") {
      depth--;
      if (depth < 0) throw new Error('scopeCss: unexpected "}" in stylesheet');
      if (depth === 0 && braceStart >= 0) {
        blocks.push({
          prelude: src.slice(start, braceStart),
          body: src.slice(braceStart + 1, i),
        });
        start = i + 1;
        braceStart = -1;
      }
    }
  }
  if (depth !== 0) throw new Error('scopeCss: unclosed "{" in stylesheet');
  const trailing = src.slice(start);
  if (trailing.replace(/\/\*[\s\S]*?\*\//g, "").trim()) {
    blocks.push({ prelude: trailing, body: null });
  }
  return blocks;
}

function transformBlock(block, indent, rootSelector, state, nested = false) {
  const clean = block.prelude.replace(/\/\*[\s\S]*?\*\//g, "").trim();
  const atMatch = clean.match(/^@[A-Za-z_-]+/);
  if (block.body === null) {
    if (atMatch) throw new Error(`scopeCss: unsupported at-rule ${atMatch[0]}`);
    throw new Error(`scopeCss: unexpected CSS statement "${clean}"`);
  }
  if (/^@(-webkit-)?keyframes\b/i.test(clean)) {
    if (nested) throw new Error(`scopeCss: unsupported at-rule ${atMatch ? atMatch[0] : "@keyframes"} inside nested block`);
    const kfName = extractKeyframeName(clean);
    if (!kfName || !kfName.startsWith("fs-")) {
      throw new Error(`scopeCss: @keyframes "${kfName || clean}" must start with "fs-"`);
    }
    state.definedKeyframes.add(kfName);
    const { leading, rest } = splitLeadingComments(block.prelude);
    const prefix = leading.trim() ? `${indent}${leading.trim()}\n` : "";
    return { keyframes: true, text: `${prefix}${indent}${rest} {${block.body}}` };
  }
  if (atMatch) {
    const ruleName = atMatch[0].toLowerCase();
    if (!SUPPORTED_GROUP_ATRULES.has(ruleName)) {
      throw new Error(`scopeCss: unsupported at-rule ${atMatch[0]}`);
    }
    const innerBlocks = parseCssBlocks(block.body);
    if (innerBlocks.length === 0) {
      throw new Error(`scopeCss: ${atMatch[0]} block must contain rules`);
    }
    const { leading, rest } = splitLeadingComments(block.prelude);
    const prefix = leading.trim() ? `${indent}${leading.trim()}\n` : "";
    const inner = innerBlocks.map(b => transformBlock(b, indent + "  ", rootSelector, state, true).text).join("\n");
    return { keyframes: false, text: `${prefix}${indent}${rest} {\n${inner}\n${indent}}` };
  }
  for (const ref of extractAnimationRefs(block.body)) {
    state.animationRefs.push(ref);
  }
  const rewritten = rewriteSelectorList(block.prelude, rootSelector);
  const { leading, rest } = splitLeadingComments(rewritten);
  const prefix = leading.trim() ? `${indent}${leading.trim()}\n` : "";
  return { keyframes: false, text: `${prefix}${indent}${rest} {${block.body}}` };
}

export function scopeCss(css, rootSelector = ".fs-root") {
  const blocks = parseCssBlocks(css);
  const state = { definedKeyframes: new Set(), animationRefs: [] };
  const scoped = [];
  const keyframes = [];
  for (const block of blocks) {
    const out = transformBlock(block, "  ", rootSelector, state);
    if (out.keyframes) {
      const { leading, rest } = splitLeadingComments(block.prelude);
      const prefix = leading.trim() ? `${leading.trim()}\n` : "";
      keyframes.push(`${prefix}${rest} {${block.body}}`);
    } else {
      scoped.push(out.text);
    }
  }
  for (const ref of state.animationRefs) {
    if (!ref.startsWith("fs-")) {
      throw new Error(`scopeCss: animation reference "${ref}" must start with "fs-"`);
    }
    if (!state.definedKeyframes.has(ref)) {
      throw new Error(`scopeCss: animation reference "${ref}" has no matching @keyframes`);
    }
  }
  const parts = [`@scope (${rootSelector}) {\n${scoped.join("\n")}\n}`];
  if (keyframes.length) parts.push(...keyframes);
  return parts.join("\n") + "\n";
}
