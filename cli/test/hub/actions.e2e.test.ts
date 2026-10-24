/**
 * The H3 gate (spec section 12, ruling R43): each v1 action goes through the real hub server, is written as a
 * request line, is processed by a fixture coordinator that runs the REAL `caddis_coordinate.py` intake, and its
 * result shows in `/api/state`. No real `gh` or `claude`: GitHub, sessions and the collector are fakes; the
 * coordinator files are real, in a temp hub folder.
 */
import http from 'node:http';
import { spawnSync } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest';
import { createActions } from '../../src/hub/actions.js';
import { addRepos, normalizeRepoPath, resetHubCache } from '../../src/hub/config.js';
import { hubDir } from '../../src/hub/paths.js';
import { startServer } from '../../src/hub/server.js';
import { createHub, safeRepoId, type HubState, type StateHub } from '../../src/hub/state.js';
import type { AgentsSource } from '../../src/hub/sources/agents.js';
import type { CollectorSource } from '../../src/hub/sources/collector.js';
import { createCoordinatorSource, type RequestView } from '../../src/hub/sources/coordinator.js';
import type { GithubSource } from '../../src/hub/sources/github.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const SCRIPTS = path.resolve(here, '..', '..', '..', 'scripts');
const COORDINATE = path.join(SCRIPTS, 'caddis_coordinate.py');
const FIXTURE = path.join(here, 'fixtures', 'fixture_coordinator.py');
const RID = 'acme__shop';
const SHA7 = 'A'.repeat(40);
const SHA8 = 'C'.repeat(40);
const MOVED = 'D'.repeat(40);

/** Python 3.11+ as `python`, then `py -3` (Windows). Null when neither is there: the suite is skipped. */
function findPython(): string[] | null {
  for (const cmd of [['python'], ['python3'], ['py', '-3']]) {
    const r = spawnSync(cmd[0]!, [...cmd.slice(1), '-c', 'import sys; print(sys.version_info >= (3, 11))'], {
      encoding: 'utf8',
      windowsHide: true,
      timeout: 20_000,
    });
    if (r.status === 0 && r.stdout.trim() === 'True') return cmd;
  }
  return null;
}
const PY = existsSync(COORDINATE) ? findPython() : null;

let home: string;
let hubFolder: string;
let offset = 0;
const now = (): number => Date.now() + offset;

function py(args: string[]): { status: number | null; stdout: string; stderr: string } {
  const r = spawnSync(PY![0]!, [...PY!.slice(1), '-B', ...args], {
    encoding: 'utf8',
    windowsHide: true,
    timeout: 60_000,
    env: { ...process.env, CADDIS_HUB_HOME: hubFolder },
  });
  return { status: r.status, stdout: r.stdout, stderr: r.stderr };
}
const coordinate = (...args: string[]) => {
  const r = py([COORDINATE, ...args]);
  expect(r.status, r.stderr).toBe(0);
  return r.stdout;
};
/** One coordinator watcher cycle's intake, with the live heads given here (no gh). */
const intake = (heads: Record<number, string>): { id: string; result: string; reason: string }[] => {
  const r = py([FIXTURE, SCRIPTS, RID, JSON.stringify(heads)]);
  expect(r.status, r.stderr).toBe(0);
  return JSON.parse(r.stdout) as { id: string; result: string; reason: string }[];
};
const coordinatorJson = (): Record<string, unknown> =>
  JSON.parse(readFileSync(path.join(hubFolder, 'repos', RID, 'coordinator.json'), 'utf8')) as Record<string, unknown>;

// ---- the hub with fake GitHub, sessions and collector; the real coordinator source ----

let state: StateHub;
let srv: { port: number; close: () => Promise<void> };
let heads: Record<number, string>;
let auth: { cookie: string; tab: string; csrf: string };

