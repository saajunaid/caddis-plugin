import http from 'node:http';
import { randomBytes } from 'node:crypto';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createActions, MAX_ACTIONS_PER_MINUTE, safeRepoId, utcSeconds } from '../../src/hub/actions.js';
import { appendLine } from '../../src/hub/append.js';
import { hubDir } from '../../src/hub/paths.js';
import { startServer } from '../../src/hub/server.js';
import { repoActions, type HubState, type RepoState } from '../../src/hub/state.js';
import type { CoordinatorEntry } from '../../src/hub/sources/coordinator.js';

const SHA = 'A'.repeat(40);
const OTHER = 'B'.repeat(40);
const T0 = Date.parse('2026-10-24T10:00:00.250Z');
let home: string;
let t: number;

beforeEach(() => {
  vi.stubEnv('CADDIS_HUB_HOME', '');
  home = mkdtempSync(path.join(tmpdir(), 'caddis-hub-'));
  t = T0;
});
afterEach(() => {
  vi.unstubAllEnvs();
  rmSync(home, { recursive: true, force: true });
});

const coordinator = (over: Partial<CoordinatorEntry> = {}): CoordinatorEntry => ({
  repo_id: 'acme__shop',
  schema: 1,
  coordinator_session: { name: 'demo-coordinator', sessionId: 's1', pid: 2 },
  heartbeat_at: '2026-10-24T09:59:50Z',
  heartbeat_age_s: 10,
  responding: true,
  status: 'live',
  stopped_at: null,
  queue: [{ pr: 7, head_sha: SHA.toLowerCase(), title: 't', state: 'ready' }],
  merging_now: null,
  deploy_checks: [],
  ledger: [],
  processed_requests: [],
  owner_asks: [],
  requests: [],
  error: null,
  update_needed: false,
  ...over,
});

function repoState(c: CoordinatorEntry | null): RepoState {
  return {
    path: '/srv/demo/shop',
    name: 'shop',
    repo_id: 'acme__shop',
    pinned: false,
    roadmaps: null,
    plans: null,
    relays: null,
    github: {
      path: '/srv/demo/shop',
      repo: 'acme/shop',
      account: 'demo',
      prs: [
        { number: 7, title: 't', head_sha: SHA, author: null, draft: false, updated_at: null, url: '', checks: [], required_state: 'pass' },
        { number: 8, title: 'u', head_sha: OTHER, author: null, draft: false, updated_at: null, url: '', checks: [], required_state: 'pass' },
      ],
      merges: [],
    },
    coordinator: c,
    owner_items: [
      { id: 'ask:1', what: 'schema change on prod', pr: 7, head_sha: SHA.toLowerCase(), source: 'coordinator', recommendation: null, from: null, since: null },
      { id: 'gate:g:P2-OG1', what: 'owner gate P2-OG1 (g)', pr: null, head_sha: null, source: 'relay', recommendation: null, from: null, since: null },
    ],
    actions: repoActions(c),
  };
}

function hubState(c: CoordinatorEntry | null = coordinator()): HubState {
  const s = (ok: boolean) => ({ ok, last_ok_at: null, last_error: null, stale: false });
  return {
    schema: 1,
    generated_at: '2026-10-24T10:00:00Z',
    versions: { hub: '0', pool: null, plugin: null },
    sources: { collector: s(true), agents: s(true), github: s(true), coordinator: s(true) },
    update_needed: false,
    repos: [repoState(c)],
    sessions: [],
    spend: null,
    guide: null,
    github_rate: {},
  };
}

const reqFile = (): string => path.join(hubDir(home), 'repos', 'acme__shop', 'requests.jsonl');
const auditFile = (): string => path.join(hubDir(home), 'audit.jsonl');
const lines = (file: string): Record<string, unknown>[] =>
  existsSync(file) ? readFileSync(file, 'utf8').trim().split('\n').filter(Boolean).map((l) => JSON.parse(l)) : [];

let ids = 0;
const make = (state: HubState = hubState()) =>
  createActions({ home, getState: () => state, now: () => t, randomId: () => `id-${++ids}` });
const hold = { repo_id: 'acme__shop', action: 'hold', pr: 7, head_sha: SHA };

