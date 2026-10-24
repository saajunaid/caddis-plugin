/**
 * The coordinator source (R23): reads `<hubDir>/repos/<repo-id>/coordinator.json`, and the tail of the
 * `requests.jsonl` beside it (H3, R38).
 * Read only. `coordinator.json` is written by `caddis_coordinate.py`, `requests.jsonl` by the hub's action route.
 * Contract: `scripts/schemas/coordinator.schema.json`. Schema 1 and 0 are accepted; unknown keys are ignored.
 */
import { closeSync, fstatSync, openSync, readdirSync, readFileSync, readSync } from 'node:fs';
import path from 'node:path';
import { hubDir } from '../paths.js';

export const COORDINATOR_SCHEMA = 1;
export const RESPONDING_WITHIN_S = 180;
/** Spec 7 rule 6: a request with no result after 2 min is "not picked up". */
export const PICKUP_WITHIN_MS = 2 * 60_000;
/** How much of `requests.jsonl` the source reads: its last 64 KB. */
export const REQUESTS_TAIL_BYTES = 64 * 1024;
/** The request views kept per repo, newest last. */
export const REQUESTS_SHOWN = 30;

/** R36: `live` enables actions; `stopped` is a clean `lock release`; `down` is a missing heartbeat. */
export type CoordinatorStatus = 'live' | 'stopped' | 'down';
export type RequestStatus = 'requested' | 'done' | 'rejected' | 'expired' | 'not_picked_up';

/** One owner request as the hub wrote it, joined with its result (R38). */
export interface RequestView {
  id: string;
  action: string;
  pr: number | null;
  head_sha: string | null;
  what: string | null;
  created_at: string;
  expires_at: string | null;
  status: RequestStatus;
  /** The coordinator's reason (`head moved`, `not in queue`, ...), or the hub's for `not_picked_up`. */
  reason: string | null;
  /** When the coordinator processed it, or null. */
  at: string | null;
}

export interface CoordinatorEntry {
  repo_id: string;
  /** Null for an error stub (the file never parsed). */
  schema: number | null;
  coordinator_session: unknown;
  heartbeat_at: string | null;
  heartbeat_age_s: number | null;
  /** True only when `status` is `live`. */
  responding: boolean;
  status: CoordinatorStatus;
  stopped_at: string | null;
  queue: unknown[];
  merging_now: unknown;
  deploy_checks: unknown[];
  ledger: unknown[];
  processed_requests: unknown[];
  /** Open owner-only items with the coordinator's recommendation (R37). */
  owner_asks: unknown[];
  requests: RequestView[];
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

interface RawRequest {
  id: string;
  action: string;
  pr: number | null;
  head_sha: string | null;
  what: string | null;
  created_at: string;
  expires_at: string | null;
}

type Good = Omit<
  CoordinatorEntry,
  'heartbeat_age_s' | 'responding' | 'status' | 'requests' | 'error' | 'update_needed'
> & { raw_requests: RawRequest[] };

const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const rec = (v: unknown): Record<string, unknown> =>
  v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
const str = (v: unknown): string | null => (typeof v === 'string' && v ? v : null);

function stub(repoId: string, schema: number | null): Good {
  return {
    repo_id: repoId,
    schema,
    coordinator_session: null,
    heartbeat_at: null,
    stopped_at: null,
    queue: [],
    merging_now: null,
    deploy_checks: [],
    ledger: [],
    processed_requests: [],
    owner_asks: [],
    raw_requests: [],
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
      stopped_at: typeof o.stopped_at === 'string' ? o.stopped_at : null,
      queue: arr(o.queue),
      merging_now: o.merging_now ?? null,
      deploy_checks: arr(o.deploy_checks).slice(-5),
      // Kept longer than shown: owner items (R37) and the request view (R38) join on them.
      ledger: arr(o.ledger).slice(-100),
      processed_requests: arr(o.processed_requests).slice(-100),
      owner_asks: arr(o.owner_asks).filter((a) => str(rec(a).id) && str(rec(a).what)),
      raw_requests: [],
    },
  };
}

/** The complete lines of the last `REQUESTS_TAIL_BYTES` of a file. A partial first or last line is dropped. */
export function readTailLines(file: string, maxBytes = REQUESTS_TAIL_BYTES): string[] {
  let fd: number;
  try {
    fd = openSync(file, 'r');
  } catch {
    return [];
  }
  try {
    const size = fstatSync(fd).size;
    const start = Math.max(0, size - maxBytes);
    const buf = Buffer.alloc(size - start);
    let got = 0;
    while (got < buf.length) {
      const n = readSync(fd, buf, got, buf.length - got, start + got);
      if (n <= 0) break;
      got += n;
    }
    let text = buf.subarray(0, got).toString('utf8');
    const lastNl = text.lastIndexOf('\n');
    if (lastNl < 0) return [];
    text = text.slice(0, lastNl); // a tail with no newline is still being written
    const lines = text.split('\n');
    if (start > 0) lines.shift(); // the first line was cut by the window
    return lines.map((l) => l.replace(/\r$/, '')).filter((l) => l.trim() !== '');
  } catch {
    return [];
  } finally {
    closeSync(fd);
  }
}

