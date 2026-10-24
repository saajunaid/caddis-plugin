import { randomBytes } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { expect, test as base, type Page } from '@playwright/test';
import { startServer, type HubServer } from '../src/hub/server';

export type FixtureName = 'full' | 'empty' | 'no-coordinator' | 'degraded';
// A fixture is plain JSON. Tests change it in place before or after sign-in.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type State = Record<string, any>;

/** The page clock starts here: the fixtures hold times relative to their `generated_at`. */
export const NOW = '2026-10-24T10:50:30Z';

export const loadFixture = (name: FixtureName): State =>
  JSON.parse(readFileSync(fileURLToPath(new URL(`../test/fixtures/hub-state/${name}.json`, import.meta.url)), 'utf8')) as State;

export interface Problems {
  console: string[];
}

export interface ActionReply {
  status: number;
  body: Record<string, unknown>;
}
export interface Hub {
  port: number;
  problems: Problems;
  /** Change the state the server returns from now on. */
  update: (change: (s: State) => void) => void;
  /** Every body the page posted to /api/actions. */
  posted: Record<string, unknown>[];
  /** Set how the fake action route answers. The default accepts and adds a `requested` view to the state. */
  reply: (fn: (body: Record<string, unknown>, s: State) => ActionReply) => void;
}

let requestNo = 0;
/** The default fake action route: accept, and show the request as `requested` in its repo (R38). */
export function acceptAction(body: Record<string, unknown>, s: State): ActionReply {
  const id = `req-${++requestNo}`;
  const repo = s.repos.find((r: State) => r.repo_id === body.repo_id);
  repo?.coordinator?.requests?.push({
    id,
    action: body.action,
    pr: body.pr ?? null,
    head_sha: body.head_sha ?? null,
    what: body.what ?? null,
    created_at: NOW,
    expires_at: null,
    status: 'requested',
    reason: null,
    at: null,
  });
  return { status: 202, body: { schema: 1, request: { id, created_at: NOW } } };
}

interface Fixtures {
  /** Start a hub on port 0 with a fixture state (optionally changed), sign in, and open the page. */
  openHub: (name: FixtureName, tweak?: (s: State) => void, hash?: string) => Promise<Hub>;
}

const KEY_HEADER = 'x-caddis-hub-key';

export const test = base.extend<Fixtures>({
  openHub: async ({ page }, use) => {
    const servers: HubServer[] = [];
    await use(async (name, tweak, hash = '') => {
      const state = loadFixture(name);
      tweak?.(state);
      const key = randomBytes(32).toString('hex');
      const posted: Record<string, unknown>[] = [];
      let answer: (body: Record<string, unknown>, s: State) => ActionReply = acceptAction;
      const srv = await startServer({
        port: 0,
        key,
        getState: () => state,
        versions: { hub: '0.0.0-e2e' },
        actions: {
          submit: async (body) => {
            posted.push(body as Record<string, unknown>);
            return answer(body as Record<string, unknown>, state);
          },
        },
      });
      servers.push(srv);
      const problems = watch(page);
      await page.clock.install({ time: new Date(NOW) });
      // Mint a one-time login code the way `caddis hub open` does: a POST with the key header.
      const res = await fetch(`http://127.0.0.1:${srv.port}/api/hub/code`, { method: 'POST', headers: { [KEY_HEADER]: key } });
      const { code } = (await res.json()) as { code: string };
      // /login answers 303 to `/#tab=<token>`, and the page captures the token.
      await page.goto(`http://127.0.0.1:${srv.port}/login?code=${code}`);
      await expect(page.getByTestId('data-age')).toContainText('Updated');
      if (hash) {
        await page.evaluate((h) => {
          window.location.hash = h;
        }, hash);
      }
      return {
        port: srv.port,
        problems,
        update: (change) => change(state),
        posted,
        reply: (fn) => {
          answer = fn;
        },
      };
    });
    for (const s of servers) await s.close();
  },
});

function watch(page: Page): Problems {
  const problems: Problems = { console: [] };
  page.on('console', (m) => {
    if (m.type() === 'error') problems.console.push(m.text());
  });
  page.on('pageerror', (e) => problems.console.push(String(e)));
  void page.addInitScript(() => {
    const w = window as unknown as { __csp?: string[] };
    document.addEventListener('securitypolicyviolation', (e) => {
      (w.__csp ??= []).push(`${e.violatedDirective} ${e.blockedURI}`);
    });
  });
  return problems;
}

export async function cspViolations(page: Page): Promise<string[]> {
  return page.evaluate(() => (window as unknown as { __csp?: string[] }).__csp ?? []);
}

export { expect };