describe('createActions: refusals (R33)', () => {
  const cases: [string, Record<string, unknown>, HubState | undefined, number, string][] = [
    ['an unknown action', { ...hold, action: 'merge' }, undefined, 400, 'unknown_action'],
    ['an unknown key', { ...hold, run: 'x' }, undefined, 400, 'bad_request'],
    ['a short SHA', { ...hold, head_sha: 'abc' }, undefined, 400, 'bad_request'],
    ['a PR with no head', { ...hold, head_sha: null }, undefined, 400, 'bad_request'],
    ['a queue action with what', { ...hold, what: 'x' }, undefined, 400, 'bad_request'],
    ['an approval with no what', { repo_id: 'acme__shop', action: 'approve', pr: null, head_sha: null }, undefined, 400, 'bad_request'],
    ['a repo not in the registry', { ...hold, repo_id: 'acme__other' }, undefined, 404, 'unknown_repo'],
    ['no coordinator', hold, hubState(null), 409, 'no_coordinator'],
    ['a stopped coordinator', hold, hubState(coordinator({ status: 'stopped', responding: false })), 409, 'no_coordinator'],
    ['a down coordinator', hold, hubState(coordinator({ status: 'down', responding: false })), 409, 'no_coordinator'],
    ['a PR not open', { ...hold, pr: 99 }, undefined, 409, 'unknown_pr'],
    ['a moved head', { ...hold, head_sha: OTHER }, undefined, 409, 'head_moved'],
    ['a PR not in the queue', { ...hold, pr: 8, head_sha: OTHER }, undefined, 409, 'not_in_queue'],
    ['an approval of an unknown item', { repo_id: 'acme__shop', action: 'approve', pr: null, head_sha: null, what: 'anything' }, undefined, 409, 'unknown_item'],
    ['an approval with the wrong PR', { repo_id: 'acme__shop', action: 'approve', pr: null, head_sha: null, what: 'schema change on prod' }, undefined, 409, 'unknown_item'],
  ];
  for (const [name, body, state, status, code] of cases) {
    it(`refuses ${name}: ${status} ${code}, writes no request, audits the refusal`, async () => {
      const r = await make(state).submit(body);
      expect(r.status).toBe(status);
      expect(r.body).toMatchObject({ schema: 1, error: code });
      expect(typeof r.body.reason).toBe('string');
      expect(existsSync(reqFile())).toBe(false);
      const audit = lines(auditFile());
      expect(audit).toHaveLength(1);
      expect(audit[0]).toMatchObject({ v: 1, result: 'refused', reason: code, request_id: null });
    });
  }

  it('gives the no-coordinator sentence the UI shows', async () => {
    const r = await make(hubState(null)).submit(hold);
    expect(r.body.reason).toContain('No coordinator');
  });

  it('refuses a body that is not an object', async () => {
    for (const body of [null, 'x', [1], 3]) expect((await make().submit(body)).status).toBe(400);
  });

  it('refuses a repo id that could leave the hub folder', () => {
    for (const bad of ['', '.', '..', 'a/b', 'a\\b', 'a:b', 'con', 'NUL.txt', 'com1', 'lpt9.x', 'x.', 'x ', 'a..b']) {
      expect(safeRepoId(bad), bad).toBe(false);
    }
    for (const ok of ['acme__shop', 'local__shop__abc123', 'local__My Repo__abc123', 'com0', 'console', 'a.b', 'x+y']) {
      expect(safeRepoId(ok), ok).toBe(true);
    }
  });

  it('the state disables actions for an id the server would refuse, with the reason', async () => {
    const state = hubState();
    state.repos[0]!.repo_id = 'con';
    state.repos[0]!.actions = repoActions(coordinator(), 'con');
    expect(state.repos[0]!.actions).toMatchObject({ enabled: false, code: 'bad_repo_id' });
    expect(state.repos[0]!.actions.reason).toContain('cannot name a hub folder');
    const r = await make(state).submit({ ...hold, repo_id: 'con' });
    expect([r.status, r.body.error]).toEqual([404, 'unknown_repo']);
    expect(repoActions(coordinator(), 'acme__shop').enabled).toBe(true);
  });
});

