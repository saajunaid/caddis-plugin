import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  accountCandidates,
  createGithubSource,
  parseAuthStatus,
  parseGithubRemote,
  readRequiredChecks,
  requiredState,
  type FetchFn,
} from '../../src/hub/sources/github.js';

let dir: string;
beforeEach(() => {
  dir = mkdtempSync(path.join(tmpdir(), 'caddis-hub-'));
});
afterEach(() => {
  rmSync(dir, { recursive: true, force: true });
});

function repo(name: string, remote: string | null, coordinator?: string): string {
  const root = path.join(dir, name);
  mkdirSync(path.join(root, '.git'), { recursive: true });
  const cfg = remote
    ? `[remote "origin"]\n\turl = ${remote}\n\tfetch = +refs/heads/*:refs/remotes/origin/*\n`
    : '[core]\n\tbare = false\n';
  writeFileSync(path.join(root, '.git', 'config'), cfg);
  if (coordinator !== undefined) {
    mkdirSync(path.join(root, '.caddis'), { recursive: true });
    writeFileSync(path.join(root, '.caddis', 'coordinator.md'), coordinator);
  }
  return root;
}

const COORD =
  'Notes\n\n```json\n{"schema":1,"required_checks":["build","test"],"merge_method":"squash"}\n```\n\n```json\n{"required_checks":["other"]}\n```\n';

// Recorded REST responses (sample names).
const OPEN_PULLS = [
  {
    number: 7,
    title: 'Add cart',
    draft: false,
    updated_at: '2026-10-24T09:00:00Z',
    html_url: 'https://github.com/acme/shop/pull/7',
    user: { login: 'dev1' },
    head: { sha: 'aaa111' },
  },
];
const CHECKS = {
  total_count: 3,
  check_runs: [
    { name: 'build', status: 'completed', conclusion: 'success' },
    { name: 'test', status: 'in_progress', conclusion: null },
    { name: 'lint', status: 'completed', conclusion: 'failure' },
  ],
};
const CLOSED_PULLS = [
  { number: 5, title: 'Old', merged_at: null, merge_commit_sha: null },
  { number: 6, title: 'Fix totals', merged_at: '2026-10-23T08:00:00Z', merge_commit_sha: 'bbb222' },
  { number: 4, title: 'Add tax', merged_at: '2026-10-22T08:00:00Z', merge_commit_sha: 'ccc333' },
];
const RUNS = {
  workflow_runs: [
    { name: 'deploy', status: 'completed', conclusion: 'success', html_url: 'https://github.com/acme/shop/actions/runs/1' },
  ],
};

const routes: Record<string, unknown> = {
  '/repos/acme/shop/pulls?state=open&per_page=50': OPEN_PULLS,
  '/repos/acme/shop/commits/aaa111/check-runs?per_page=100': CHECKS,
  '/repos/acme/shop/pulls?state=closed&sort=updated&direction=desc&per_page=20': CLOSED_PULLS,
  '/repos/acme/shop/actions/runs?head_sha=bbb222&per_page=10': RUNS,
  '/repos/acme/shop/actions/runs?head_sha=ccc333&per_page=10': { workflow_runs: [] },
};

interface Call {
  url: string;
  headers: Record<string, string>;
}
function fakeFetch(calls: Call[], extra: Record<string, number> = {}, remaining = '4999'): FetchFn {
  return async (url, init) => {
    const p = url.replace('https://api.github.com', '');
    calls.push({ url: p, headers: init.headers });
    const repoName = /^\/repos\/([^/]+\/[^/]+)/.exec(p)?.[1] ?? '';
    const status = extra[repoName];
    const rl = { 'x-ratelimit-remaining': remaining, 'x-ratelimit-reset': '1792000000' };
    if (status) return new Response('{"message":"Bad credentials"}', { status, headers: rl });
    const body = routes[p];
    if (body === undefined) return new Response('{}', { status: 404, headers: rl });
    const etag = `"etag-${p.length}"`;
    if (init.headers['If-None-Match'] === etag) return new Response(null, { status: 304, headers: rl });
    return new Response(JSON.stringify(body), { status: 200, headers: { ...rl, etag } });
  };
}

