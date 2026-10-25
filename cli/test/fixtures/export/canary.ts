import { spawnSync } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';

/**
 * A canary git fixture for the Pages export tests (H6.5, H6.6). The repo, the machine and CADDIS_HOME hold planted
 * private values. Every name is a sample. Tests build it in a temp folder (prefix `caddis-hub-`) and remove it.
 */
export const CANARY = {
  runnerHost: 'sample-runner-host-77',
  lockHost: 'sample-lock-host-88',
  lockPid: '424242',
  session: 'sample-session-canary-zz',
  prompt: 'sample-resume-prompt-canary-zz',
  coordinator: 'sample-coordinator-canary-zz',
  home: 'sample-home-canary-zz',
};
export const MACHINE = { user: 'sample-user', host: 'sample-box-01' };
export const SHA40 = 'abcdef0123456789'.repeat(3).slice(0, 40);

export const git = (cwd: string, ...args: string[]): void => {
  const r = spawnSync('git', ['-C', cwd, ...args], { stdio: 'ignore' });
  if (r.status !== 0) throw new Error(`git ${args[0]} failed`);
};
export const put = (file: string, text: string): void => {
  mkdirSync(path.dirname(file), { recursive: true });
  writeFileSync(file, text);
};

export const roadmapText = (blockerReason: string, phaseName: string): string =>
  `# launch roadmap\n\nRunner host: ${CANARY.runnerHost}\n\n## Milestones\n` +
  `| ID | Milestone | Phases | Depends on | Exit check | Status | Owner | Target |\n|---|---|---|---|---|---|---|---|\n` +
  `| S1 | Catalog loads | p-shop#1, p-shop#2 | - | \`python check_s1.py\` | in-progress | runner | WD3 |\n` +
  `| S2 | Checkout works | p-shop#3 | S1 | \`python check_s2.py\` | todo | runner | WD4 |\n\n` +
  `## Blockers\n| Milestone | Type | Reason | Check |\n|---|---|---|---|\n| S2 | owner-gate | ${blockerReason} | |\n`;

const planText = (phaseName: string): string =>
  `---\ntype: plan\nstatus: active\ntitle: p-shop sample plan\n---\n\n# p-shop\n\n### Phase 1 - ${phaseName}\n**Lane:** claude - the roadmap runner\n` +
  `### Phase 2 - Show the catalog\n**Lane:** claude - the roadmap runner\n### Phase 3 - Check out\n**Lane:** claude - the roadmap runner\n\n` +
  `## Tracker\n| Phase | Milestone | Status | Commit | Notes |\n|---|---|---|---|---|\n` +
  `| 1 | S1 | done #11 | abc1234 | |\n| 2 | S1 | in progress | - | |\n| 3 | S2 | not started | - | |\n`;

export interface Fixture {
  repo: string;
  home: string;
}

/** A git checkout with an origin, one roadmap, one plan, planted private files and a runner lock. */
export function makeRepo(base: string, opts: { blockerReason?: string; phaseName?: string; name?: string } = {}): Fixture {
  const repo = path.join(base, opts.name ?? 'sample-shop');
  const origin = path.join(base, `${opts.name ?? 'sample-shop'}.origin.git`);
  const reason = opts.blockerReason ?? 'owner signs off the catalog';
  const phase = opts.phaseName ?? 'Load the catalog';
  put(path.join(repo, '.caddis', 'roadmaps', 'launch', 'roadmap.md'), roadmapText(reason, phase));
  put(path.join(repo, '.caddis', 'plans', 'p-shop.md'), planText(phase));
  put(path.join(repo, '.caddis', 'relay', 'demo-session.md'), `---\ntype: relay\nsession_id: ${CANARY.session}\n---\n\n## Resume prompt\n${CANARY.prompt}\n\nSTATUS: CONTINUE\n`);
  put(path.join(repo, '.caddis', 'coordinator.md'), `# coordinator\n${CANARY.coordinator}\n`);
  mkdirSync(origin, { recursive: true });
  git(base, 'init', '-q', '--bare', '-b', 'main', origin);
  git(repo, 'init', '-q', '-b', 'main');
  for (const [k, v] of [['user.email', 'test@example.invalid'], ['user.name', 'test'], ['commit.gpgsign', 'false']] as const) git(repo, 'config', k, v);
  git(repo, 'add', '-A');
  git(repo, 'commit', '-q', '-m', 'fixture');
  git(repo, 'remote', 'add', 'origin', origin);
  git(repo, 'push', '-q', '-u', 'origin', 'main');
  git(repo, 'remote', 'set-head', 'origin', 'main');
  put(
    path.join(repo, '.git', 'caddis-runner', 'roadmap-launch', 'runner.lock'),
    JSON.stringify({ batch: 'S1', pid: Number(CANARY.lockPid), host: CANARY.lockHost, started_utc: '2026-10-24T09:00:00Z', max_hours: 1 }),
  );
  const home = path.join(base, 'sample-caddis-home');
  put(path.join(home, '.caddis', 'hub', 'repos', 'x', 'coordinator.json'), JSON.stringify({ note: CANARY.home }));
  put(path.join(home, '.caddis', 'hub', 'audit.jsonl'), `{"note":"${CANARY.home}"}\n`);
  put(path.join(home, '.caddis', 'spend', 'log.jsonl'), `{"cap_eur":${CANARY.home.length},"note":"${CANARY.home}"}\n`);
  return { repo, home };
}

/** A built app stand-in: the placeholder, one asset, one font, the licences, and files that must NOT be copied. */
export function makeDist(base: string): string {
  const dist = path.join(base, 'dist-export');
  put(path.join(dist, 'index.html'), '<!doctype html><html><head><meta charset="utf-8"></head><body><div id="root"></div>\n  <!--caddis-export-data-->\n</body></html>\n');
  put(path.join(dist, 'assets', 'app-1.js'), 'console.log("app");\n');
  put(path.join(dist, 'assets', 'app-1.css'), 'body{margin:0}\n');
  mkdirSync(path.join(dist, 'fonts'), { recursive: true });
  writeFileSync(path.join(dist, 'fonts', 'sample-400.abc.woff2'), Buffer.from('wOF2....'));
  put(path.join(dist, 'fonts', 'OFL-Atkinson.txt'), 'OFL sample\n');
  put(path.join(dist, 'fonts', 'OFL-MapleMono.txt'), 'OFL sample\n');
  put(path.join(dist, 'fonts', 'LICENSE-Lucide.txt'), 'ISC sample\n');
  put(path.join(dist, 'fonts', 'notes.txt'), 'must not be copied\n');
  put(path.join(dist, 'assets', 'nested', 'x.js'), 'must not be copied\n');
  put(path.join(dist, 'stats.json'), '{}');
  return dist;
}