function fakeGithub(repoPath: string): GithubSource {
  return {
    refresh: async () => {},
    nextDelayMs: () => 60_000,
    get: () => ({
      ok: true,
      last_ok_at: new Date(now()).toISOString(),
      last_error: null,
      stale: false,
      data: {
        repos: [
          {
            path: repoPath,
            repo: 'acme/shop',
            account: 'demo',
            last_ok_at: new Date(now()).toISOString(),
            prs: Object.entries(heads).map(([n, sha]) => ({
              number: Number(n),
              title: `PR ${n}`,
              head_sha: sha,
              author: 'demo-author',
              draft: false,
              updated_at: null,
              url: '',
              checks: [],
              required_state: 'pass' as const,
            })),
            merges: [],
          },
        ],
        rate: { demo: { remaining: 4000, reset_at: null } },
      },
    }),
  };
}
const quiet = <T,>(data: T) => ({ refresh: async () => {}, get: () => ({ ok: true, last_ok_at: new Date(now()).toISOString(), last_error: null, stale: false, ...data }) });

function req(method: string, p: string, headers: Record<string, string> = {}, body?: string): Promise<{ status: number; headers: http.IncomingHttpHeaders; body: string }> {
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

/** Sign in the way the browser does: one-time code, cookie, tab token from the fragment, CSRF from the session. */
async function login(key: string): Promise<{ cookie: string; tab: string; csrf: string }> {
  const code = JSON.parse((await req('POST', '/api/hub/code', { 'x-caddis-hub-key': key })).body).code as string;
  const r = await req('GET', `/login?code=${code}`);
  const cookie = String((r.headers['set-cookie'] as string[])[0]).split(';')[0]!;
  const tab = /#tab=(.+)$/.exec(String(r.headers.location))![1]!;
  const s = await req('GET', '/api/session', { cookie, 'x-caddis-hub-tab': tab });
  return { cookie, tab, csrf: JSON.parse(s.body).csrf_token as string };
}

async function act(body: Record<string, unknown>): Promise<{ status: number; body: Record<string, unknown> }> {
  const r = await req(
    'POST',
    '/api/actions',
    {
      origin: `http://127.0.0.1:${srv.port}`,
      cookie: auth.cookie,
      'x-csrf-token': auth.csrf,
      'x-caddis-hub-tab': auth.tab,
      'content-type': 'application/json',
    },
    JSON.stringify(body),
  );
  return { status: r.status, body: JSON.parse(r.body) as Record<string, unknown> };
}

async function apiState(): Promise<HubState> {
  await state.refreshAll();
  const r = await req('GET', '/api/state', { cookie: auth.cookie, 'x-caddis-hub-tab': auth.tab });
  expect(r.status).toBe(200);
  return JSON.parse(r.body) as HubState;
}
const shop = (s: HubState) => s.repos.find((r) => r.repo_id === RID)!;
const viewOf = (s: HubState, id: string): RequestView | undefined => shop(s).coordinator?.requests.find((r) => r.id === id);
const idOf = (r: { body: Record<string, unknown> }): string => (r.body.request as { id: string }).id;

// The gate must run in CI: there a missing Python fails the run. Locally it skips with this note.
describe.runIf(PY === null && !!process.env.CI)('H3 gate: Python', () => {
  it('needs Python 3.11+ in CI', () => {
    throw new Error('the H3 gate test needs Python 3.11+ (python, python3 or py -3) and scripts/caddis_coordinate.py');
  });
});

describe.skipIf(PY === null)('H3 gate: actions end to end through a fixture coordinator', () => {
  beforeAll(async () => {
    vi.stubEnv('CADDIS_HUB_HOME', '');
    resetHubCache();
    home = mkdtempSync(path.join(tmpdir(), 'caddis-hub-'));
    hubFolder = hubDir(home);
    heads = { 7: SHA7, 8: SHA8 };
    // The coordinator side, with the real script: lock (this test's live pid), a queue of two PRs, two owner asks.
    coordinate('lock', 'acquire', '--repo', RID, '--pid', String(process.pid), '--session-id', 'demo-session', '--name', 'demo-coordinator');
    coordinate('queue', 'add', '--repo', RID, '--pr', '7', '--head-sha', SHA7, '--title', 'search filters');
    coordinate('queue', 'add', '--repo', RID, '--pr', '8', '--head-sha', SHA8, '--title', 'cart total');
    coordinate('ask', 'add', '--repo', RID, '--what', 'schema change on prod', '--recommendation', 'approve', '--reason',
      'The change is additive.', '--evidence', 'migration test green; undo: drop the column', '--pr', '7', '--head-sha', SHA7);
    coordinate('ask', 'add', '--repo', RID, '--what', 'overnight agy run', '--recommendation', 'hold', '--reason',
      'It runs unattended.', '--evidence', 'estimate EUR 80');

    // The hub side: a registered repo folder whose remote is acme/shop.
    const repoPath = normalizeRepoPath(path.join(home, 'src', 'shop'));
    mkdirSync(path.join(repoPath, '.git'), { recursive: true });
    writeFileSync(path.join(repoPath, '.git', 'config'), '[remote "origin"]\n\turl = https://github.com/acme/shop.git\n');
    addRepos([repoPath], home);
    state = createHub({
      home,
      now,
      github: fakeGithub(repoPath),
      agents: quiet({ data: [] }) as unknown as AgentsSource,
      collector: quiet({ update_needed: false, data: { schema: 1, generated_at: new Date().toISOString(), repos: [], spend: {}, guide: {} } }) as unknown as CollectorSource,
      coordinator: createCoordinatorSource({ home, now }),
      versions: () => ({ hub: '0.0.0-e2e', pool: null, plugin: null }),
    });
    const key = randomBytes(32).toString('hex');
    srv = await startServer({ port: 0, key, getState: () => state.getState(), versions: {}, actions: createActions({ home, getState: () => state.getState(), now }) });
    await state.refreshAll();
    auth = await login(key);
  }, 120_000);

  afterAll(async () => {
    await srv?.close();
    vi.unstubAllEnvs();
    resetHubCache();
    rmSync(home, { recursive: true, force: true });
  });

  it('shows the live coordinator, the queue, and both owner asks with their recommendations', async () => {
    const s = shop(await apiState());
    expect(s.actions).toEqual({ enabled: true, code: 'ok', reason: null });
    expect(s.coordinator!.status).toBe('live');
    expect(s.coordinator!.queue.map((q) => (q as { pr: number }).pr)).toEqual([7, 8]);
    expect(s.owner_items.map((o) => [o.what, o.pr, o.recommendation?.decision, o.from])).toEqual([
      ['schema change on prod', 7, 'approve', 'demo-coordinator'],
      ['overnight agy run', null, 'hold', 'demo-coordinator'],
    ]);
  });

  it('hotfix, hold, approve and decline: requested, then done, with their effects', async () => {
    const sent = [
      await act({ repo_id: RID, action: 'hotfix', pr: 7, head_sha: SHA7 }),
      await act({ repo_id: RID, action: 'hold', pr: 8, head_sha: SHA8 }),
      await act({ repo_id: RID, action: 'approve', pr: 7, head_sha: SHA7, what: 'schema change on prod' }),
      await act({ repo_id: RID, action: 'decline', what: 'overnight agy run' }),
    ];
    for (const r of sent) expect(r.status, JSON.stringify(r.body)).toBe(202);
    const ids = sent.map(idOf);
    let s = await apiState();
    expect(ids.map((id) => viewOf(s, id)?.status)).toEqual(['requested', 'requested', 'requested', 'requested']);

    const results = intake(heads);
    expect(results.map((r) => [r.id, r.result])).toEqual(ids.map((id) => [id, 'done']));

    s = await apiState();
    expect(ids.map((id) => viewOf(s, id)?.status)).toEqual(['done', 'done', 'done', 'done']);
    const file = coordinatorJson();
    const queue = file.queue as { pr: number; hotfix: boolean; held: boolean }[];
    expect(queue.find((q) => q.pr === 7)!.hotfix).toBe(true);
    expect(queue.find((q) => q.pr === 8)!.held).toBe(true);
    const ledger = file.ledger as { what: string; decision: string; approved_by: string; window: string; request_id: string }[];
    expect(ledger.map((e) => [e.what, e.decision, e.approved_by, e.window, e.request_id])).toEqual([
      ['schema change on prod', 'approve', 'owner', 'hub', ids[2]],
      ['overnight agy run', 'decline', 'owner', 'hub', ids[3]],
    ]);
    expect(file.owner_asks).toEqual([]);
    expect(shop(s).owner_items).toEqual([]);
    // The audit file has one line per request, and no secret.
    const audit = readFileSync(path.join(hubFolder, 'audit.jsonl'), 'utf8');
    for (const id of ids) expect(audit).toContain(id);
    expect(audit).not.toContain(auth.csrf);
  });

  it('unhotfix and release: done, and the flags clear', async () => {
    const sent = [
      await act({ repo_id: RID, action: 'unhotfix', pr: 7, head_sha: SHA7 }),
      await act({ repo_id: RID, action: 'release', pr: 8, head_sha: SHA8 }),
    ];
    expect(sent.map((r) => r.status)).toEqual([202, 202]);
    expect(intake(heads).map((r) => r.result)).toEqual(['done', 'done']);
    const s = await apiState();
    expect(sent.map((r) => viewOf(s, idOf(r))?.status)).toEqual(['done', 'done']);
    const queue = coordinatorJson().queue as { pr: number; hotfix: boolean; held: boolean }[];
    expect(queue.map((q) => [q.pr, q.hotfix, q.held])).toEqual([
      [7, false, false],
      [8, false, false],
    ]);
  });

  it('a head that moves after the click is rejected by intake: rejected, head moved', async () => {
    const sent = await act({ repo_id: RID, action: 'hold', pr: 7, head_sha: SHA7 });
    expect(sent.status).toBe(202);
    expect(intake({ 7: MOVED, 8: SHA8 }).map((r) => [r.result, r.reason])).toEqual([['rejected', 'head moved']]);
    const v = viewOf(await apiState(), idOf(sent))!;
    expect([v.status, v.reason]).toEqual(['rejected', 'head moved']);
  });

  it('the server refuses a head it already knows moved, and an approval of a decided item', async () => {
    heads[7] = MOVED;
    await state.refreshAll();
    expect((await act({ repo_id: RID, action: 'hold', pr: 7, head_sha: SHA7 })).body.error).toBe('head_moved');
    heads[7] = SHA7;
    expect((await act({ repo_id: RID, action: 'approve', what: 'overnight agy run' })).body.error).toBe('unknown_item');
  });

  it('a request with no intake for 2 min shows not picked up', async () => {
    const sent = await act({ repo_id: RID, action: 'hold', pr: 8, head_sha: SHA8 });
    expect(sent.status).toBe(202);
    expect(viewOf(await apiState(), idOf(sent))!.status).toBe('requested');
    coordinate('heartbeat', '--repo', RID); // the coordinator is alive, but its intake does not run
    offset = 121_000;
    try {
      const v = viewOf(await apiState(), idOf(sent))!;
      expect([v.status, v.reason]).toEqual(['not_picked_up', 'no coordinator intake for 2 min']);
    } finally {
      offset = 0;
    }
    // The coordinator catches up: the same request ends done.
    expect(intake(heads).map((r) => r.result)).toEqual(['done']);
    expect(viewOf(await apiState(), idOf(sent))!.status).toBe('done');
  });

  it('the hub repo-id rule is exactly the rule of caddis_coordinate.py _repo_dir', () => {
    const ids = ['', '.', '..', 'a/b', 'a\\b', 'a:b', 'con', 'NUL.txt', 'com1', 'com0', 'lpt9.x', 'x.', 'x ', 'a..b',
      'acme__shop', 'local__My Repo__abc123', 'console', 'a.b', 'x+y'];
    const code = [
      'import json, sys',
      `sys.path.insert(0, ${JSON.stringify(SCRIPTS)})`,
      'import caddis_coordinate as c',
      'def ok(i):',
      '    try:',
      '        c._repo_dir(i)',
      '        return True',
      '    except ValueError:',
      '        return False',
      'print(json.dumps([ok(i) for i in json.loads(sys.argv[1])]))',
    ].join('\n');
    const r = py(['-c', code, JSON.stringify(ids)]);
    expect(r.status, r.stderr).toBe(0);
    expect(ids.map((i) => safeRepoId(i))).toEqual(JSON.parse(r.stdout));
  });

  it('after a clean stop the hub shows stopped and refuses actions with the reason', async () => {
    coordinate('lock', 'release', '--repo', RID, '--pid', String(process.pid));
    const s = shop(await apiState());
    expect(s.coordinator!.status).toBe('stopped');
    expect(s.actions.enabled).toBe(false);
    const r = await act({ repo_id: RID, action: 'release', pr: 8, head_sha: SHA8 });
    expect(r.status).toBe(409);
    expect(r.body).toMatchObject({ error: 'no_coordinator' });
    expect(String(r.body.reason)).toContain('stopped');
  });
});