const mk = (repos: string[], f: FetchFn, accounts: Record<string, string> = {}, extra = {}) =>
  createGithubSource({
    repos: () => repos,
    accounts: () => accounts,
    fetch: f,
    getToken: async (a) => `tok-${a}`,
    now: () => Date.parse('2026-10-24T10:00:00Z'),
    ...extra,
  });

describe('helpers', () => {
  it('parses GitHub remotes', () => {
    expect(parseGithubRemote('https://github.com/acme/shop.git')).toBe('acme/shop');
    expect(parseGithubRemote('git@github.com:acme/shop.git')).toBe('acme/shop');
    expect(parseGithubRemote('ssh://git@github.com/acme/shop')).toBe('acme/shop');
    expect(parseGithubRemote('https://gitea.example/acme/shop.git')).toBeNull();
  });
  it('reads required_checks from the first json block only', () => {
    expect(readRequiredChecks(repo('a', null, COORD))).toEqual(['build', 'test']);
    expect(readRequiredChecks(repo('b', null, '```json\n{bad\n```'))).toBeNull();
    expect(readRequiredChecks(repo('c', null, '```json\n{"required_checks":"x"}\n```'))).toBeNull();
    expect(readRequiredChecks(repo('d', null))).toBeNull();
  });
  it('computes required state', () => {
    const c = (name: string, status: string, conclusion: string | null) => ({ name, status, conclusion, required: true });
    expect(requiredState([c('a', 'completed', 'success')], ['a'])).toBe('pass');
    expect(requiredState([c('a', 'completed', 'failure')], ['a'])).toBe('fail');
    expect(requiredState([c('a', 'in_progress', null)], ['a'])).toBe('pending');
    expect(requiredState([], ['a'])).toBe('pending');
    expect(requiredState([], null)).toBe('unknown');
  });
});

