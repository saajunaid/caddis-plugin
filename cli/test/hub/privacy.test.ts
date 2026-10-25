import { existsSync, mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { hitLine, scanExport, type Hit } from '../../src/hub/export/privacy.js';

/**
 * H6.3: the privacy scan (R62). Each planted value must give a hit. The values are samples, and the tokens that look
 * like paths or hashes are built in code, so no tracked file holds one.
 */
let dir: string;
beforeEach(() => {
  dir = mkdtempSync(path.join(tmpdir(), 'caddis-hub-privacy-'));
  mkdirSync(path.join(dir, 'assets'));
  mkdirSync(path.join(dir, 'fonts'));
  writeFileSync(path.join(dir, 'assets', 'app.js'), 'console.log("hello");\n');
  write('index.html', page('{"schema":1,"roadmaps":[]}'));
});
afterEach(() => rmSync(dir, { recursive: true, force: true }));

const write = (rel: string, content: string | Buffer): void => writeFileSync(path.join(dir, ...rel.split('/')), content);
const page = (data: string): string =>
  `<!doctype html><html><head><meta charset="utf-8"></head><body><div id="root"></div>` +
  `<script type="application/json" id="caddis-export-data">${data}</script></body></html>\n`;
const scan = (extra: { deny?: string[]; github?: string | null } = {}): Hit[] =>
  scanExport(dir, { deny: extra.deny ?? [], github: extra.github === undefined ? 'acme/shop' : extra.github });
const rules = (hits: Hit[]): string[] => hits.map((h) => h.rule);

const WIN = ['C:', 'Users', 'sample-user'].join('\\');
const UNC = ['', '', 'sample-server', 'share'].join('\\');
const SHA40 = 'abcdef0123456789'.repeat(3).slice(0, 40);

describe('scanExport (R62)', () => {
  it('a clean folder gives no hit', () => {
    expect(scan()).toEqual([]);
  });

  it('a derived value in a JS file', () => {
    write('assets/app.js', 'const host = "sample-host-77";\n');
    const hits = scan({ deny: ['sample-host-77'] });
    expect(hits).toEqual([{ file: 'assets/app.js', offset: 14, rule: 'derived-private-value' }]);
  });

  it('a derived value matches without regard to case', () => {
    write('index.html', page('{"reason":"run on SAMPLE-HOST-77"}'));
    expect(rules(scan({ deny: ['sample-host-77'] }))).toEqual(['derived-private-value']);
  });

  it('a derived value inside a woff2 byte stream', () => {
    write('fonts/a.woff2', Buffer.concat([Buffer.from('wOF2'), Buffer.from([0, 1, 2, 3]), Buffer.from('sample-host-77'), Buffer.from([9, 9])]));
    const hits = scan({ deny: ['sample-host-77'] });
    expect(hits).toEqual([{ file: 'fonts/a.woff2', offset: 8, rule: 'derived-private-value' }]);
  });

  it('short and numeric values do not match binary noise', () => {
    write('fonts/a.woff2', Buffer.from('wOF2 424242 abc'));
    expect(scan({ deny: ['424242', 'abc'] })).toEqual([]);
  });

  it('a numeric value needs digit boundaries in text', () => {
    write('assets/app.js', 'const n = 1424242;\n');
    expect(scan({ deny: ['424242'] })).toEqual([]);
    write('assets/app.js', 'const n = 424242;\n');
    expect(rules(scan({ deny: ['424242'] }))).toEqual(['derived-private-value']);
  });

  it('a short plain word is skipped in assets but found in the page', () => {
    write('assets/app.js', 'const dev = 1;\n');
    expect(scan({ deny: ['dev'] })).toEqual([]);
    write('index.html', page('{"reason":"run on dev"}'));
    expect(rules(scan({ deny: ['dev'] }))).toEqual(['derived-private-value']);
  });

  it.each([
    ['sessionId', '{"sessionId":"x"}', 'private-name:sessionId'],
    ['session_id', '{"session_id":"x"}', 'private-name:session_id'],
    ['waitingFor', '{"waitingFor":"x"}', 'private-name:waitingFor'],
    ['prompt', '{"prompt":"x"}', 'private-name:prompt'],
    ['cap_eur', '{"cap_eur":1}', 'private-name:cap_eur'],
    ['committed_eur', '{"committed_eur":1}', 'private-name:committed_eur'],
    ['coordinator.json', '{"note":"see coordinator.json"}', 'private-name:coordinator.json'],
    ['requests.jsonl', '{"note":"requests.jsonl"}', 'private-name:requests.jsonl'],
    ['audit.jsonl', '{"note":"audit.jsonl"}', 'private-name:audit.jsonl'],
    ['coordinator_session', '{"coordinator_session":"x"}', 'private-name:coordinator_session'],
    ['heartbeat_at', '{"heartbeat_at":"x"}', 'private-name:heartbeat_at'],
    ['roadmap-pages', '{"note":"roadmap-pages"}', 'private-name:roadmap-pages'],
    ['X-Caddis-Hub', '{"note":"X-Caddis-Hub"}', 'private-name:X-Caddis-Hub'],
  ])('a private key or file name in the data block: %s', (_name, data, rule) => {
    write('index.html', page(data));
    expect(rules(scan())).toContain(rule);
  });

  it('a private name escaped as \\uXXXX still gives a hit', () => {
    write('index.html', page('{"note":"session\\u005fid"}'));
    expect(rules(scan())).toContain('private-name:session_id');
  });

  it.each([
    ['a Windows drive path', `{"check":"${WIN.replace(/\\/g, '\\\\')}"}`, 'pattern:windows-drive-path'],
    ['a drive path with a slash', '{"check":"D:/work/shop"}', 'pattern:windows-drive-path'],
    ['a UNC path', `{"check":"${UNC.replace(/\\/g, '\\\\')}"}`, 'pattern:unc-path'],
    ['a /home/ path', '{"check":"/home/sample/work"}', 'pattern:home-path'],
    ['a /Users/ path', '{"check":"/Users/sample/work"}', 'pattern:users-path'],
    ['a /root/ path', '{"check":"/root/work"}', 'pattern:root-path'],
    ['a /runner/ path', '{"check":"/home/runner/work"}', 'pattern:runner-path'],
    ['an e-mail address', '{"reason":"ask sample.person@example.invalid"}', 'pattern:email-address'],
    ['an IPv4 address', '{"reason":"host 10.20.30.40"}', 'pattern:ipv4-address'],
    ['a 40-hex SHA', `{"tracker":"done ${SHA40}"}`, 'pattern:sha-40'],
  ])('%s in the page', (_name, data, rule) => {
    write('index.html', page(data));
    expect(rules(scan())).toContain(rule);
  });

  it('a version number and a 7-hex commit are not hits', () => {
    write('index.html', page('{"reason":"v1.2.3 and commit ABC1234 and https://github.com/acme/shop/pull/7"}'));
    expect(rules(scan())).not.toContain('pattern:ipv4-address');
    expect(rules(scan())).not.toContain('pattern:sha-40');
    expect(rules(scan())).not.toContain('pattern:windows-drive-path');
  });

  it('a URL that is not on the allow-list', () => {
    write('assets/app.js', 'fetch("https://evil.test/x");\n');
    expect(scan()).toEqual([{ file: 'assets/app.js', offset: 7, rule: 'url-not-allowed' }]);
  });

  it('a PR URL passes only for the --github value', () => {
    write('index.html', page('{"u":"https://github.com/acme/shop/pull/7"}'));
    expect(scan({ github: 'acme/shop' })).toEqual([]);
    write('index.html', page('{"u":"https://github.com/other/repo/pull/1"}'));
    expect(rules(scan({ github: 'acme/shop' }))).toEqual(['url-not-allowed']);
    write('index.html', page('{"u":"https://github.com/acme/shop/pull/7"}'));
    expect(rules(scan({ github: null }))).toEqual(['url-not-allowed']);
  });

  it('a URL template in a JS file passes, in the page it does not', () => {
    write('assets/app.js', 'const u = `https://github.com/${e}/pull/${n}`;\n');
    expect(scan()).toEqual([]);
    write('index.html', page('{"u":"https://github.com/${e}/pull/1"}'));
    expect(rules(scan())).toEqual(['url-not-allowed']);
  });

  it('the allow-list file names the namespace URLs', () => {
    write('assets/app.js', 'const ns = "http://www.w3.org/2000/svg";\n');
    expect(scan()).toEqual([]);
  });

  it('a hit names the file, the offset and the rule, and the line does not show the value', () => {
    write('assets/app.js', 'const a = 1; const host = "sample-host-77";\n');
    const [hit] = scan({ deny: ['sample-host-77'] });
    expect(hit).toMatchObject({ file: 'assets/app.js', rule: 'derived-private-value' });
    expect(typeof hit!.offset).toBe('number');
    expect(hitLine(hit!)).toBe(`privacy: assets/app.js:${hit!.offset}: derived-private-value`);
    expect(hitLine(hit!)).not.toContain('sample-host-77');
  });

  it('a symbolic link is a hit', () => {
    try {
      // A link needs a right on some Windows set-ups. Without it the test has nothing to check.
      writeFileSync(path.join(dir, 'real.txt'), 'x');
      symlinkSync(path.join(dir, 'real.txt'), path.join(dir, 'link.txt'), 'file');
    } catch {
      return;
    }
    expect(rules(scan())).toContain('symbolic-link');
  });
});

// The export build holds the React and SVG namespace URLs. They must pass. Skipped when `dist/export` is not built.
const BUILT = fileURLToPath(new URL('../../dist/export', import.meta.url));
describe.skipIf(!existsSync(path.join(BUILT, 'index.html')))('a real dist/export build', () => {
  it('passes the URL rule', () => {
    const hits = scanExport(BUILT, { deny: [], github: 'acme/shop' }).filter((h) => h.rule === 'url-not-allowed');
    expect(hits).toEqual([]);
  });
});