/** Parse request lines (spec 7 rule 4); a bad line is skipped. */
export function parseRequests(lines: string[]): RawRequest[] {
  const out: RawRequest[] = [];
  for (const line of lines) {
    let o: Record<string, unknown>;
    try {
      o = rec(JSON.parse(line));
    } catch {
      continue;
    }
    const id = str(o.id);
    const action = str(o.action);
    const created = str(o.created_at);
    if (!id || !action || !created) continue;
    out.push({
      id,
      action,
      pr: typeof o.pr === 'number' && Number.isInteger(o.pr) ? o.pr : null,
      head_sha: str(o.head_sha),
      what: str(rec(o.args).what),
      created_at: created,
      expires_at: str(o.expires_at),
    });
  }
  return out;
}

/** Join the hub's requests with the coordinator's results (R38). Newest last, at most `REQUESTS_SHOWN`. */
export function requestViews(raw: RawRequest[], processed: unknown[], now: number): RequestView[] {
  const results = new Map<string, Record<string, unknown>>();
  for (const p of processed) {
    const r = rec(p);
    const id = str(r.id);
    if (id) results.set(id, r);
  }
  const seen = new Set<string>();
  const out: RequestView[] = [];
  for (const q of raw) {
    if (seen.has(q.id)) continue;
    seen.add(q.id);
    const r = results.get(q.id);
    let status: RequestStatus;
    let reason: string | null = null;
    let at: string | null = null;
    if (r) {
      const result = str(r.result);
      status = result === 'done' || result === 'rejected' || result === 'expired' ? result : 'rejected';
      reason = str(r.reason);
      at = str(r.at);
    } else {
      const created = Date.parse(q.created_at);
      status = !Number.isNaN(created) && now - created >= PICKUP_WITHIN_MS ? 'not_picked_up' : 'requested';
      if (status === 'not_picked_up') reason = 'no coordinator intake for 2 min';
    }
    out.push({ ...q, status, reason, at });
  }
  return out.slice(-REQUESTS_SHOWN);
}

/** R36: a stop marker at or after the last heartbeat is a clean stop. */
export function coordinatorStatus(heartbeatAt: string | null, stoppedAt: string | null, ageS: number | null): CoordinatorStatus {
  const hb = heartbeatAt ? Date.parse(heartbeatAt) : NaN;
  const stop = stoppedAt ? Date.parse(stoppedAt) : NaN;
  if (!Number.isNaN(stop) && (Number.isNaN(hb) || stop >= hb)) return 'stopped';
  return ageS !== null && ageS < RESPONDING_WITHIN_S ? 'live' : 'down';
}

/** `CADDIS_HUB_HOME` is the hub folder itself (as in `caddis_coordinate.py`); else `<home>/.caddis/hub`. */
export function hubHome(home?: string): string {
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
        const requests = parseRequests(readTailLines(path.join(root, id, 'requests.jsonl')));
        let text: string;
        try {
          text = readFileSync(path.join(root, id, 'coordinator.json'), 'utf8');
        } catch (e) {
          if ((e as NodeJS.ErrnoException).code === 'ENOENT') {
            lastGood.delete(id);
            errors.delete(id);
          } else {
            if (!lastGood.has(id)) lastGood.set(id, stub(id, null));
            lastGood.get(id)!.raw_requests = requests;
            errors.set(id, { error: `cannot read coordinator.json: ${(e as Error).message}`, updateNeeded: false });
          }
          continue;
        }
        const r = parse(id, text);
        if (r.good) {
          lastGood.set(id, { ...r.good, raw_requests: requests });
          errors.delete(id);
          continue;
        }
        if (!lastGood.has(id)) lastGood.set(id, r.newer ?? stub(id, null));
        lastGood.get(id)!.raw_requests = requests;
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
        const { raw_requests, ...rest } = good;
        const status = coordinatorStatus(good.heartbeat_at, good.stopped_at, age);
        out.push({
          ...rest,
          heartbeat_age_s: age,
          responding: status === 'live',
          status,
          requests: requestViews(raw_requests, good.processed_requests, t),
          error: err?.error ?? null,
          update_needed: err?.updateNeeded ?? false,
        });
      }
      return out.sort((a, b) => a.repo_id.localeCompare(b.repo_id));
    },
  };
}
