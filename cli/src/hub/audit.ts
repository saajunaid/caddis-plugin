/**
 * The audit tail (R51): the last lines of `<hub>/audit.jsonl`, read only.
 * The hub action route writes the file (R35). Activity shows these lines as owner actions.
 * Each line is cut down to the keys below, so a stray key never reaches the browser.
 */
import { statSync } from 'node:fs';
import { auditPath } from './paths.js';
import { readTailLines } from './sources/coordinator.js';

export const AUDIT_KEEP = 200;
export const AUDIT_TAIL_BYTES = 64 * 1024;

export interface AuditEntry {
  at: string;
  request_id: string | null;
  repo: string | null;
  pr: number | null;
  action: string | null;
  what: string | null;
  result: string | null;
  reason: string | null;
}

const text = (v: unknown, max = 500): string | null => (typeof v === 'string' && v ? v.slice(0, max) : null);

/** Parse audit lines. A line that is not an object, or has no valid `at`, is skipped. */
export function parseAudit(lines: string[]): AuditEntry[] {
  const out: AuditEntry[] = [];
  for (const line of lines) {
    let o: unknown;
    try {
      o = JSON.parse(line);
    } catch {
      continue;
    }
    if (!o || typeof o !== 'object' || Array.isArray(o)) continue;
    const r = o as Record<string, unknown>;
    const at = text(r.at, 40);
    if (!at || Number.isNaN(Date.parse(at))) continue;
    out.push({
      at,
      request_id: text(r.request_id, 80),
      repo: text(r.repo, 120),
      pr: typeof r.pr === 'number' && Number.isInteger(r.pr) ? r.pr : null,
      action: text(r.action, 20),
      what: text(r.what),
      result: text(r.result, 20),
      reason: text(r.reason),
    });
  }
  return out;
}

const cache = new Map<string, { sig: string; value: AuditEntry[] }>();

/** The last `AUDIT_KEEP` valid lines, in file order. A missing or unreadable file gives `[]`. */
export function readAudit(home?: string): AuditEntry[] {
  const file = auditPath(home);
  let sig: string;
  try {
    const st = statSync(file);
    sig = `${st.size}:${st.mtimeMs}`;
  } catch {
    cache.delete(file);
    return [];
  }
  const hit = cache.get(file);
  if (hit && hit.sig === sig) return hit.value;
  const value = parseAudit(readTailLines(file, AUDIT_TAIL_BYTES)).slice(-AUDIT_KEEP);
  cache.set(file, { sig, value });
  return value;
}
