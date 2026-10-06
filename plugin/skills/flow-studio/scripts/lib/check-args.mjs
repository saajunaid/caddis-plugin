import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const allowed = new Set(['notes', 'playback', 'update', 'hostile']);

export function pageUrl(input) {
  // try/catch, not URL.canParse: canParse needs Node 18.17+ and this skill runs on older tooling too.
  let parsed = null;
  try { parsed = new URL(input); } catch { /* not an absolute URL; treat the input as a local path */ }
  if (parsed?.protocol === 'http:' || parsed?.protocol === 'https:' || parsed?.protocol === 'file:') return parsed.href;
  return pathToFileURL(resolve(input)).href;
}

export function skippedGroups(value = '') {
  const groups = value ? value.split(',').map(s => s.trim()) : [];
  for (const group of groups) if (!allowed.has(group)) throw new Error(`unknown skip group: ${group}`);
  return new Set(groups);
}
