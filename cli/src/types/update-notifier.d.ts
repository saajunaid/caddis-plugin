/**
 * update-notifier v7 ships no type declarations and there is no @types package
 * for it. Declare only the surface we use.
 */
declare module 'update-notifier' {
  interface Options {
    pkg: { name: string; version: string };
    updateCheckInterval?: number;
    shouldNotifyInNpmScript?: boolean;
    distTag?: string;
  }

  interface NotifyOptions {
    defer?: boolean;
    message?: string;
    isGlobal?: boolean;
    boxenOptions?: unknown;
  }

  interface Notifier {
    notify(options?: NotifyOptions): void;
    update?: { current: string; latest: string; type: string; name: string };
  }

  export default function updateNotifier(options: Options): Notifier;
}