describe('github source', () => {
  it('builds PRs with required checks and merges with deploy runs', async () => {
    const root = repo('shop', 'https://github.com/acme/shop.git', COORD);
    const calls: Call[] = [];
    const src = mk([root], fakeFetch(calls));
    await src.refresh();
    const s = src.get();
    expect(s.ok).toBe(true);
    const slot = s.data!.repos[0]!;
    expect(slot).toMatchObject({ repo: 'acme/shop', account: 'acme' });
    expect(slot.prs![0]).toMatchObject({ number: 7, head_sha: 'aaa111', author: 'dev1', draft: false, required_state: 'pending' });
    expect(slot.prs![0]!.checks).toEqual([
      { name: 'build', status: 'completed', conclusion: 'success', required: true },
      { name: 'test', status: 'in_progress', conclusion: null, required: true },
      { name: 'lint', status: 'completed', conclusion: 'failure', required: false },
    ]);
    expect(slot.merges!.map((m) => m.number)).toEqual([6, 4]);
    expect(slot.merges![0]).toEqual({
      number: 6,
      title: 'Fix totals',
      merge_sha: 'bbb222',
      merged_at: '2026-10-23T08:00:00Z',
      runs: [{ name: 'deploy', status: 'completed', conclusion: 'success', url: 'https://github.com/acme/shop/actions/runs/1' }],
    });
    expect(s.data!.rate.acme).toEqual({ remaining: 4999, reset_at: new Date(1792000000 * 1000).toISOString() });
    expect(calls[0]!.headers).toMatchObject({
      Authorization: 'Bearer tok-acme',
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      'User-Agent': 'caddis-hub',
    });
    expect(JSON.stringify(s)).not.toContain('tok-acme');
  });

  it('sends If-None-Match on the second run and reuses the body on 304', async () => {
    const root = repo('shop', 'git@github.com:acme/shop.git', COORD);
    const calls: Call[] = [];
    const src = mk([root], fakeFetch(calls));
    await src.refresh();
    const first = JSON.stringify(src.get().data);
    const n = calls.length;
    expect(calls.every((c) => c.headers['If-None-Match'] === undefined)).toBe(true);
    await src.refresh();
    const second = calls.slice(n);
    expect(second.length).toBe(n);
    expect(second.every((c) => c.headers['If-None-Match'])).toBe(true);
    expect(JSON.stringify(src.get().data)).toBe(first);
  });

  it('marks checks required: null without coordinator.md', async () => {
    const root = repo('shop', 'https://github.com/acme/shop', undefined);
    const src = mk([root], fakeFetch([]));
    await src.refresh();
    const pr = src.get().data!.repos[0]!.prs![0]!;
    expect(pr.required_state).toBe('unknown');
    expect(pr.checks.every((c) => c.required === null)).toBe(true);
  });

  it('skips a repo with no github remote', async () => {
    const a = repo('local', null);
    const b = repo('other', 'https://gitea.example/x/y.git');
    const src = mk([a, b], fakeFetch([]));
    await src.refresh();
    expect(src.get().data!.repos.map((r) => r.reason)).toEqual(['no github remote', 'no github remote']);
  });

  it('shows the auth message for a 401 repo and leaves others alone', async () => {
    const good = repo('shop', 'https://github.com/acme/shop.git', COORD);
    const bad = repo('vault', 'https://github.com/zed/vault.git');
    const src = mk([bad, good], fakeFetch([], { 'zed/vault': 401 }), { zed: 'zed-work' });
    await src.refresh();
    const [b, g] = src.get().data!.repos;
    expect(b!.error).toBe(
      'no access with account zed-work: run gh auth login -h github.com, or set "accounts": {"zed": "<gh user>"} in ~/.caddis/hub/config.json',
    );
    expect(g!.prs).toHaveLength(1);
  });

  it('picks the account: exact repo, then owner, then remote owner', async () => {
    const root = repo('shop', 'https://github.com/acme/shop.git');
    const tokens: string[] = [];
    const mkWith = (accounts: Record<string, string>) =>
      createGithubSource({
        repos: () => [root],
        accounts: () => accounts,
        fetch: fakeFetch([]),
        getToken: async (a) => {
          tokens.push(a);
          return 't';
        },
      });
    await mkWith({ 'acme/shop': 'one', acme: 'two' }).refresh();
    await mkWith({ acme: 'two' }).refresh();
    await mkWith({}).refresh();
    expect(tokens).toEqual(['one', 'two', 'acme']);
  });

  it('treats a missing token as an auth error', async () => {
    const root = repo('shop', 'https://github.com/acme/shop.git');
    const src = mk([root], fakeFetch([]), {}, { getToken: async () => null });
    await src.refresh();
    expect(src.get().data!.repos[0]!.error).toContain('no access with account acme: run gh auth login -h github.com');
  });

  it('slows the poll below the rate reserve', async () => {
    const root = repo('shop', 'https://github.com/acme/shop.git');
    const fast = mk([root], fakeFetch([], {}, '4000'));
    await fast.refresh();
    expect(fast.nextDelayMs()).toBe(60_000);
    const slow = mk([root], fakeFetch([], {}, '499'));
    await slow.refresh();
    expect(slow.nextDelayMs()).toBe(300_000);
    expect(slow.get().data!.rate.acme!.remaining).toBe(499);
  });

  it('keeps the last good data on a rate limit, and does not call it an auth error', async () => {
    const root = repo('shop', 'https://github.com/acme/shop.git', COORD);
    let limited = false;
    const inner = fakeFetch([]);
    const f: FetchFn = async (url, init) =>
      limited ? new Response('{}', { status: 403, headers: { 'x-ratelimit-remaining': '0' } }) : inner(url, init);
    const src = mk([root], f);
    await src.refresh();
    limited = true;
    await src.refresh();
    const s = src.get();
    expect(s.ok).toBe(false);
    expect(s.last_error).toContain('rate limit');
    expect(s.data!.repos[0]!.prs).toHaveLength(1);
    expect(s.data!.repos[0]!.error).toBeUndefined();
  });
  it('evicts the ETag key of an old head SHA after the head changes', async () => {
    const root = repo('shop', 'https://github.com/acme/shop.git', COORD);
    const calls: Call[] = [];
    const local = { ...routes } as Record<string, unknown>;
    let head = 'aaa111';
    const f: FetchFn = async (url, init) => {
      const p = url.replace('https://api.github.com', '');
      calls.push({ url: p, headers: init.headers });
      let body = local[p];
      if (p.includes('state=open')) body = [{ ...OPEN_PULLS[0]!, head: { sha: head } }];
      if (p.includes('/commits/')) body = CHECKS;
      if (body === undefined) return new Response('{}', { status: 404 });
      return new Response(JSON.stringify(body), { status: 200, headers: { etag: `"e-${p}"` } });
    };
    const src = mk([root], f);
    await src.refresh();
    head = 'ddd444';
    await src.refresh();
    calls.length = 0;
    head = 'aaa111';
    await src.refresh();
    const old = calls.find((c) => c.url.includes('/commits/aaa111/'));
    expect(old).toBeDefined();
    expect(old!.headers['If-None-Match']).toBeUndefined();
    const kept = calls.find((c) => c.url.includes('state=open'));
    expect(kept!.headers['If-None-Match']).toBeTruthy();
  });

  it('stops calling the other repos of an account after a rate limit', async () => {
    const a = repo('shop', 'https://github.com/acme/shop.git');
    const b = repo('blog', 'https://github.com/acme/blog.git');
    const c = repo('other', 'https://github.com/zed/thing.git');
    const calls: Call[] = [];
    const f: FetchFn = async (url, init) => {
      const p = url.replace('https://api.github.com', '');
      calls.push({ url: p, headers: init.headers });
      if (p.startsWith('/repos/acme/')) return new Response('{}', { status: 403, headers: { 'x-ratelimit-remaining': '0' } });
      return new Response('[]', { status: 200 });
    };
    const src = mk([a, b, c], f);
    await src.refresh();
    expect(calls.filter((x) => x.url.startsWith('/repos/acme/blog'))).toHaveLength(0);
    expect(calls.filter((x) => x.url.startsWith('/repos/acme/shop'))).toHaveLength(1);
    expect(calls.some((x) => x.url.startsWith('/repos/zed/thing'))).toBe(true);
  });

  it('takes the auth-error path for a 403 that is not a rate limit', async () => {
    const root = repo('shop', 'https://github.com/acme/shop.git');
    const f: FetchFn = async () => new Response('{}', { status: 403, headers: { 'x-ratelimit-remaining': '10' } });
    const src = mk([root], f);
    await src.refresh();
    const slot = src.get().data!.repos[0]!;
    expect(slot.error).toContain('gh auth login');
  });

  it('treats a 304 with no cached copy as an error and keeps last good data', async () => {
    const root = repo('shop', 'https://github.com/acme/shop.git', COORD);
    const inner = fakeFetch([]);
    let bad = false;
    const f: FetchFn = async (url, init) => (bad ? new Response(null, { status: 304 }) : inner(url, init));
    const src = mk([root], f);
    await src.refresh();
    bad = true;
    // A fresh source has no cache: first run answers 304 for every URL.
    const fresh = mk([root], f);
    await fresh.refresh();
    expect(fresh.get().ok).toBe(false);
    expect(fresh.get().last_error).toContain('304');
    expect(src.get().data!.repos[0]!.prs).toHaveLength(1);
  });

  it('keeps the later run when check names repeat', async () => {
    const root = repo('shop', 'https://github.com/acme/shop.git');
    const f: FetchFn = async (url) => {
      const p = url.replace('https://api.github.com', '');
      if (p.includes('state=open')) return new Response(JSON.stringify(OPEN_PULLS), { status: 200 });
      if (p.includes('/commits/'))
        return new Response(
          JSON.stringify({
            check_runs: [
              { name: 'build', status: 'completed', conclusion: 'failure' },
              { name: 'build', status: 'completed', conclusion: 'success' },
            ],
          }),
          { status: 200 },
        );
      return new Response('[]', { status: 200 });
    };
    const src = mk([root], f);
    await src.refresh();
    expect(src.get().data!.repos[0]!.prs![0]!.checks).toEqual([
      { name: 'build', status: 'completed', conclusion: 'success', required: null },
    ]);
  });
});

