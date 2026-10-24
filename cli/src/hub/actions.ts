/**
 * Owner actions (spec section 7; rulings R32-R35).
 *
 * The hub never merges and never runs a command from request data (spec 7 rule 1). An action only appends one
 * request line to `<hub>/repos/<repo-id>/requests.jsonl`, which the repo's coordinator applies with
 * `caddis_coordinate.py intake`, and one line to `<hub>/audit.jsonl`. Every check here runs against the state the
 * owner sees: the registry, the cached GitHub PR list and the coordinator file. Intake checks the live head again.
 */
import { randomUUID } from 'node:crypto';
import path from 'node:path';
import { appendLine } from './append.js';
import { auditPath, hubHome } from './paths.js';
import { safeRepoId, type HubState, type RepoState } from './state.js';

export const ACTIONS = ['hotfix', 'unhotfix', 'hold', 'release', 'approve', 'decline'] as const;
export type ActionName = (typeof ACTIONS)[number];
const QUEUE_ACTIONS: ReadonlySet<string> = new Set(['hotfix', 'unhotfix', 'hold', 'release']);
/** Spec 7 rule 4: a request expires 30 min after it is made. */
export const REQUEST_LIFE_MS = 30 * 60_000;
export const MAX_ACTIONS_PER_MINUTE = 20;
export const MAX_ACTION_BODY_BYTES = 2 * 1024;
export const MAX_WHAT_CHARS = 200;
const BODY_KEYS: ReadonlySet<string> = new Set(['repo_id', 'action', 'pr', 'head_sha', 'what']);
const SHA = /^[0-9a-fA-F]{40}$/;

export interface ActionReply {
  status: number;
  body: Record<string, unknown>;
}
export interface ActionsOptions {
  home?: string;
  getState: () => HubState | Promise<HubState>;
  now?: () => number;
  randomId?: () => string;
}
export interface Actions {
  /** Check one action body and, when it passes, write its request. Never throws. */
  submit(body: unknown): Promise<ActionReply>;
}

/** `YYYY-MM-DDTHH:MM:SSZ`, the format `caddis_coordinate.py` parses. */
export const utcSeconds = (ms: number): string => new Date(ms).toISOString().replace(/\.\d{3}Z$/, 'Z');

export { safeRepoId };

interface Body {
  repo_id: string;
  action: ActionName;
  pr: number | null;
  head_sha: string | null;
  what: string | null;
}

class Refusal {
  constructor(
    readonly status: number,
    readonly code: string,
    readonly reason: string,
  ) {}
}

function parseBody(raw: unknown): Body {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new Refusal(400, 'bad_request', 'The body must be a JSON object.');
  const o = raw as Record<string, unknown>;
  for (const k of Object.keys(o)) if (!BODY_KEYS.has(k)) throw new Refusal(400, 'bad_request', `Unknown key: ${k.slice(0, 40)}.`);
  if (typeof o.action !== 'string' || !(ACTIONS as readonly string[]).includes(o.action)) {
    throw new Refusal(400, 'unknown_action', 'This action is not in the v1 list.');
  }
  if (typeof o.repo_id !== 'string' || !o.repo_id) throw new Refusal(400, 'bad_request', 'repo_id is missing.');
  const pr = o.pr ?? null;
  if (pr !== null && (typeof pr !== 'number' || !Number.isInteger(pr) || pr <= 0)) {
    throw new Refusal(400, 'bad_request', 'pr must be a positive integer.');
  }
  const head = o.head_sha ?? null;
  if (head !== null && (typeof head !== 'string' || !SHA.test(head))) {
    throw new Refusal(400, 'bad_request', 'head_sha must be a full 40-character SHA.');
  }
  if ((pr === null) !== (head === null)) throw new Refusal(400, 'bad_request', 'pr and head_sha go together.');
  const what = o.what ?? null;
  if (what !== null && (typeof what !== 'string' || !what.trim() || what.length > MAX_WHAT_CHARS)) {
    throw new Refusal(400, 'bad_request', `what must be 1 to ${MAX_WHAT_CHARS} characters.`);
  }
  if (QUEUE_ACTIONS.has(o.action) && (pr === null || what !== null)) {
    throw new Refusal(400, 'bad_request', 'A queue action names a PR and its head, and no what.');
  }
  if (!QUEUE_ACTIONS.has(o.action) && what === null) throw new Refusal(400, 'bad_request', 'An approval names what it decides.');
  return { repo_id: o.repo_id, action: o.action as ActionName, pr, head_sha: head, what: what === null ? null : what.trim() };
}

