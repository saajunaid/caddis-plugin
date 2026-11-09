/**
 * Opt-in logon autostart for the hub (H1.8): `caddis hub autostart enable | disable | status`.
 *
 * - Windows: a logon task `caddis-hub` runs `wscript.exe <hubDir>/autostart.vbs`. The vbs starts
 *   `caddis hub serve` with no console window (style 0, no wait). Some machines refuse `schtasks /Create`
 *   to a user who is not an administrator ("Access is denied"). Then the same vbs goes into the user's
 *   Startup folder (`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\caddis-hub.vbs`).
 * - macOS: a LaunchAgent `dev.caddis.hub`.
 * - Linux: `~/.config/autostart/caddis-hub.desktop`.
 * The builders are pure. The runner takes the home, the platform and the command runner as deps,
 * so tests never touch the real system.
 */
import { existsSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { run } from '../util/exec.js';
import { caddisHome } from '../util/sessions.js';
import { hubDir } from './paths.js';

export const TASK_NAME = 'caddis-hub';
export const MAC_LABEL = 'dev.caddis.hub';
const CMD_TIMEOUT_MS = 30_000;

/** The one-line VBScript launcher. Inner quotes are doubled the VBScript way. */
export function buildVbs(node: string, entry: string): string {
  const q = (s: string): string => `""${s.replace(/"/g, '""""')}""`;
  return `CreateObject("WScript.Shell").Run "${q(node)} ${q(entry)} hub serve", 0, False\r\n`;
}

export const vbsPath = (home?: string): string => path.join(hubDir(home), 'autostart.vbs');

/** The Startup folder launcher, the fallback when the logon task cannot be created. */
export const startupVbsPath = (appData: string): string =>
  path.join(appData, 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup', `${TASK_NAME}.vbs`);

/** Args for `schtasks /Create`. Pass them to execa with `shell: false`. */
export function schtasksCreateArgs(vbs: string): string[] {
  return ['/Create', '/SC', 'ONLOGON', '/RL', 'LIMITED', '/TN', TASK_NAME, '/TR', `wscript.exe "${vbs}"`, '/F'];
}
export const schtasksDeleteArgs = (): string[] => ['/Delete', '/TN', TASK_NAME, '/F'];
export const schtasksQueryArgs = (): string[] => ['/Query', '/TN', TASK_NAME];

const xml = (s: string): string =>
  s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

export const plistPath = (home: string): string => path.join(home, 'Library', 'LaunchAgents', `${MAC_LABEL}.plist`);

export function buildPlist(node: string, entry: string): string {
  const args = [node, entry, 'hub', 'serve'].map((a) => `    <string>${xml(a)}</string>`).join('\n');
  return `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${MAC_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
${args}
  </array>
  <key>RunAtLoad</key>
  <true/>
</dict>
</plist>
`;
}

export const desktopPath = (home: string): string => path.join(home, '.config', 'autostart', `${TASK_NAME}.desktop`);

/** Quote one Exec argument per the desktop entry spec: escape reserved characters, then double every backslash. */
function desktopArg(a: string): string {
  const escaped = a.replace(/([`$"\\])/g, '\\$1').replace(/%/g, '%%');
  return `"${escaped.replace(/\\/g, '\\\\')}"`;
}

export function buildDesktop(node: string, entry: string): string {
  const exec = [node, entry, 'hub', 'serve'].map(desktopArg).join(' ');
  return `[Desktop Entry]
Type=Application
Name=caddis hub
Exec=${exec}
X-GNOME-Autostart-enabled=true
NoDisplay=true
`;
}

export interface CmdResult {
  ok: boolean;
  code: number | null;
}
export type CmdRunner = (cmd: string, args: string[]) => Promise<CmdResult>;

export interface AutostartDeps {
  home?: string;
  platform?: NodeJS.Platform;
  node?: string;
  entry?: string;
  runCmd?: CmdRunner;
  /** Windows `%APPDATA%`, for the Startup folder fallback. Default: the `APPDATA` environment variable. */
  appData?: string;
}

export interface AutostartResult {
  ok: boolean;
  message: string;
}

const defaultRun: CmdRunner = async (cmd, args) => {
  const r = await run(cmd, args, { timeout: CMD_TIMEOUT_MS });
  return { ok: r.ok, code: r.code };
};

function writeText(file: string, text: string): void {
  mkdirSync(path.dirname(file), { recursive: true });
  writeFileSync(file, text, 'utf8');
}

const appDataOf = (deps: AutostartDeps): string | undefined => deps.appData ?? process.env.APPDATA;

type Kind = 'win' | 'mac' | 'linux';
const kindOf = (p: NodeJS.Platform): Kind => (p === 'win32' ? 'win' : p === 'darwin' ? 'mac' : 'linux');

export async function enableAutostart(deps: AutostartDeps = {}): Promise<AutostartResult> {
  const home = deps.home ?? caddisHome();
  const node = deps.node ?? process.execPath;
  const rawEntry = deps.entry ?? process.argv[1];
  if (!rawEntry) return { ok: false, message: 'cannot find the caddis CLI entry script' };
  const entry = path.resolve(rawEntry);
  const runCmd = deps.runCmd ?? defaultRun;
  const kind = kindOf(deps.platform ?? process.platform);
  if (kind === 'win') {
    const vbs = vbsPath(home);
    const text = buildVbs(node, entry);
    writeText(vbs, text);
    const r = await runCmd('schtasks', schtasksCreateArgs(vbs));
    const appData = appDataOf(deps);
    if (r.ok) {
      // One launcher only: a Startup file from an earlier fallback would start a second serve.
      if (appData) rmSync(startupVbsPath(appData), { force: true });
      return { ok: true, message: `caddis hub autostart enabled (logon task ${TASK_NAME})` };
    }
    if (!appData) {
      return { ok: false, message: `schtasks /Create failed (exit ${r.code}) and APPDATA is not set, so there is no Startup folder` };
    }
    const startup = startupVbsPath(appData);
    writeText(startup, text);
    return {
      ok: true,
      message: `caddis hub autostart enabled (Startup folder: ${startup}); the logon task failed (schtasks exit ${r.code})`,
    };
  }
  if (kind === 'mac') {
    const file = plistPath(home);
    writeText(file, buildPlist(node, entry));
    const r = await runCmd('launchctl', ['load', '-w', file]);
    return r.ok
      ? { ok: true, message: `caddis hub autostart enabled (${file})` }
      : { ok: false, message: `launchctl load failed (exit ${r.code})` };
  }
  const file = desktopPath(home);
  writeText(file, buildDesktop(node, entry));
  return { ok: true, message: `caddis hub autostart enabled (${file})` };
}

export async function disableAutostart(deps: AutostartDeps = {}): Promise<AutostartResult> {
  const home = deps.home ?? caddisHome();
  const runCmd = deps.runCmd ?? defaultRun;
  const kind = kindOf(deps.platform ?? process.platform);
  if (kind === 'win') {
    const r = await runCmd('schtasks', schtasksDeleteArgs());
    rmSync(vbsPath(home), { force: true });
    const appData = appDataOf(deps);
    const startup = appData ? startupVbsPath(appData) : null;
    const hadStartup = startup !== null && existsSync(startup);
    if (startup) rmSync(startup, { force: true });
    const removed = [r.ok ? `logon task ${TASK_NAME}` : '', hadStartup ? 'Startup folder launcher' : ''].filter(Boolean);
    return removed.length
      ? { ok: true, message: `caddis hub autostart disabled (removed ${removed.join(' and ')})` }
      : { ok: true, message: 'caddis hub autostart was not enabled (no logon task or Startup launcher to remove)' };
  }
  if (kind === 'mac') {
    const file = plistPath(home);
    if (existsSync(file)) await runCmd('launchctl', ['unload', '-w', file]);
    rmSync(file, { force: true });
    return { ok: true, message: 'caddis hub autostart disabled' };
  }
  rmSync(desktopPath(home), { force: true });
  return { ok: true, message: 'caddis hub autostart disabled' };
}

/** `ok` is true when autostart is enabled. */
export async function autostartStatus(deps: AutostartDeps = {}): Promise<AutostartResult> {
  const home = deps.home ?? caddisHome();
  const runCmd = deps.runCmd ?? defaultRun;
  const kind = kindOf(deps.platform ?? process.platform);
  if (kind === 'win') {
    const task = (await runCmd('schtasks', schtasksQueryArgs())).ok;
    const appData = appDataOf(deps);
    const startup = appData ? startupVbsPath(appData) : null;
    const how = [task ? `logon task ${TASK_NAME}` : '', startup && existsSync(startup) ? `Startup folder: ${startup}` : ''];
    const on = how.filter(Boolean);
    return on.length
      ? { ok: true, message: `caddis hub autostart is enabled (${on.join('; ')})` }
      : { ok: false, message: 'caddis hub autostart is not enabled' };
  }
  const enabled = existsSync(kind === 'mac' ? plistPath(home) : desktopPath(home));
  return { ok: enabled, message: enabled ? 'caddis hub autostart is enabled' : 'caddis hub autostart is not enabled' };
}
