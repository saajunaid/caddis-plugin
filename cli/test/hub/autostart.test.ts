import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import {
  autostartStatus,
  buildDesktop,
  buildPlist,
  buildVbs,
  desktopPath,
  disableAutostart,
  enableAutostart,
  plistPath,
  schtasksCreateArgs,
  vbsPath,
  type CmdRunner,
} from '../../src/hub/autostart.js';

const NODE = 'C:\\Program Files\\nodejs\\node.exe';
const ENTRY = 'C:\\Users\\demo user\\app\\cli.js';

let home: string;
let calls: Array<[string, string[]]>;
let result: { ok: boolean; code: number | null };
const runCmd: CmdRunner = async (cmd, args) => {
  calls.push([cmd, args]);
  return result;
};

beforeEach(() => {
  home = mkdtempSync(path.join(tmpdir(), 'caddis-hub-'));
  calls = [];
  result = { ok: true, code: 0 };
});
afterEach(() => rmSync(home, { recursive: true, force: true }));

describe('builders', () => {
  it('vbs has exactly one Run line with doubled inner quotes, style 0, no wait', () => {
    expect(buildVbs(NODE, ENTRY)).toBe(
      'CreateObject("WScript.Shell").Run """C:\\Program Files\\nodejs\\node.exe"" ""C:\\Users\\demo user\\app\\cli.js"" hub serve", 0, False\r\n',
    );
  });

  it('schtasks create args are an array with the quoted vbs path', () => {
    expect(schtasksCreateArgs('C:\\Users\\demo user\\.caddis\\hub\\autostart.vbs')).toEqual([
      '/Create', '/SC', 'ONLOGON', '/RL', 'LIMITED', '/TN', 'caddis-hub',
      '/TR', 'wscript.exe "C:\\Users\\demo user\\.caddis\\hub\\autostart.vbs"', '/F',
    ]);
  });

  it('plist lists the arguments and RunAtLoad, with XML escaping', () => {
    const text = buildPlist('/usr/local/bin/node', '/Users/demo user/a&b/cli.js');
    expect(text).toContain('<key>Label</key>\n  <string>dev.caddis.hub</string>');
    expect(text).toContain(
      '    <string>/usr/local/bin/node</string>\n    <string>/Users/demo user/a&amp;b/cli.js</string>\n    <string>hub</string>\n    <string>serve</string>',
    );
    expect(text).toContain('<key>RunAtLoad</key>\n  <true/>');
  });

  it('desktop entry quotes each Exec argument and escapes reserved characters', () => {
    expect(buildDesktop('/usr/bin/node', '/home/demo user/$x/cli.js')).toBe(
      '[Desktop Entry]\nType=Application\nName=caddis hub\n' +
        'Exec="/usr/bin/node" "/home/demo user/\\\\$x/cli.js" "hub" "serve"\n' +
        'X-GNOME-Autostart-enabled=true\nNoDisplay=true\n',
    );
  });
});

describe('windows runner', () => {
  it('enable writes the vbs and creates the task', async () => {
    const r = await enableAutostart({ home, platform: 'win32', node: NODE, entry: ENTRY, runCmd });
    expect(r.ok).toBe(true);
    expect(readFileSync(vbsPath(home), 'utf8')).toBe(buildVbs(NODE, path.resolve(ENTRY)));
    expect(calls).toEqual([['schtasks', schtasksCreateArgs(vbsPath(home))]]);
  });

  it('enable reports a schtasks failure', async () => {
    result = { ok: false, code: 1 };
    const r = await enableAutostart({ home, platform: 'win32', node: NODE, entry: ENTRY, runCmd });
    expect(r.ok).toBe(false);
  });

  it('disable deletes the task and removes the vbs', async () => {
    await enableAutostart({ home, platform: 'win32', node: NODE, entry: ENTRY, runCmd });
    calls = [];
    const r = await disableAutostart({ home, platform: 'win32', runCmd });
    expect(r.ok).toBe(true);
    expect(calls).toEqual([['schtasks', ['/Delete', '/TN', 'caddis-hub', '/F']]]);
    expect(existsSync(vbsPath(home))).toBe(false);
  });

  it('status uses the query exit code', async () => {
    expect((await autostartStatus({ home, platform: 'win32', runCmd })).ok).toBe(true);
    expect(calls).toEqual([['schtasks', ['/Query', '/TN', 'caddis-hub']]]);
    result = { ok: false, code: 1 };
    expect((await autostartStatus({ home, platform: 'win32', runCmd })).ok).toBe(false);
  });
});

describe('macOS runner', () => {
  it('enable writes the plist and loads it; disable unloads and removes it', async () => {
    await enableAutostart({ home, platform: 'darwin', node: '/n/node', entry: '/a/cli.js', runCmd });
    const file = plistPath(home);
    expect(readFileSync(file, 'utf8')).toBe(buildPlist('/n/node', path.resolve('/a/cli.js')));
    expect(calls).toEqual([['launchctl', ['load', '-w', file]]]);
    expect((await autostartStatus({ home, platform: 'darwin', runCmd })).ok).toBe(true);
    calls = [];
    await disableAutostart({ home, platform: 'darwin', runCmd });
    expect(calls).toEqual([['launchctl', ['unload', '-w', file]]]);
    expect(existsSync(file)).toBe(false);
    expect((await autostartStatus({ home, platform: 'darwin', runCmd })).ok).toBe(false);
  });
});

describe('linux runner', () => {
  it('enable writes the desktop file; disable removes it; no command runs', async () => {
    await enableAutostart({ home, platform: 'linux', node: '/n/node', entry: '/a/cli.js', runCmd });
    const file = desktopPath(home);
    expect(readFileSync(file, 'utf8')).toBe(buildDesktop('/n/node', path.resolve('/a/cli.js')));
    expect((await autostartStatus({ home, platform: 'linux', runCmd })).ok).toBe(true);
    await disableAutostart({ home, platform: 'linux', runCmd });
    expect(existsSync(file)).toBe(false);
    expect(calls).toEqual([]);
  });
});
