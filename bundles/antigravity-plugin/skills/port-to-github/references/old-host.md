# Retiring the old host

Only after: the app is on GitHub, SHA-verified, and its first GitHub deploy was green and
verified by an artefact changing.

## 1. Prove nothing is lost

```powershell
& <skill>/scripts/Compare-PortRefs.ps1 -Left <old-url> -Right https://github.com/<owner>/<repo>.git `
    -Mode LeftInRight -LeftLabel old -RightLabel github
```

Exit 0 means every branch and tag on the old host exists on GitHub with the same SHA. If not,
push the missing refs to GitHub first (from a fresh `git clone --mirror` of the old host, with
an explicit refspec for just those refs) and run it again. Release tags pushed by the old CI
after the port are the usual stragglers.

## 2. Find what still depends on the old host

Search every consumer's default branch (not working trees) for the old host name: dependency
pins, registry config, CI steps, deploy scripts. Anything found keeps the old host alive, and
keeps a credential for it alive.

## 3. Choose: read-only mirror, archive, or delete

| Option | When | Cost |
|---|---|---|
| **Read-only pull mirror of GitHub** (Actions OFF) | Something still pins from the old URL, or you want a live fallback | The old host keeps running; a mirror that stops pulling goes stale silently |
| Archive (read-only, no sync) | Nothing depends on it; you want the old PR/issue history browsable | A frozen snapshot that drifts from day one |
| Delete | Nothing depends on it and its history is exported | Irreversible |

**Never a push mirror driven by CI.** A job pushing into a host that then runs CI on what
arrives has caused a full outage: tests failed, deploy was skipped (not failed), the push guard
only checked `failure`, and it pushed a change disabling the old deploy - leaving no deploy path
anywhere. A pull mirror with Actions disabled cannot do that.

## 4. Converting a Gitea repo into a pull mirror

An existing Gitea repo cannot be converted in place. It must be deleted and recreated as a
mirror under the same path, which **destroys its pull requests and issues** - export them first
(API: `/repos/{owner}/{repo}/pulls?state=all`, `/issues?state=all`, comments per item).

1. Run step 1 again immediately before, and export PRs/issues.
2. `DELETE /api/v1/repos/{owner}/{repo}`.
3. **Verify the delete on BOTH halves: the API returns 404 AND the repository directory is gone
   on disk.** Gitea can remove the database row and fail on disk (a locked pack file). The next
   create then returns 500 while still making an EMPTY mirror row, on which `mirror-sync`
   returns 400. The Gitea log names the locked file; nothing else does.
4. `POST /api/v1/repos/migrate` with `mirror: true`, the GitHub clone URL, and a GitHub read
   token (`auth_token`). Then disable Actions on it (`has_actions: false`).
5. Verify by refs, not by existence: `Compare-PortRefs.ps1 -Left <github> -Right <gitea> -Mode Equal`.
6. If something pins from the mirror, prove it: clone the exact pinned tag from the mirror.

## 5. Watching a mirror

A pull mirror syncs on an interval (Gitea default 8h). A mirror behind GitHub is either LAGGING
(the GitHub commit is newer than the mirror's last pull - normal) or STALE (the commit was there
at the last pull and still did not arrive - the stored credential probably expired). Decide
which by comparing the GitHub commit time with the mirror's last-update time before you touch
any credential. `POST /repos/{owner}/{repo}/mirror-sync` forces a pull: an immediate match means
it was lag.
