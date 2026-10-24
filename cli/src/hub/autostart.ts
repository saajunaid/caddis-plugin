/**
 * Opt-in logon autostart for the hub (H1.8): `caddis hub autostart enable | disable | status`.
 *
 * - Windows: a logon task `caddis-hub` runs `wscript.exe <hubDir>/autostart.vbs`. The vbs starts
 *   `caddis hub serve` with no console window (style 0, no wait).
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
    writeText(vbs, buildVbs(node, entry));
    const r = await runCmd('schtasks', schtasksCreateArgs(vbs));
    return r.ok
      ? { ok: true, message: `caddis hub autostart enabled (logon task ${TASK_NAME})` }
      : { ok: false, message: `schtasks /Create failed (exit ${r.code})` };
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
    return r.ok
      ? { ok: true, message: 'caddis hub autostart disabled' }
      : { ok: true, message: 'caddis hub autostart was not enabled (no logon task to delete)' };
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
  const enabled =
    kind === 'win'
      ? (await runCmd('schtasks', schtasksQueryArgs())).ok
      : existsSync(kind === 'mac' ? plistPath(home) : desktopPath(home));
  return { ok: enabled, message: enabled ? 'caddis hub autostart is enabled' : 'caddis hub autostart is not enabled' };
}
