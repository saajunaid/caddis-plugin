// On Windows, killing a child does not release its open files until it closes.
export async function stopPreview(preview, closed, graceMs = 5000) {
  if (!preview) return;
  if (preview.exitCode === null && preview.signalCode === null && !preview.kill())
    throw new Error('Could not stop vite preview');
  // A child that ignores the term signal must not block the teardown forever: force-kill it.
  const finished = await Promise.race([closed.then(() => true), new Promise(resolve => setTimeout(resolve, graceMs, false))]);
  if (!finished) {
    preview.kill('SIGKILL');
    await closed;
  }
}