describe('createActions: accepted requests (R34, R35)', () => {
  it('writes exactly the spec 7 rule 4 line and a requested audit line', async () => {
    const r = await make().submit(hold);
    expect(r.status).toBe(202);
    const [line] = lines(reqFile());
    expect(Object.keys(line!)).toEqual(['v', 'id', 'created_at', 'expires_at', 'repo', 'pr', 'head_sha', 'action', 'args']);
    expect(line).toEqual({
      v: 1,
      id: `id-${ids}`,
      created_at: '2026-10-24T10:00:00Z',
      expires_at: '2026-10-24T10:30:00Z',
      repo: 'acme__shop',
      pr: 7,
      head_sha: SHA.toLowerCase(),
      action: 'hold',
      args: {},
    });
    expect(r.body).toEqual({ schema: 1, request: line });
    expect(lines(auditFile())).toEqual([
      { v: 1, at: '2026-10-24T10:00:00Z', request_id: `id-${ids}`, repo: 'acme__shop', pr: 7, action: 'hold', what: null, result: 'requested', reason: null },
    ]);
  });

  it('an approval of a no-PR item carries pr null, head null and args.what', async () => {
    const r = await make().submit({ repo_id: 'acme__shop', action: 'decline', what: ' owner gate P2-OG1 (g) ' });
    expect(r.status).toBe(202);
    expect(lines(reqFile())[0]).toMatchObject({ pr: null, head_sha: null, action: 'decline', args: { what: 'owner gate P2-OG1 (g)' } });
  });

  it('an approval of a PR item checks its PR and head', async () => {
    const ok = await make().submit({ repo_id: 'acme__shop', action: 'approve', pr: 7, head_sha: SHA, what: 'schema change on prod' });
    expect(ok.status).toBe(202);
    expect(lines(reqFile())[0]).toMatchObject({ pr: 7, action: 'approve', args: { what: 'schema change on prod' } });
  });

  it('uses a random uuid by default', async () => {
    const r = await createActions({ home, getState: () => hubState(), now: () => t }).submit(hold);
    expect((r.body.request as { id: string }).id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[0-9a-f]{4}-[0-9a-f]{12}$/);
  });

  it(`refuses the action after ${MAX_ACTIONS_PER_MINUTE} in one minute, and accepts again after it`, async () => {
    const a = make();
    for (let i = 0; i < MAX_ACTIONS_PER_MINUTE; i++) expect((await a.submit(hold)).status).toBe(202);
    const r = await a.submit(hold);
    expect(r).toMatchObject({ status: 429, body: { error: 'rate_limited' } });
    t += 60_001;
    expect((await a.submit(hold)).status).toBe(202);
    expect(lines(reqFile())).toHaveLength(MAX_ACTIONS_PER_MINUTE + 1);
  });

  it('formats times with whole seconds', () => {
    expect(utcSeconds(Date.parse('2026-10-24T10:00:00.999Z'))).toBe('2026-10-24T10:00:00Z');
  });
});

describe('appendLine (R34)', () => {
  it('20 parallel appends give 20 whole lines', async () => {
    const file = path.join(home, 'x', 'requests.jsonl');
    const payload = (i: number): string => JSON.stringify({ i, pad: 'p'.repeat(3000) });
    await Promise.all(Array.from({ length: 20 }, (_, i) => appendLine(file, payload(i))));
    const got = readFileSync(file, 'utf8').split('\n');
    expect(got.pop()).toBe('');
    expect(got.map((l) => JSON.parse(l).i).sort((a, b) => a - b)).toEqual(Array.from({ length: 20 }, (_, i) => i));
  });

  it('closes a tail with no newline first, so the new line stays whole', async () => {
    const file = path.join(home, 'requests.jsonl');
    writeFileSync(file, '{"half":');
    await appendLine(file, '{"ok":1}');
    expect(readFileSync(file, 'utf8')).toBe('{"half":\n{"ok":1}\n');
  });

  it('refuses a line with a newline', async () => {
    await expect(appendLine(path.join(home, 'f'), 'a\nb')).rejects.toThrow('newline');
  });
});

// ---- the route (R32) ----

interface Res {
  status: number;
  headers: http.IncomingHttpHeaders;
  body: string;
}
let srv: { port: number; close: () => Promise<void> };
let key: string;

function req(method: string, p: string, headers: Record<string, string> = {}, body?: string): Promise<Res> {
  return new Promise((resolve, reject) => {
    const r = http.request(
      { host: '127.0.0.1', port: srv.port, method, path: p, headers: { host: `127.0.0.1:${srv.port}`, ...headers }, agent: false },
      (res) => {
        const chunks: Buffer[] = [];
        res.on('data', (c: Buffer) => chunks.push(c));
        res.on('end', () => resolve({ status: res.statusCode ?? 0, headers: res.headers, body: Buffer.concat(chunks).toString('utf8') }));
      },
    );
    r.on('error', reject);
    if (body !== undefined) r.write(body);
    r.end();
  });
}