describe('time limits (final review must-fix 2)', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('passes an abort signal to every request', async () => {
    const root = repo('shop', 'https://github.com/acme/shop.git', COORD);
    const signals: unknown[] = [];
    const inner = fakeFetch([]);
    const f: FetchFn = async (url, init) => {
      signals.push(init.signal);
      return inner(url, init);
    };
    await mk([root], f).refresh();
    expect(signals.length).toBeGreaterThan(0);
    expect(signals.every((x) => x instanceof AbortSignal)).toBe(true);
  });

  it('ends a run whose request never settles, and the next refresh starts a new run', async () => {
    vi.useFakeTimers();
    const root = repo('shop', 'https://github.com/acme/shop.git');
    let calls = 0;
    const f: FetchFn = () => {
      calls += 1;
      return new Promise<Response>(() => {});
    };
    const src = mk([root], f);
    const first = src.refresh();
    await vi.advanceTimersByTimeAsync(16_000);
    await first;
    expect(src.get().last_error).toContain('GitHub request did not finish in 16 s');
    void src.refresh();
    await vi.advanceTimersByTimeAsync(0);
    expect(calls).toBe(2);
  });

  it('ends a run whose token read never settles', async () => {
    vi.useFakeTimers();
    const root = repo('shop', 'https://github.com/acme/shop.git');
    const src = mk([root], fakeFetch([]), {}, { getToken: () => new Promise<string | null>(() => {}) });
    const first = src.refresh();
    await vi.advanceTimersByTimeAsync(15_000);
    await first;
    expect(src.get().last_error).toContain('gh auth token did not finish');
  });
});

