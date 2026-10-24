import type { Locator, Page } from '@playwright/test';
import { cspViolations, expect, test, type State } from './fixtures';

/**
 * H3 actions in the browser (R41, R43): the buttons, their disabled states, and the request lifecycle. The server is
 * real; its action route is a fake that records each body (the end-to-end write and intake are covered by
 * test/hub/actions.e2e.test.ts).
 */

const SHOP = '#/repo/acme__shop';

/** The shop coordinator in the full fixture, live, with one coordinator ask that has a recommendation. */
function withAsk(s: State): void {
  const shop = s.repos[0];
  shop.owner_items = [
    {
      id: 'ask:ask-1',
      what: 'schema change on prod',
      pr: 214,
      head_sha: 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA214',
      source: 'coordinator',
      recommendation: { decision: 'approve', reason: 'The change is additive.', evidence: 'migration test green; undo: drop the column' },
      from: 'demo-coordinator',
      since: '2026-10-24T10:40:00Z',
    },
  ];
}

const queueItem = (page: Page, pr: number): Locator => page.getByTestId('queue-item').filter({ hasText: `#${pr} ` });

async function noHorizontalScroll(page: Page): Promise<void> {
  const m = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth }));
  expect(m.scroll).toBeLessThanOrEqual(m.client);
}