async function login(): Promise<{ cookie: string; tab: string; csrf: string }> {
  const code = JSON.parse((await req('POST', '/api/hub/code', { 'x-caddis-hub-key': key })).body).code as string;
  const r = await req('GET', `/login?code=${code}`);
  const cookie = String((r.headers['set-cookie'] as string[])[0]).split(';')[0]!;
  const tab = /#tab=(.+)$/.exec(String(r.headers.location))![1]!;
  const s = await req('GET', '/api/session', { cookie, 'x-caddis-hub-tab': tab });
  return { cookie, tab, csrf: JSON.parse(s.body).csrf_token as string };
}

describe('POST /api/actions (R32)', () => {
  let auth: { cookie: string; tab: string; csrf: string };
  const headers = (over: Record<string, string | undefined> = {}): Record<string, string> => {
    const h: Record<string, string | undefined> = {
      origin: `http://127.0.0.1:${srv.port}`,
      cookie: auth.cookie,
      'x-csrf-token': auth.csrf,
      'x-caddis-hub-tab': auth.tab,
      'content-type': 'application/json',
      ...over,
    };
    return Object.fromEntries(Object.entries(h).filter((e): e is [string, string] => e[1] !== undefined));
  };
  const post = (h: Record<string, string>, body = JSON.stringify(hold)): Promise<Res> => req('POST', '/api/actions', h, body);

  beforeEach(async () => {
    key = randomBytes(32).toString('hex');
    srv = await startServer({ port: 0, key, getState: () => hubState(), versions: {}, actions: make() });
    auth = await login();
  });
  afterEach(async () => {
    await srv.close();
  });

  it('accepts a good action', async () => {
    const r = await post(headers());
    expect(r.status).toBe(202);
    expect(JSON.parse(r.body).request.action).toBe('hold');
    expect(lines(reqFile())).toHaveLength(1);
  });

  const refused: [string, Record<string, string | undefined>, number][] = [
    ['no Origin', { origin: undefined }, 403],
    ['Origin null', { origin: 'null' }, 403],
    ['another Origin', { origin: 'http://127.0.0.1:1' }, 403],
    ['no cookie', { cookie: undefined }, 401],
    ['no CSRF token', { 'x-csrf-token': undefined }, 403],
    ['a wrong CSRF token', { 'x-csrf-token': 'x' }, 403],
    ['no tab token', { 'x-caddis-hub-tab': undefined }, 401],
    ['a wrong tab token', { 'x-caddis-hub-tab': 'x' }, 401],
    ['a form content type', { 'content-type': 'application/x-www-form-urlencoded' }, 415],
    ['a text content type', { 'content-type': 'text/plain' }, 415],
  ];
  for (const [name, over, status] of refused) {
    it(`refuses ${name} with ${status} and writes nothing`, async () => {
      const r = await post(headers(over));
      expect(r.status).toBe(status);
      expect(existsSync(reqFile())).toBe(false);
    });
  }

  it('refuses a body over 2 KB and bad JSON', async () => {
    expect((await post(headers(), JSON.stringify({ ...hold, what: 'x'.repeat(3000) }))).status).toBe(413);
    expect((await post(headers(), '{bad')).status).toBe(400);
    expect(existsSync(reqFile())).toBe(false);
  });

  it('answers 404 when the server has no actions', async () => {
    await srv.close();
    srv = await startServer({ port: 0, key, getState: () => hubState(), versions: {} });
    auth = await login();
    expect((await post(headers())).status).toBe(404);
  });

  it('never puts the key, cookie, CSRF or tab token in a reply or an audit line', async () => {
    const replies = [await post(headers()), await post(headers(), JSON.stringify({ ...hold, pr: 99 }))];
    const text = replies.map((r) => r.body + JSON.stringify(r.headers)).join('') + readFileSync(auditFile(), 'utf8');
    for (const secret of [key, auth.cookie.split('=')[1]!, auth.csrf, auth.tab]) expect(text).not.toContain(secret);
  });
});

describe('the hub folder', () => {
  it('requests go beside coordinator.json', async () => {
    mkdirSync(path.join(hubDir(home), 'repos', 'acme__shop'), { recursive: true });
    await make().submit(hold);
    expect(existsSync(reqFile())).toBe(true);
  });
});