describe('access errors and per-repo age (final review I3)', () => {
  it('treats a 404 on the first call as an access error, not a source error', async () => {
    const good = repo('shop', 'https://github.com/acme/shop.git', COORD);
    const hidden = repo('vault', 'https://github.com/zed/vault.git');
    const src = mk([hidden, good], fakeFetch([], { 'zed/vault': 404 }));
    await src.refresh();
    const s = src.get();
    expect(s.ok).toBe(true);
    expect(s.last_error).toBeNull();
    expect(s.data!.repos[0]!.error).toContain('no access with account zed');
    expect(s.data!.repos[1]!.prs).toHaveLength(1);
  });

  it('keeps the source fresh when one repo keeps failing; that repo shows its own age', async () => {
    const good = repo('shop', 'https://github.com/acme/shop.git', COORD);
    const flaky = repo('blog', 'https://github.com/zed/blog.git');
    let clock = Date.parse('2026-10-24T10:00:00Z');
    let broken = false;
    const inner = fakeFetch([]);
    const f: FetchFn = async (url, init) => {
      if (url.includes('/repos/zed/blog/')) {
        return broken ? new Response('{}', { status: 500 }) : new Response('[]', { status: 200 });
      }
      return inner(url, init);
    };
    const src = mk([good, flaky], f, {}, { now: () => clock });
    await src.refresh();
    const firstOk = new Date(clock).toISOString();
    broken = true;
    for (let i = 0; i < 4; i += 1) {
      clock += 60_000;
      await src.refresh();
    }
    const s = src.get();
    expect(s.stale).toBe(false);
    expect(s.ok).toBe(false);
    const [g, b] = s.data!.repos;
    expect(g!.last_ok_at).toBe(new Date(clock).toISOString());
    expect(b!.last_ok_at).toBe(firstOk);
    expect(b!.error).toBe('GitHub answered 500');
    expect(b!.prs).toEqual([]);
  });

  it('goes stale when every repo fails', async () => {
    const root = repo('shop', 'https://github.com/acme/shop.git');
    let clock = Date.parse('2026-10-24T10:00:00Z');
    const src = mk([root], async () => new Response('{}', { status: 500 }), {}, { now: () => clock });
    await src.refresh();
    clock += 4 * 60_000;
    await src.refresh();
    expect(src.get().stale).toBe(true);
  });
});

