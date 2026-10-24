/**
 * A time limit for one wait. A source keeps a `running` latch, so a wait that never ends would stop that source
 * for good. Every wait inside a latch goes through `withTimeout` (or has its own timeout, as `spawnBounded` has).
 */

/** `work`, or a rejection with `<what> did not finish in N s` after `ms`. The timer never keeps Node alive. */
export function withTimeout<T>(work: Promise<T>, ms: number, what: string): Promise<T> {
  let timer: NodeJS.Timeout | undefined;
  const limit = new Promise<never>((_resolve, reject) => {
    timer = setTimeout(() => reject(new Error(`${what} did not finish in ${Math.round(ms / 1000)} s`)), ms);
    timer.unref();
  });
  return Promise.race([work, limit]).finally(() => clearTimeout(timer));
}
