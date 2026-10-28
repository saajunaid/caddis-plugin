import path from 'node:path';
import { caddisHome } from '../util/sessions.js';

/** The hub data folder: `<home>/.caddis/hub`. Home is `CADDIS_HOME` or the user home (R21). */
export function hubDir(home: string = caddisHome()): string {
  return path.join(home, '.caddis', 'hub');
}

/** `CADDIS_HUB_HOME` is the hub folder itself (as in `caddis_coordinate.py`); else `<home>/.caddis/hub`. */
export function hubHome(home?: string): string {
  const override = process.env.CADDIS_HUB_HOME;
  return override ? override : hubDir(home);
}

export const configPath = (home?: string): string => path.join(hubDir(home), 'config.json');
export const registryPath = (home?: string): string => path.join(hubDir(home), 'repos.json');
export const keyPath = (home?: string): string => path.join(hubDir(home), 'key');
export const lockPath = (home?: string): string => path.join(hubDir(home), 'hub.lock');
/** The one audit file: the action route writes it and the state reads it, so both use `hubHome`. */
export const auditPath = (home?: string): string => path.join(hubHome(home), 'audit.jsonl');

export function sessionsPath(home?: string): string {
  return path.join(hubDir(home), 'sessions.json');
}