describe('account discovery (final review I4)', () => {
  const STATUS_NEW = [
    'github.com',
    '  ✓ Logged in to github.com account dev-personal (keyring)',
    '  - Active account: false',
    '  - Git operations protocol: https',
    '  - Token: gho_************************************',
    '',
    '  ✓ Logged in to github.com account dev-work (keyring)',
    '  - Active account: true',
    '  - Token: gho_************************************',
    'ghe.example',
    '  ✓ Logged in to ghe.example account other (keyring)',
    '  - Active account: true',
  ].join('\n');

  it('parses gh auth status, new and old formats', () => {
    expect(parseAuthStatus(STATUS_NEW)).toEqual({ active: 'dev-work', accounts: ['dev-personal', 'dev-work'] });
    expect(parseAuthStatus('github.com\n  ✓ Logged in to github.com as dev-old (oauth_token)\n')).toEqual({
      active: 'dev-old',
      accounts: ['dev-old'],
    });
    expect(parseAuthStatus('You are not logged into any GitHub hosts.')).toEqual({ active: null, accounts: [] });
  });

  it('orders the candidates: known, remote owner if logged in, active, then the others', () => {
    const st = { active: 'dev-work', accounts: ['dev-personal', 'dev-work', 'acme'] };
    expect(accountCandidates('acme', st)).toEqual(['acme', 'dev-work', 'dev-personal']);
    expect(accountCandidates('org-x', st)).toEqual(['dev-work', 'dev-personal', 'acme']);
    expect(accountCandidates('org-x', st, 'dev-personal')).toEqual(['dev-personal', 'dev-work', 'acme']);
    expect(accountCandidates('org-x', null)).toEqual(['org-x']);
  });

  function orgRepo() {
    const root = repo('shop', 'https://github.com/acme-org/shop.git', COORD);
    const local: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(routes)) local[k.replace('/repos/acme/shop/', '/repos/acme-org/shop/')] = v;
    const used: string[] = [];
    // Only dev-personal can see the org repo; dev-work gets 404, as GitHub answers for a hidden private repo.
    const f: FetchFn = async (url, init) => {
      const p = url.replace('https://api.github.com', '');
      const who = (init.headers.Authorization ?? '').replace('Bearer tok-', '');
      used.push(`${who} ${p.split('?')[0]}`);
      if (who !== 'dev-personal') return new Response('{"message":"Not Found"}', { status: 404 });
      const body = local[p];
      return body === undefined ? new Response('{}', { status: 404 }) : new Response(JSON.stringify(body), { status: 200 });
    };
    return { root, f, used };
  }

  it('falls back from an org owner to the active account, then the others, and keeps the one that works', async () => {
    const { root, f, used } = orgRepo();
    const tokens: string[] = [];
    let statusCalls = 0;
    const src = mk([root], f, {}, {
      getToken: async (a: string) => {
        tokens.push(a);
        return `tok-${a}`;
      },
      authStatus: async () => {
        statusCalls += 1;
        return parseAuthStatus(STATUS_NEW);
      },
    });
    await src.refresh();
    const slot = src.get().data!.repos[0]!;
    expect(slot.account).toBe('dev-personal');
    expect(slot.prs).toHaveLength(1);
    expect(tokens).toEqual(['dev-work', 'dev-personal']); // never `-u acme-org`: an org is not a gh account
    used.length = 0;
    await src.refresh();
    expect(used[0]).toBe('dev-personal /repos/acme-org/shop/pulls'); // the kept account goes first
    expect(statusCalls).toBe(2); // once per run
  });

  it('uses the config override alone, and names the config fix when no account can see the repo', async () => {
    const { root, f } = orgRepo();
    const tried: string[] = [];
    const src = mk([root], f, { 'acme-org': 'dev-work' }, {
      getToken: async (a: string) => {
        tried.push(a);
        return `tok-${a}`;
      },
      authStatus: async () => parseAuthStatus(STATUS_NEW),
    });
    await src.refresh();
    expect(tried).toEqual(['dev-work']);
    expect(src.get().data!.repos[0]!.error).toBe(
      'no access with account dev-work: run gh auth login -h github.com, or set "accounts": {"acme-org": "<gh user>"} in ~/.caddis/hub/config.json',
    );
  });

  it('says so when no gh account is logged in', async () => {
    const { root, f } = orgRepo();
    const src = mk([root], f, {}, { authStatus: async () => ({ active: null, accounts: [] }) });
    await src.refresh();
    expect(src.get().data!.repos[0]!.error).toBe(
      'no gh account is logged in: run gh auth login -h github.com, then set "accounts": {"acme-org": "<gh user>"} in ~/.caddis/hub/config.json',
    );
  });
});