test.describe('Flow view and the request lifecycle', () => {
  test('the queue shows state, flags and buttons in queue order', async ({ page, openHub }) => {
    const { problems } = await openHub('full', withAsk, SHOP);
    await expect(page.getByTestId('flow-status')).toContainText('Coordinator demo-coordinator live');
    await expect(page.getByTestId('queue-item')).toHaveCount(4);
    await expect(page.getByTestId('queue-item').first()).toContainText('#215');
    await expect(queueItem(page, 215).getByTestId('flag-hotfix')).toBeVisible();
    await expect(queueItem(page, 214).getByTestId('flag-held')).toBeVisible();
    await expect(queueItem(page, 215).getByTestId('act-unhotfix')).toBeEnabled();
    await expect(queueItem(page, 214).getByTestId('act-release')).toBeEnabled();
    await expect(queueItem(page, 213).getByTestId('act-hotfix')).toBeEnabled();
    await expect(page.getByTestId('deploy-check')).toHaveCount(1);
    expect(await cspViolations(page)).toEqual([]);
    expect(problems.console).toEqual([]);
  });

  test('a click is requested, then done', async ({ page, openHub }) => {
    const hub = await openHub('full', withAsk, SHOP);
    await queueItem(page, 213).getByTestId('act-hold').click();
    await expect.poll(() => hub.posted).toEqual([
      { repo_id: 'acme__shop', action: 'hold', pr: 213, head_sha: 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA213' },
    ]);
    const status = queueItem(page, 213).getByTestId('request-status');
    await expect(status).toHaveText('Hold: requested. Waiting for the coordinator.');
    hub.update((s) => {
      const r = s.repos[0].coordinator.requests.at(-1);
      r.status = 'done';
      r.at = '2026-10-24T10:50:40Z';
    });
    await page.clock.fastForward(11_000);
    await expect(status).toHaveText('Hold: done.');
    await expect(page.getByTestId('request-log').first()).toContainText('Hold: done.');
  });

  test('rejected: head moved, and not picked up after 2 min', async ({ page, openHub }) => {
    const hub = await openHub('full', withAsk, SHOP);
    await queueItem(page, 213).getByTestId('act-hotfix').click();
    await queueItem(page, 213).getByTestId('act-hold').click();
    await expect.poll(() => hub.posted.length).toBe(2);
    hub.update((s) => {
      const [hot, hold] = s.repos[0].coordinator.requests.slice(-2);
      Object.assign(hot, { status: 'rejected', reason: 'head moved' });
      Object.assign(hold, { status: 'not_picked_up', reason: 'no coordinator intake for 2 min' });
    });
    await page.clock.fastForward(11_000);
    const lines = queueItem(page, 213).getByTestId('request-status');
    await expect(lines.filter({ hasText: 'Mark hotfix: rejected: head moved.' })).toHaveCount(1);
    await expect(lines.filter({ hasText: 'Hold: not picked up.' })).toHaveCount(1);
  });

  test('a server refusal shows its reason', async ({ page, openHub }) => {
    const hub = await openHub('full', withAsk, SHOP);
    hub.reply(() => ({ status: 409, body: { schema: 1, error: 'head_moved', reason: 'The head of PR #213 moved. Reload and check it again.' } }));
    await queueItem(page, 213).getByTestId('act-hold').click();
    await expect(queueItem(page, 213).getByTestId('request-status')).toHaveText('Hold: refused. The head of PR #213 moved. Reload and check it again.');
  });

  test('owner item: the recommendation with who made it, then Approve posts its what', async ({ page, openHub }) => {
    const hub = await openHub('full', withAsk, SHOP);
    const item = page.getByTestId('owner-item');
    await expect(item.getByTestId('recommendation')).toContainText('Recommendation, from demo-coordinator');
    await expect(item.getByTestId('recommendation')).toContainText('A recommendation is not an approval.');
    await item.getByTestId('act-approve').click();
    await expect.poll(() => hub.posted).toEqual([
      { repo_id: 'acme__shop', action: 'approve', pr: 214, head_sha: 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA214', what: 'schema change on prod' },
    ]);
    await expect(item.getByTestId('request-status')).toHaveText('Approve: requested. Waiting for the coordinator.');
  });
});

test.describe('disabled states (spec 7 rule 7)', () => {
  test('a coordinator that is not responding: greyed queue, buttons disabled with the reason', async ({ page, openHub }) => {
    await openHub('full', undefined, '#/repo/acme__billing');
    await expect(page.getByTestId('flow-status')).toContainText('Coordinator not responding since');
    const item = page.getByTestId('queue-item').first();
    await expect(item.locator('button').first()).toBeDisabled();
    await expect(item.getByTestId('action-reason')).toContainText('not responding');
  });

  test('a clean stop: stopped text, buttons disabled with the reason', async ({ page, openHub }) => {
    await openHub(
      'full',
      (s) => {
        const c = s.repos[0].coordinator;
        Object.assign(c, { status: 'stopped', responding: false, stopped_at: '2026-10-24T10:45:00Z' });
        s.repos[0].actions = { enabled: false, code: 'no_coordinator', reason: 'The coordinator stopped. Start it again with /caddis:coordinate.' };
      },
      SHOP,
    );
    await expect(page.getByTestId('flow-status')).toContainText('Coordinator stopped at');
    await expect(queueItem(page, 213).getByTestId('act-hold')).toBeDisabled();
    await expect(queueItem(page, 213).getByTestId('action-reason')).toHaveText('The coordinator stopped. Start it again with /caddis:coordinate.');
    await page.getByRole('link', { name: 'Overview' }).click();
    await expect(page.getByTestId('lane-summary').filter({ hasText: 'Coordinator stopped at' })).toHaveCount(1);
    await expect(page.getByTestId('lane-summary').filter({ hasText: 'not responding' })).toHaveCount(1); // billing only
  });

  test('no coordinator: the Flow view says so, and an owner gate has Approve disabled with the reason', async ({ page, openHub }) => {
    await openHub('no-coordinator', (s) => {
      // With no coordinator, the asking session's recommendation comes from its relay (D16).
      s.repos[0].owner_items = [
        {
          id: 'gate:docs-plan:P1-OG1',
          what: 'owner gate P1-OG1 (docs-plan)',
          pr: null,
          head_sha: null,
          source: 'relay',
          recommendation: { decision: 'hold', reason: 'Wait for the review.', evidence: null },
          from: 'demo-session',
          since: '2026-10-24T10:30:00Z',
          relay: 'docs-plan',
        },
      ];
    });
    await page.getByTestId('folder-approvals').click();
    await page.getByTestId('inbox-item').first().click();
    const detail = page.getByTestId('inbox-detail');
    await expect(detail.getByTestId('recommendation')).toContainText('Recommendation, from demo-session');
    await expect(detail.getByTestId('recommendation')).toContainText('Hold: Wait for the review.');
    await expect(detail.getByTestId('act-approve')).toBeDisabled();
    await expect(detail.getByTestId('action-reason')).toContainText('No coordinator: each session merges its own PRs.');
    await page.evaluate(() => {
      window.location.hash = '#/repo/acme__docs';
    });
    await expect(page.getByTestId('flow-status')).toContainText('No coordinator');
    await expect(page.getByTestId('unqueued-pr')).toHaveCount(1);
  });
});

test.describe('Inbox and Overview buttons', () => {
  test('Inbox: a blocked queued PR gets Hold; the approval shows its recommendation', async ({ page, openHub }) => {
    const hub = await openHub('full', withAsk);
    await page.getByTestId('folder-blocked').click();
    await page.getByTestId('inbox-item').filter({ hasText: 'PR #212' }).first().click();
    await page.getByTestId('inbox-detail').getByTestId('act-hold').click();
    await expect.poll(() => hub.posted.map((b) => [b.action, b.pr])).toEqual([['hold', 212]]);
    await page.getByTestId('folder-approvals').click();
    await page.getByTestId('inbox-item').filter({ hasText: 'schema change on prod' }).click();
    await expect(page.getByTestId('inbox-detail').getByTestId('recommendation')).toContainText('The change is additive.');
  });

  test('Overview: queue cards have compact buttons', async ({ page, openHub }) => {
    const hub = await openHub('full', undefined, '#/overview');
    const card = page.getByTestId('lane-card').filter({ hasText: '#213' });
    await card.getByTestId('act-hotfix').click();
    await expect.poll(() => hub.posted.map((b) => [b.action, b.pr])).toEqual([['hotfix', 213]]);
    await expect(card.getByTestId('request-status')).toContainText('requested');
  });

  test('the footer shows GitHub quota left', async ({ page, openHub }) => {
    await openHub('full', (s) => {
      s.github_rate = { demo: { remaining: 4321, reset_at: null } };
    });
    await expect(page.getByTestId('quota')).toHaveText('GitHub quota 4321 left (demo)');
  });
});

test.describe('360 px', () => {
  test.use({ viewport: { width: 360, height: 740 } });

  test('the Flow view with an owner item and request lines fits', async ({ page, openHub }) => {
    const hub = await openHub('full', withAsk, SHOP);
    await queueItem(page, 213).getByTestId('act-hold').click();
    await expect.poll(() => hub.posted.length).toBe(1);
    await expect(queueItem(page, 213).getByTestId('request-status')).toBeVisible();
    await noHorizontalScroll(page);
    await page.getByRole('button', { name: 'Open navigation menu' }).click();
    await page.getByRole('link', { name: 'Overview' }).click();
    await expect(page.getByTestId('lane').first()).toBeVisible();
    await noHorizontalScroll(page);
  });
});