/** Checks of R33 after the body shape. Returns the repo, or throws a Refusal. */
function check(state: HubState, b: Body): RepoState {
  const repo = state.repos.find((r) => r.repo_id === b.repo_id);
  if (!repo || !safeRepoId(b.repo_id)) throw new Refusal(404, 'unknown_repo', 'This repo is not in the hub registry.');
  const actions = repo.actions;
  if (!actions?.enabled) throw new Refusal(409, 'no_coordinator', actions?.reason ?? 'No live coordinator in this repo.');
  if (b.pr !== null) {
    const pr = repo.github?.prs?.find((p) => p.number === b.pr);
    if (!pr) throw new Refusal(409, 'unknown_pr', `PR #${b.pr} is not in the open PR list the hub has.`);
    if (pr.head_sha.toLowerCase() !== (b.head_sha ?? '').toLowerCase()) {
      throw new Refusal(409, 'head_moved', `The head of PR #${b.pr} moved. Reload and check it again.`);
    }
    const queued = (repo.coordinator?.queue ?? []).some((q) => (q as { pr?: unknown })?.pr === b.pr);
    if (!queued) throw new Refusal(409, 'not_in_queue', `PR #${b.pr} is not in the coordinator queue.`);
  }
  if (b.what !== null) {
    const item = (repo.owner_items ?? []).find((i) => i.what === b.what && i.pr === b.pr);
    if (!item) throw new Refusal(409, 'unknown_item', 'This is not an open owner item of the repo.');
    if (item.head_sha && b.head_sha && item.head_sha.toLowerCase() !== b.head_sha.toLowerCase()) {
      throw new Refusal(409, 'head_moved', 'The PR head moved after the recommendation. Ask the coordinator again.');
    }
  }
  return repo;
}

export function createActions(opts: ActionsOptions): Actions {
  const now = opts.now ?? Date.now;
  const randomId = opts.randomId ?? randomUUID;
  const root = (): string => hubHome(opts.home);
  const auditFile = (): string => auditPath(opts.home);
  let recent: number[] = [];

  const audit = async (entry: Record<string, unknown>): Promise<void> => {
    try {
      await appendLine(auditFile(), JSON.stringify({ v: 1, at: utcSeconds(now()), ...entry }));
    } catch {
      /* the audit line is best effort; the request line is the record that acts */
    }
  };

  const refuse = async (r: Refusal, b: Partial<Body>): Promise<ActionReply> => {
    await audit({
      request_id: null,
      repo: typeof b.repo_id === 'string' ? b.repo_id.slice(0, 120) : null,
      pr: typeof b.pr === 'number' ? b.pr : null,
      action: typeof b.action === 'string' ? b.action.slice(0, 20) : null,
      what: typeof b.what === 'string' ? b.what.slice(0, MAX_WHAT_CHARS) : null,
      result: 'refused',
      reason: r.code,
    });
    return { status: r.status, body: { schema: 1, error: r.code, reason: r.reason } };
  };

  return {
    async submit(raw: unknown): Promise<ActionReply> {
      const t = now();
      recent = recent.filter((x) => t - x < 60_000);
      if (recent.length >= MAX_ACTIONS_PER_MINUTE) {
        return { status: 429, body: { schema: 1, error: 'rate_limited', reason: 'Too many actions in one minute. Wait, then try again.' } };
      }
      recent.push(t);
      let body: Body;
      try {
        body = parseBody(raw);
      } catch (e) {
        if (e instanceof Refusal) return refuse(e, (raw && typeof raw === 'object' ? raw : {}) as Partial<Body>);
        throw e;
      }
      try {
        check(await opts.getState(), body);
      } catch (e) {
        if (e instanceof Refusal) return refuse(e, body);
        return refuse(new Refusal(500, 'state_failed', 'The hub could not read its state.'), body);
      }
      const request = {
        v: 1,
        id: randomId(),
        created_at: utcSeconds(t),
        expires_at: utcSeconds(t + REQUEST_LIFE_MS),
        repo: body.repo_id,
        pr: body.pr,
        head_sha: body.head_sha === null ? null : body.head_sha.toLowerCase(),
        action: body.action,
        args: body.what === null ? {} : { what: body.what },
      };
      try {
        await appendLine(path.join(root(), 'repos', body.repo_id, 'requests.jsonl'), JSON.stringify(request));
      } catch {
        return refuse(new Refusal(500, 'write_failed', 'The hub could not write the request.'), body);
      }
      await audit({
        request_id: request.id,
        repo: body.repo_id,
        pr: body.pr,
        action: body.action,
        what: body.what,
        result: 'requested',
        reason: null,
      });
      return { status: 202, body: { schema: 1, request } };
    },
  };
}
