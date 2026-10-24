/**
 * The coordinator source (R23): reads `<hubDir>/repos/<repo-id>/coordinator.json`.
 * Read only. The file is written by `caddis_coordinate.py`, never by the hub.
 * Contract: `scripts/schemas/coordinator.schema.json`. Schema 1 and 0 are accepted.
 */
import { readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { hubDir } from '../paths.js';

export const COORDINATOR_SCHEMA = 1;
export const RESPONDING_WITHIN_S = 180;

export interface CoordinatorEntry {
  repo_id: string;
  /** Null for an error stub (the file never parsed). */
  schema: number | null;
  coordinator_session: unknown;
  heartbeat_at: string | null;
  heartbeat_age_s: number | null;
  responding: boolean;
  queue: unknown[];
  merging_now: unknown;
  deploy_checks: unknown[];
  ledger: unknown[];
  processed_requests: unknown[];
  /** Set when the last read failed. The entry then holds the last good copy. */
  error: string | null;
  update_needed: boolean;
}
export interface CoordinatorSource {
  refresh(): void;
  get(): CoordinatorEntry[];
}
export interface CoordinatorOptions {
  home?: string;
  now?: () => number;
}

type Good = Omit<CoordinatorEntry, 'heartbeat_age_s' | 'responding' | 'error' | 'update_needed'>;

const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);

function stub(repoId: string, schema: number | null): Good {
  return {
    repo_id: repoId,
    schema,
    coordinator_session: null,
    heartbeat_at: null,
    queue: [],
    merging_now: null,
    deploy_checks: [],
    ledger: [],
    processed_requests: [],
  };
}

function parse(repoId: string, text: string): { good?: Good; newer?: Good; error?: string } {
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch (e) {
    return { error: `corrupt coordinator.json: ${(e as Error).message}` };
  }
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return { error: 'coordinator.json is not a JSON object' };
  const o = raw as Record<string, unknown>;
  const schema = o.schema;
  if (typeof schema !== 'number' || !Number.isInteger(schema) || schema < COORDINATOR_SCHEMA - 1) {
    return { error: `coordinator.json has an unusable schema: ${String(schema)}` };
  }
  if (schema > COORDINATOR_SCHEMA) {
    return {
      newer: stub(repoId, schema),
      error: `coordinator schema ${schema} is newer than this hub (${COORDINATOR_SCHEMA}): update the hub`,
    };
  }
  return {
    good: {
      repo_id: repoId,
      schema,
      coordinator_session: o.coordinator_session ?? null,
      heartbeat_at: typeof o.heartbeat_at === 'string' ? o.heartbeat_at : null,
      queue: arr(o.queue),
      merging_now: o.merging_now ?? null,
      deploy_checks: arr(o.deploy_checks).slice(-5),
      ledger: arr(o.ledger).slice(-20),
      processed_requests: arr(o.processed_requests).slice(-20),
    },
  };
}

/** `CADDIS_HUB_HOME` is the hub folder itself (as in `caddis_coordinate.py`); else `<home>/.caddis/hub`. */
function hubHome(home?: string): string {
  const override = process.env.CADDIS_HUB_HOME;
  return override ? override : hubDir(home);
}

export function createCoordinatorSource(opts: CoordinatorOptions = {}): CoordinatorSource {
  const now = opts.now ?? Date.now;
  const lastGood = new Map<string, Good>();
  const errors = new Map<string, { error: string; updateNeeded: boolean }>();

  return {
    refresh(): void {
      const root = path.join(hubHome(opts.home), 'repos');
      let ids: string[] = [];
      try {
        ids = readdirSync(root, { withFileTypes: true })
          .filter((d) => d.isDirectory())
          .map((d) => d.name);
      } catch {
        /* no repos folder yet */
      }
      const seen = new Set(ids);
      for (const id of [...lastGood.keys()]) if (!seen.has(id)) lastGood.delete(id);
      for (const id of [...errors.keys()]) if (!seen.has(id)) errors.delete(id);
      for (const id of ids) {
        let text: string;
        try {
          text = readFileSync(path.join(root, id, 'coordinator.json'), 'utf8');
        } catch (e) {
          if ((e as NodeJS.ErrnoException).code === 'ENOENT') {
            lastGood.delete(id);
            errors.delete(id);
          } else {
            if (!lastGood.has(id)) lastGood.set(id, stub(id, null));
            errors.set(id, { error: `cannot read coordinator.json: ${(e as Error).message}`, updateNeeded: false });
          }
          continue;
        }
        const r = parse(id, text);
        if (r.good) {
          lastGood.set(id, r.good);
          errors.delete(id);
          continue;
        }
        if (!lastGood.has(id)) lastGood.set(id, r.newer ?? stub(id, null));
        errors.set(id, { error: r.error ?? 'unreadable', updateNeeded: r.newer !== undefined });
      }
    },
    get(): CoordinatorEntry[] {
      const t = now();
      const out: CoordinatorEntry[] = [];
      for (const [id, good] of lastGood) {
        const ms = good.heartbeat_at ? Date.parse(good.heartbeat_at) : NaN;
        const age = Number.isNaN(ms) ? null : Math.max(0, Math.floor((t - ms) / 1000));
        const err = errors.get(id);
        out.push({
          ...good,
          heartbeat_age_s: age,
          responding: age !== null && age < RESPONDING_WITHIN_S,
          error: err?.error ?? null,
          update_needed: err?.updateNeeded ?? false,
        });
      }
      return out.sort((a, b) => a.repo_id.localeCompare(b.repo_id));
    },
  };
}
