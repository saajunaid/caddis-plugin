/**
 * The agent adapter contract.
 *
 * caddis's CLI is a META-INSTALLER: it detects an agent and drives that agent's
 * OWN native mechanism. It never reimplements Claude Code's marketplace or
 * agy's installer. One adapter per agent, fully isolated, so a flag rename in
 * a vendor CLI is a one-file blast radius (plan risk #3).
 */
export type AgentId = 'claude' | 'agy' | 'codex' | 'copilot';

export type DriveAction = 'install' | 'update';

/** Is the agent on this machine at all? */
export interface Detection {
  present: boolean;
  /** Binary path, or config path for file-configured agents. */
  path?: string;
  /** The AGENT's own version, when it is cheap to obtain. Not caddis's. */
  agentVersion?: string;
  /** Why detection concluded what it did. Shown by doctor. */
  note?: string;
}

/**
 * The optional long-tail skill plugin (`caddis-extras`).
 *
 * It is a SEPARATE plugin with its OWN version line — 1.3.13 while core is
 * 1.3.39 — so it can never be compared against the core pool version. Tracked
 * apart from `AgentStatus.version` for exactly that reason.
 */
export interface ExtrasStatus {
  installed: boolean;
  version?: string;
  source?: string;
}

/** Which caddis is installed INTO that agent? */
export interface AgentStatus {
  installed: boolean;
  /** The caddis CORE version the agent currently has. */
  version?: string;
  /** Where the version was read from — doctor prints it so a wrong answer is debuggable. */
  source?: string;
  /** True when the agent has caddis but it is disabled rather than active. */
  disabled?: boolean;
  /** Undefined when the adapter does not support an extras plugin at all. */
  extras?: ExtrasStatus;
  note?: string;
}

export interface StepResult {
  command: string;
  ok: boolean;
  code: number | null;
  /** Trimmed stderr/stdout tail, for the failure message only. */
  output?: string;
}

export interface DriveResult {
  ok: boolean;
  /** True when nothing was attempted (absent agent, unsupported, dry run). */
  skipped: boolean;
  steps: StepResult[];
  message?: string;
}

export interface DriveOptions {
  dryRun: boolean;
  /**
   * Add the optional `caddis-extras` long-tail plugin (`--extras`), mirroring
   * `caddis-init --extras`. Opt-in: extras is a large, always-loaded skill set,
   * so it is never installed by default. An extras install that ALREADY exists
   * is kept current regardless of this flag — adapters decide that.
   */
  extras?: boolean;
}

export interface AgentAdapter {
  readonly id: AgentId;
  /** Display name. */
  readonly name: string;
  /**
   * False for the v0.2 stubs (Codex / Copilot): they are DETECTED and
   * reported, never driven. Absence — and un-support — is graceful.
   */
  readonly supported: boolean;
  /** One line explaining what driving this agent does. Shown by --dry-run and init. */
  readonly summary: string;
  detect(): Promise<Detection>;
  drive(action: DriveAction, options: DriveOptions): Promise<DriveResult>;
  status(): Promise<AgentStatus>;
}
