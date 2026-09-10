---
name: windows-deployment
description: "Deploy FastAPI + React/Vite apps to Windows Server with NSSM services, reverse proxy (IIS or nginx), and git-pull workflow. Use when deploying any web app to a Windows prod server, setting up NSSM services, configuring IIS or nginx reverse proxy, making code environment-aware for dev/prod, or troubleshooting prod deployment issues."
---

# Windows Server Deployment Skill

Deploy FastAPI + React/Vite web applications to Windows Server using NSSM services, a reverse proxy (IIS or nginx), and a git-pull workflow.

## 1. When to Apply This Skill

**Trigger conditions:**
- "Deploy this app to prod" / "Deploy to Windows Server"
- Setting up a new web application on a Windows prod server
- Adding a reverse proxy (IIS or nginx) for an app
- Registering NSSM services
- Configuring environment-aware dev/prod code (subpath, auth, static serving)
- Troubleshooting prod deployment (502, 404, service won't start)
- "Why can't the frontend reach the API?"

**Prerequisites the user should have:**
- A FastAPI + React/Vite app
- A Windows Server target machine
- NSSM installed on the target
- A git remote (Gitea, GitHub, etc.) accessible from both dev and prod
- Python and Node.js installed on the target

---

## 2. Architecture Overview

Two reverse proxy strategies are available. Choose based on what the server already runs.

### Strategy A — IIS (Recommended When IIS Is Already Running)

```
Browser → IIS (:80/:443)
           ├─ Windows Auth + Active Directory (handled by IIS)
           ├─ URL Rewrite: /{subpath}/api/* → http://localhost:{api-port}/api/*
           └─ URL Rewrite: /{subpath}/*     → http://localhost:{api-port}/*
                                                 ├─ /api/* → FastAPI routers
                                                 └─ /*     → FastAPI serves dist/ static files

NSSM manages:
  - <org>-{app}-api-prod (one per app)
```

**Key characteristics:**
- IIS handles authentication (Windows Auth, AD groups) — app code has zero auth logic
- App is deployed under a subpath (e.g. `/my-app/`) — IIS strips the prefix before forwarding
- FastAPI serves both API routes and static frontend files in production
- No separate frontend service/port needed

### Strategy B — nginx (Standalone Reverse Proxy)

```
Browser → nginx (:51xx) → serves static dist/ files
                         → proxies /api/* → uvicorn (:81xx)

NSSM manages:
  - <org>-nginx-prod (single instance, all apps)
  - <org>-{app}-api-prod (one per app)
```

**Key characteristics:**
- nginx handles static file serving and API proxying
- Each app gets its own port (e.g. `:5103`, `:5104`)
- No built-in auth — add separately if needed
- Clean separation: nginx = static + proxy, uvicorn = API only

### Decision Matrix

| Factor | Choose IIS | Choose nginx |
|--------|-----------|-------------|
| IIS already running on the server | ✅ | |
| Need Windows Authentication / AD | ✅ | |
| Apps must be on port 80/443 | ✅ | |
| Multiple apps under one domain with subpaths | ✅ | |
| No IIS on the server | | ✅ |
| Need lightweight, portable setup | | ✅ |
| Each app gets its own port | | ✅ |

### Port Convention

| Environment | API (uvicorn) | Frontend |
|-------------|--------------|----------|
| Dev         | 81x2         | 51x2 (Vite dev server) |
| Prod (IIS)  | 81x3         | IIS on :80/:443 (no separate FE port) |
| Prod (nginx)| 81x3         | 51x3 (nginx) |

Where `x` is the app number. Prod API ports increment per app on the shared server (8103, 8104, 8105...).

---

## 3. Deployment Flow

### First-Time Setup (Both Strategies)

```
1. Clone repo on prod via git
2. Set up Python venv + install deps
3. Build frontend (npm ci && npm run build:prod)
4. Create config/.env.api.prod
5. Register NSSM API service
6. Configure reverse proxy (IIS or nginx)
7. Open firewall ports
8. Verify
```

### Subsequent Deploys

```
1. Dev: git push origin main
2. Prod: git pull
3. pip install -e . (if Python deps changed)
4. cd frontend && npm ci && npm run build:prod (if FE changed)
5. nssm restart <org>-{app}-api-prod
6. Verify
```

### 3.1 Remote Capability Handshake (Required Before Saying "Can't Access Prod")

When a user asks for remote prod actions, do **not** assume remote access is unavailable.

Run this handshake first:

```powershell
$server = "{hostname}"

# 1) Reachability
Test-Connection -ComputerName $server -Count 1

# 2) WinRM availability
Test-WSMan -ComputerName $server

# 3) Actual command execution
Invoke-Command -ComputerName $server -ScriptBlock {
  hostname
  Get-Location
}
```

Decision rule:
- If steps 1-3 succeed, proceed with remote deploy actions.
- If any step fails, report the exact failing step and provide fallback instructions.

**Hard rule:** Never claim "I can't remote into prod" until this probe fails in the current session.

---

## 4. Common Steps (Both Strategies)

### 4.1 Git Setup on Prod

```powershell
cd G:\Projects
git clone http://{git-host}/{org}/{app-name}.git
cd {app-name}

# Credential storage (one-time)
git config credential.helper store
[System.Environment]::SetEnvironmentVariable("GCM_PROVIDER", "generic", "User")

git pull  # enter credentials once, stored thereafter
```

If using a self-hosted git server, ensure the `hosts` file maps the hostname.

### 4.2 Python Environment

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
```

**Verify Python version** matches dev: `python --version`.

### 4.3 Frontend Build

```powershell
cd frontend
npm ci
npm run build:prod    # ← uses production Vite mode (see §7)
Get-ChildItem dist -Recurse | Measure-Object
```

### 4.4 Environment Config

Create `config/.env.api.prod`:

```env
APP_ENV=production
APP_PORT=81x3
# Add app-specific vars (DB connection, etc.)
```

**Never commit real `.env` files.** Only `.env.example` with placeholder values.

### 4.5 Register API Service with NSSM

```powershell
$projectRoot = "G:\Projects\{app-name}"
$pythonExe = "$projectRoot\.venv\Scripts\python.exe"
$svcName = "<org>-{short}-api-prod"
$port = 81x3  # Use actual port

nssm install $svcName $pythonExe "-m uvicorn src.api.main:app --host 0.0.0.0 --port $port"
nssm set $svcName AppDirectory $projectRoot
nssm set $svcName DisplayName "{App Name} API (PROD)"
nssm set $svcName Description "{App Name} FastAPI backend - prod environment"
nssm set $svcName AppEnvironmentExtra "APP_ENV=production"

# Logging
nssm set $svcName AppStdout "$projectRoot\logs\$svcName-stdout.log"
nssm set $svcName AppStderr "$projectRoot\logs\$svcName-stderr.log"
nssm set $svcName AppRotateFiles 1
nssm set $svcName AppRotateBytes 10485760  # 10 MB

# Restart on failure
nssm set $svcName AppRestartDelay 5000

nssm start $svcName
```

---

## 5. Strategy A — IIS Reverse Proxy Setup

### 5.1 Prerequisites

Install IIS features (if not already present):
```powershell
Install-WindowsFeature Web-Server, Web-Mgmt-Console
```

Install these IIS modules:
- **URL Rewrite** — https://www.iis.net/downloads/microsoft/url-rewrite
- **Application Request Routing (ARR)** — https://www.iis.net/downloads/microsoft/application-request-routing

Enable ARR proxy functionality:
```powershell
# In IIS Manager → Server level → Application Request Routing → Server Proxy Settings
# Check "Enable proxy" → Apply
# Or via appcmd:
& "$env:SystemRoot\system32\inetsrv\appcmd.exe" set config -section:system.webServer/proxy /enabled:true /commit:apphost
```

### 5.2 IIS Rewrite Rules

Create rewrite rules under the Default Web Site (or a dedicated site). Two rules are needed — the API rule must come first:

**Rule 1 — API proxy (matches first):**
```xml
<rule name="{app-name}-api" stopProcessing="true">
    <match url="^{subpath}/api/(.*)" />
    <action type="Rewrite" url="http://localhost:{api-port}/api/{R:1}" />
</rule>
```

**Rule 2 — Frontend catch-all:**
```xml
<rule name="{app-name}-frontend" stopProcessing="true">
    <match url="^{subpath}/(.*)" />
    <action type="Rewrite" url="http://localhost:{api-port}/{R:1}" />
</rule>
```

**How it works:** IIS strips the subpath prefix before forwarding. FastAPI receives clean paths (`/api/v1/...` and `/index.html`).

### 5.3 Windows Authentication

Enable Windows Auth on the IIS site/app:

```powershell
# Disable anonymous access, enable Windows Auth
Set-WebConfigurationProperty -Filter '/system.webServer/security/authentication/anonymousAuthentication' `
    -PSPath 'IIS:\Sites\Default Web Site' -Name 'enabled' -Value 'false'
Set-WebConfigurationProperty -Filter '/system.webServer/security/authentication/windowsAuthentication' `
    -PSPath 'IIS:\Sites\Default Web Site' -Name 'enabled' -Value 'true'
```

**Key insight:** Auth is fully external to the application. FastAPI endpoints have no auth dependencies or middleware — IIS rejects unauthenticated requests before they reach uvicorn.

### 5.4 FastAPI Static File Serving (Required for IIS Strategy)

With IIS, FastAPI must serve the frontend `dist/` files in production. Add this to `main.py` — gated on a settings flag so it only activates in production:

```python
from pathlib import Path
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

_FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"

# ... app setup, routers ...

# ── Static file serving (production only) ──
if not settings.debug and _FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=_FRONTEND_DIST / "assets"), name="static")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str) -> FileResponse:
        # Path traversal guard (OWASP A04)
        file = (_FRONTEND_DIST / full_path).resolve()
        if file.is_file() and str(file).startswith(str(_FRONTEND_DIST)):
            return FileResponse(file)
        return FileResponse(_FRONTEND_DIST / "index.html")
```

**Critical ordering rule:** Mount this AFTER all API routers. The SPA catch-all must be the last route.

**Dev behavior:** `settings.debug == True` → static block is skipped → Vite dev server handles frontend.
**Prod behavior:** `settings.debug == False` → FastAPI serves `dist/assets/*` and falls back to `index.html` for SPA routing.

### 5.5 Firewall (IIS)

No per-app firewall rules needed — IIS listens on ports 80/443, which are typically already open. API ports (81xx) stay on localhost.

### 5.6 Verify (IIS)

```powershell
# IIS site running?
Get-Website | Where-Object { $_.State -eq 'Started' }

# Frontend loads?
Invoke-WebRequest -Uri "http://localhost/{subpath}/" -UseBasicParsing -UseDefaultCredentials | Select-Object StatusCode

# API proxied?
(Invoke-WebRequest -Uri "http://localhost/{subpath}/api/v1/{endpoint}" -UseBasicParsing -UseDefaultCredentials).Content

# Health?
(Invoke-WebRequest -Uri "http://localhost/{subpath}/api/health" -UseBasicParsing -UseDefaultCredentials).Content
```

---

## 6. Strategy B — nginx Reverse Proxy Setup

### 6.1 nginx as a Shared Service

nginx runs as a **single NSSM service** serving all apps. Each app gets its own `server {}` block on a different port.

```powershell
# First-time nginx setup
nssm install <org>-nginx-prod "C:\nginx\nginx.exe"
nssm set <org>-nginx-prod AppDirectory "C:\nginx"
nssm set <org>-nginx-prod DisplayName "nginx Reverse Proxy (PROD)"
nssm set <org>-nginx-prod AppStdout "G:\Projects\logs\<org>-nginx-prod-stdout.log"
nssm set <org>-nginx-prod AppStderr "G:\Projects\logs\<org>-nginx-prod-stderr.log"
nssm set <org>-nginx-prod AppRotateFiles 1
nssm set <org>-nginx-prod AppRotateBytes 10485760
nssm set <org>-nginx-prod AppRestartDelay 5000

nssm start <org>-nginx-prod
```

### 6.2 nginx Server Block Template

Add to `C:\nginx\conf\nginx.conf`:

```nginx
server {
    listen {51x3};
    server_name {hostname} localhost;

    location /api/ {
        proxy_pass         http://127.0.0.1:{81x3}/api/;
        proxy_http_version 1.1;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 120s;
    }

    location /health {
        proxy_pass         http://127.0.0.1:{81x3}/health;
        proxy_http_version 1.1;
        proxy_set_header   Host $host;
    }

    location / {
        root G:/Projects/{app-name}/frontend/dist;
        try_files $uri $uri/ /index.html;
        expires 1h;
        add_header Cache-Control "public, no-transform";
    }
}
```

Test and reload:
```powershell
C:\nginx\nginx.exe -t -c C:\nginx\conf\nginx.conf
nssm restart <org>-nginx-prod
```

### 6.3 Firewall (nginx)

```powershell
# Only expose the FE port — API stays on localhost
New-NetFirewallRule -DisplayName "{App Name} ({51x3})" -Direction Inbound -LocalPort {51x3} -Protocol TCP -Action Allow
```

### 6.4 CORS Configuration (nginx only)

When nginx serves on a different port than the API, CORS is needed:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5102",   # Vite dev
        "http://localhost:51x3",   # nginx prod
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**IIS note:** CORS is generally not needed with IIS because the browser hits IIS on the same origin as the page — no cross-origin request occurs.

---

## 7. Environment-Aware Code — The One-Codebase Pattern

The single most important deployment principle: **one codebase serves both dev and prod.** Environment differences are handled by **runtime/build-time detection**, not separate code.

### 7.1 Vite Config — Conditional Base Path

When deployed under a subpath (IIS strategy), asset URLs must include the subpath prefix. Vite bakes this in at build time via the `base` config.

```typescript
// vite.config.ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const isProd = mode === "production";
  const base = isProd ? "/{subpath}/" : "/";

  return {
    base,
    plugins: [react()],
    server: {
      port: 5102,
      proxy: isProd ? undefined : {
        "/api": {
          target: "http://localhost:8102",
          changeOrigin: true,
        },
      },
    },
  };
});
```

**Dev:** `base: "/"`, proxy active → Vite dev server handles everything.
**Prod build:** `base: "/{subpath}/"` → all asset paths in `dist/index.html` prefixed correctly.

If not deploying under a subpath (nginx or root path), keep `base: "/"` for both modes and simplify.

### 7.2 Client-Side Router — basepath Configuration

**This is the most common cause of "Not Found" on subpath deployments.** The reverse proxy (IIS) strips the subpath before forwarding to FastAPI, but the browser URL still shows the subpath. Client-side routers need to know about this prefix.

#### TanStack Router

```typescript
// frontend/src/main.tsx
import { createRouter } from "@tanstack/react-router";

const router = createRouter({
  routeTree,
  basepath: import.meta.env.BASE_URL, // dev: "/", prod: "/{subpath}/"
});
```

#### React Router (v6+)

```tsx
<BrowserRouter basename={import.meta.env.BASE_URL}>
  <Routes>...</Routes>
</BrowserRouter>
```

`import.meta.env.BASE_URL` is automatically set by Vite from the `base` config in `vite.config.ts` (§7.1). This is the single source of truth for the subpath prefix across the entire frontend.

**Why this breaks:** IIS rewrites `/my-app/dashboard` → `/dashboard` server-side. FastAPI serves `index.html`. But the browser URL bar still shows `/my-app/dashboard`. The client-side router sees that URL, and without `basepath`, tries to match `/my-app/dashboard` against your route tree — which only has `/dashboard`. No match → "Not Found".

### 7.3 Axios Client — Dynamic Base URL

```typescript
// frontend/src/api/client.ts
import axios from "axios";

const apiClient = axios.create({
  baseURL: `${import.meta.env.BASE_URL}api/v1`,
  withCredentials: true,  // Required if using Windows Auth (IIS)
});

export default apiClient;
```

`import.meta.env.BASE_URL` is set by Vite automatically from the `base` config:
- Dev: `"/"` → `baseURL = "/api/v1"` → Vite proxy forwards to FastAPI
- Prod (subpath): `"/{subpath}/"` → `baseURL = "/{subpath}/api/v1"` → IIS rewrites to FastAPI

**`withCredentials: true`** is required when the reverse proxy handles auth (e.g. IIS Windows Auth). With nginx or no auth, it's harmless.

### 7.4 Static Asset Fetches — The Hidden Subpath Trap

Router basepath (§7.2) and API baseURL (§7.3) are well-known subpath requirements. **Runtime fetches of files from the `public/` directory are easily missed** because they work fine in dev (where `BASE_URL` is `"/"`) and only break under a subpath.

Examples of static asset fetches that break under a subpath:
- `fetch("/config.json")` — app configuration
- `fetch("/ireland-counties.geojson")` — map data
- `fetch("/manifest.json")` — PWA manifest
- Any `fetch("/<file>")` for files in `public/`

**Fix:** Create a `toAppUrl()` helper and use it everywhere:

```typescript
// frontend/src/lib/utils.ts
export function toAppUrl(path: string): string {
  const base = import.meta.env.BASE_URL ?? "/";
  const stripped = path.startsWith("/") ? path.slice(1) : path;
  return `${base}${stripped}`;
}
```

Usage:
```typescript
// ❌ BAD: Root-absolute — breaks under /my-app/ subpath
const GEOJSON_PATH = "/ireland-counties.geojson";
fetch("/config.json");

// ✅ GOOD: Subpath-aware
import { toAppUrl } from "@/lib/utils";
const GEOJSON_PATH = toAppUrl("ireland-counties.geojson");
fetch(toAppUrl("config.json"));
```

**Detection:** Search for root-absolute fetch patterns that bypass `BASE_URL`:
```bash
grep -rn 'fetch("/' frontend/src/
grep -rn '= "/[a-zA-Z]' frontend/src/
```

**The three categories of subpath-sensitive URLs:**

| Category | What | Where to fix | Reference |
|----------|------|-------------|----------|
| Router basepath | Route matching in browser | `createRouter({ basepath })` | §7.2 |
| API baseURL | Backend API calls | `axios.create({ baseURL })` | §7.3 |
| Static asset fetches | `public/` files loaded at runtime | `toAppUrl()` helper | §7.4 |

All three must use `import.meta.env.BASE_URL`. Missing any one causes prod-only failures.

### 7.5 package.json Build Scripts

```json
{
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "build:prod": "tsc -b && vite build --mode production"
  }
}
```

- `npm run build` — default build (dev mode, `base: "/"`)
- `npm run build:prod` — production build with subpath prefix

### 7.6 FastAPI Settings — Debug Flag

Use a settings property to distinguish dev from prod behavior:

```python
# src/config/settings.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    app_env: str = "development"
    app_port: int = 8102

    @property
    def debug(self) -> bool:
        return self.app_env == "development"
```

`config/.env.api.dev` → `APP_ENV=development` → `debug=True` → no static serving, docs enabled
`config/.env.api.prod` → `APP_ENV=production` → `debug=False` → static serving active, docs disabled

### 7.7 What This Means for Development

| Action | Dev | Prod |
|--------|-----|------|
| Frontend served by | Vite dev server (`:5102`) | FastAPI (IIS) or nginx |
| API requests proxied by | Vite `proxy` config | IIS URL Rewrite or nginx |
| Auth | None | IIS Windows Auth (external) |
| `npm run build` needed? | No (Vite serves source) | Yes (`build:prod`) |
| FastAPI serves `dist/`? | No (`debug=True`) | Yes (IIS strategy) or No (nginx strategy) |

**All behavior switches automatically based on environment config.** You never maintain separate codebases.

---

## 8. NSSM Script (Reusable)

Projects can include a reusable NSSM install script:

```powershell
# Usage:
#   .\nssm-install.ps1 -ProjectShort nps -Port 8103
param(
    [Parameter(Mandatory)][string]$ProjectShort,
    [Parameter(Mandatory)][int]$Port,
    [string]$ProjectRoot = (Get-Location).Path
)

$svcName = "<org>-$ProjectShort-api-prod"
$pythonExe = "$ProjectRoot\.venv\Scripts\python.exe"

nssm install $svcName $pythonExe "-m uvicorn src.api.main:app --host 0.0.0.0 --port $Port"
nssm set $svcName AppDirectory $ProjectRoot
nssm set $svcName AppEnvironmentExtra "APP_ENV=production"
nssm set $svcName AppStdout "$ProjectRoot\logs\$svcName-stdout.log"
nssm set $svcName AppStderr "$ProjectRoot\logs\$svcName-stderr.log"
nssm set $svcName AppRotateFiles 1
nssm set $svcName AppRotateBytes 10485760
nssm set $svcName AppRestartDelay 5000

nssm start $svcName
```

---

## 9. Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| "Unable to load periods" / API 404 | Frontend hitting static server, no proxy to API | Configure reverse proxy (IIS §5 or nginx §6) |
| Assets load but API calls fail on subpath | `vite.config.ts` not setting `base` for prod | Use `defineConfig(({ mode }) => ...)` pattern (§7.1) |
| Site works on prod but breaks after `git pull` | Sysadmin made manual edits — overwritten by pull | Make code environment-aware (§7), never hand-edit on prod |
| Next `npm run build` breaks prod | Build uses wrong mode (no subpath prefix) | Use `npm run build:prod` with `--mode production` (§7.3) |
| 502 Bad Gateway (IIS or nginx) | uvicorn not running | `Get-Service <org>-{short}-api-prod` → restart |
| IIS returns 401 Unauthorized | Windows Auth blocking — user not in AD | Check IIS auth settings, verify user is in allowed AD group |
| IIS returns 404 on subpath routes | URL Rewrite rules missing or wrong order | API rule must come before frontend catch-all (§5.2) |
| `bind() failed` on nginx start | Port already in use | `netstat -ano \| findstr {port}` → stop conflicting process |
| Stale frontend after `git pull` | `dist/` not rebuilt | `cd frontend && npm ci && npm run build:prod` |
| `ENOTEMPTY: rmdir dist/assets` | Process has `dist/` files locked | Stop service → build → restart |
| Service starts then stops immediately | Bad path or missing dependency | Check NSSM stderr log: `Get-Content logs\<org>-{short}-api-prod-stderr.log -Tail 50` |
| `git pull` fails with auth error | Credentials expired or GCM_PROVIDER not set | `git config credential.helper store` + `GCM_PROVIDER=generic` as user env var |
| Unclear whether remote control works | Assumed lack of access without probing | Run Remote Capability Handshake (§3.1) before deciding |
| Frontend shows blank page | SPA routing broken (no catch-all) | IIS: check FastAPI SPA catch-all (§5.4). nginx: check `try_files` (§6.2) |
| Frontend shows blank page (assets 404) | Vite `base` flattened to `"/"` under subpath | Restore `base: mode === "production" ? "/{subpath}/" : "/"` in `vite.config.ts`, rebuild, add deploy guard (§12) |
| Users see old version after deploy | Browser caching stale `index.html` | Add `Cache-Control: no-cache, no-store, must-revalidate` on HTML responses (§13) |
| Frontend shows "Not Found" on subpath | Client-side router missing `basepath` | Add `basepath: import.meta.env.BASE_URL` to router config (§7.2) |
| `Unexpected token '<'` parsing JSON | Static asset fetch uses root-absolute path (`/file.json`) under subpath | Use `toAppUrl()` helper for all `public/` file fetches (§7.4) |
| `withCredentials` CORS error in browser | Missing `allow_credentials=True` or wrong origin | Add CORS config (§6.4) or verify same-origin (IIS usually doesn't need CORS) |

---

## 10. Deploy Checklists (Copy-Paste)

### First-Time Deploy — IIS Strategy

```
- [ ] Git clone on prod + credential setup
- [ ] Python venv + pip install -e .
- [ ] config/.env.api.prod created (APP_ENV=production)
- [ ] Frontend: npm ci && npm run build:prod
- [ ] NSSM: API service registered and started
- [ ] IIS: URL Rewrite + ARR installed and proxy enabled
- [ ] IIS: Two rewrite rules added (API first, then frontend catch-all)
- [ ] IIS: Windows Auth enabled, anonymous disabled (if needed)
- [ ] FastAPI main.py has conditional static serving block (§5.4)
- [ ] vite.config.ts uses defineConfig(({ mode }) => ...) with conditional base (§7.1)
- [ ] client.ts uses import.meta.env.BASE_URL for baseURL (§7.3)
- [ ] Client-side router has basepath set to import.meta.env.BASE_URL (§7.2)
- [ ] All `fetch("/...")` calls for public/ assets use `toAppUrl()` helper (§7.4)
- [ ] Grep for root-absolute fetches: `grep -rn 'fetch("/' frontend/src/` returns no matches
- [ ] Deploy guard: post-build HTML check for `/{subpath}/assets/` prefix (§12.1)
- [ ] Cache-Control: `no-cache` on HTML, `immutable` on hashed assets (§13)
- [ ] Verify: frontend loads, API responds, auth works
```

### First-Time Deploy — nginx Strategy

```
- [ ] Git clone on prod + credential setup
- [ ] Python venv + pip install -e .
- [ ] config/.env.api.prod created (APP_ENV=production)
- [ ] Frontend: npm ci && npm run build
- [ ] NSSM: API service registered and started
- [ ] nginx: server block added, tested, reloaded
- [ ] Firewall: FE port opened (API port NOT exposed)
- [ ] CORS: prod FE port added to FastAPI allow_origins
- [ ] Verify: static files, API proxy, health all return 200
```

### Subsequent Deploy (Both Strategies)

```
- [ ] Remote Capability Handshake run (ping + WSMan + Invoke-Command) (§3.1)
- [ ] git pull on prod
- [ ] pip install -e . (if deps changed)
- [ ] cd frontend && npm ci && npm run build:prod (if FE changed, IIS strategy)
      OR npm run build (nginx strategy)
- [ ] nssm restart <org>-{short}-api-prod
- [ ] Verify app loads and API responds
```

---

## 11. Lessons Learned

Hard-won lessons from real deployments:

1. **One codebase, one repo.** Dev and prod share identical code. Environment differences are handled by build-time mode (`vite --mode production`) and runtime config (`APP_ENV`). Never maintain separate dev/prod codebases.

2. **Auth is infrastructure, not application code.** When IIS handles Windows Auth, FastAPI endpoints have zero auth dependencies. IIS rejects unauthenticated requests before they reach uvicorn. Don't add auth middleware to match prod — it's not needed.

3. **`serve` cannot proxy API calls.** Vercel's `serve` is static-only. `/api/v1/...` requests hit serve → 404. You need a reverse proxy (IIS or nginx) or FastAPI must serve static files. Never use `serve` for apps with API backends.

4. **Sysadmin hand-edits on prod cause `git pull` disasters.** If a sysadmin manually edits `vite.config.ts` or `client.ts` on the prod server, the next `git pull` will overwrite those changes and break the site. Make the code environment-aware in the repo so `git pull` is always safe.

5. **Vite is a BUILD tool, not a runtime.** `vite.config.ts` is read at `npm run build` time. The `base` config gets baked into every asset URL in `dist/index.html`. The file doesn't exist in prod at runtime. If the `base` is wrong at build time, the site breaks — even though the config "looks right" in the repo.

6. **Rebuild frontend after `git pull`.** `git pull` updates source files, not the compiled `dist/` folder. Always run the appropriate build command after pulling frontend changes.

7. **IIS subpath deployment eliminates the need for a separate FE port.** With IIS serving on :80/:443 and rewriting to FastAPI, there is no port 5103 or nginx. One entry point, one port.

8. **API ports stay on localhost.** Only expose the entry-point ports (80/443 for IIS, 51xx for nginx). API ports (81xx) are proxied internally — no external access needed.

9. **`withCredentials: true` in axios is needed for IIS Windows Auth.** Without it, the browser won't send Negotiate/NTLM credentials in the API requests. It's harmless when no auth is used.

10. **Check the NSSM stderr log first** when a service won't start: `Get-Content logs\<org>-{short}-api-prod-stderr.log -Tail 50`.

11. **`GCM_PROVIDER=generic` is required** on Windows Server for git credential storage to work with self-hosted git servers. Set as a persistent user env var.

12. **Port conflicts between apps.** When multiple apps share a prod server, API backends must use different ports. Follow a consistent convention: 8103, 8104, 8105, etc.

13. **Client-side router `basepath` is mandatory for subpath deployments.** When IIS serves an app under `/my-app/`, the browser URL retains that prefix. IIS strips it server-side before forwarding to FastAPI, so FastAPI never sees it. But the client-side router runs in the *browser*, where the URL still has `/my-app/`. Without `basepath` (TanStack Router) or `basename` (React Router), the router can't match any route → "Not Found". This is the #1 gotcha in subpath deployments.

14. **Path traversal guard on SPA catch-all.** The `serve_spa` endpoint resolves file paths from user-supplied URL segments. Always `.resolve()` the path and verify it starts with the `dist/` directory to prevent path traversal attacks (OWASP A04).

15. **Static asset fetches are the hidden third subpath trap.** Router basepath and API baseURL are well-documented. Runtime `fetch("/config.json")` or `fetch("/data.geojson")` from `public/` are not — they work in dev (base is `/`) and silently break in prod under a subpath. The symptom is `Unexpected token '<'` because the root-absolute URL hits the wrong app or fallback page, returning HTML instead of JSON. Prevention: create a `toAppUrl()` helper and audit with `grep -rn 'fetch("/' frontend/src/`.

16. **Probe remote capability before declaring no access.** In Windows environments, agents may be able to execute remote commands via WinRM (`Invoke-Command`) even when interactive RDP control is not available. Always run the Remote Capability Handshake (§3.1) before stating remote access is unavailable.

17. **Never flatten `base` to `"/"` when the app is deployed under a subpath.** The Vite `base` config controls every `<script src>` and `<link href>` in the built `index.html`. Changing `base: mode === "production" ? "/{subpath}/" : "/"` → `base: "/"` causes all asset URLs to lose the subpath prefix. If the server has a catch-all rewrite rule (e.g. a Streamlit proxy at root), those asset requests hit the wrong backend → blank page. This is a silent, catastrophic break that is invisible in dev because dev always uses `base: "/"`.

18. **Deploy guards must validate built HTML before restarting services.** A wrong `base` path produces a valid build (exit code 0) but broken output. The deploy script must check the built `index.html` for the expected asset prefix **before** restarting services. If the check fails, the old working version stays live — the deploy aborts without downtime. See §12.

19. **Cache-Control headers prevent stale HTML after deploys.** Vite hashes asset filenames (`index-Crzj2IZk.js`) so old assets never collide with new ones. But `index.html` has a fixed path — without `no-cache`, browsers serve the old HTML (with old asset hashes) even after a deploy. Set `Cache-Control: no-cache, no-store, must-revalidate` on HTML and `public, max-age=31536000, immutable` on hashed assets. See §13.

---

## 12. Deploy Guards — Post-Build Validation

A deploy guard is a check that runs **after the build but before the service restart**. If the guard fails, the deploy aborts and the currently-running (working) version stays live. This prevents broken builds from causing downtime.

### 12.1 Base Path Guard (IIS Strategy — Required)

When deploying under a subpath, verify the built HTML references the correct asset prefix:

```powershell
# In deploy.ps1 — after vite build, before nssm restart
$indexHtml = Join-Path $frontendDir "dist\index.html"
if (Test-Path $indexHtml) {
    $html = Get-Content $indexHtml -Raw
    if ($html -notmatch '/{subpath}/assets/') {
        throw "DEPLOY GUARD FAILED: Built index.html does not reference /{subpath}/assets/. " +
              "The Vite base path is wrong — aborting deploy before service restart."
    }
    Write-Host "Deploy guard passed: assets reference /{subpath}/"
} else {
    throw "DEPLOY GUARD FAILED: $indexHtml not found after build"
}
```

**Why this matters:** A wrong `base` in `vite.config.ts` produces a successful build (exit 0) but broken output. Without this guard, the deploy script would restart the service, serve the broken HTML, and take the app down. With the guard, the old working version stays live.

### 12.2 CI Build Validation (Belt-and-Suspenders)

The same check should run in CI so the broken build is caught **before** it reaches the deploy step:

```yaml
# In CI workflow — after frontend build step
- name: Validate production base path
  shell: powershell
  working-directory: frontend
  run: |
    $html = Get-Content dist\index.html -Raw
    if ($html -notmatch '/{subpath}/assets/') {
      throw "DEPLOY GUARD: Built index.html does not reference /{subpath}/assets/. " +
            "Check vite.config.ts base setting."
    }
    Write-Host 'Base-path guard passed'
```

**Key:** Build with `--mode production` in CI (not just `vite build`), otherwise the mode-conditional `base` won't activate and the guard will always fail.

### 12.3 Additional Deploy Guards (Optional)

| Guard | What it checks | When to add |
|-------|---------------|-------------|
| **Health endpoint** | API responds 200 after restart | Always |
| **Base path** | Asset prefix in built HTML | Subpath deployments |
| **Dist size** | `dist/` is non-empty and reasonable size | Prevent empty-build deploys |
| **Git SHA convergence** | prod HEAD matches expected commit | Prevent stale-code deploys |

---

## 13. Cache-Control Headers for SPA Serving

When FastAPI serves the built frontend (IIS strategy, §5.4), set appropriate cache headers to ensure browsers always get fresh HTML after deploys while caching hashed assets aggressively.

### 13.1 The Problem

Vite produces content-hashed asset filenames (`index-Crzj2IZk.js`), so old and new assets never collide. But `index.html` has a **fixed path** — without cache-control headers, browsers may serve a cached `index.html` with stale asset references after a deploy. The user sees a blank page or JS errors because the old hashed files no longer exist.

### 13.2 The Fix — Two Cache Policies

```python
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# Cache policies
_NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"}
_LONG_CACHE = {"Cache-Control": "public, max-age=31536000, immutable"}

_FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"

if not settings.debug and _FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=_FRONTEND_DIST / "assets"), name="static")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str) -> FileResponse:
        file = (_FRONTEND_DIST / full_path).resolve()
        if file.is_file() and str(file).startswith(str(_FRONTEND_DIST)):
            # Hashed assets → cache forever; everything else → no cache
            headers = _LONG_CACHE if "/assets/" in full_path else _NO_CACHE
            return FileResponse(file, headers=headers)
        return FileResponse(_FRONTEND_DIST / "index.html", headers=_NO_CACHE)
```

### 13.3 Cache Policy Summary

| Resource | Cache-Control | Why |
|----------|--------------|-----|
| `index.html` (SPA shell) | `no-cache, no-store, must-revalidate` | Must always fetch latest — contains hashed asset references |
| `/assets/*.js`, `/assets/*.css` | `public, max-age=31536000, immutable` | Content-hashed filenames — safe to cache forever |
| Other static files (`favicon.ico`, etc.) | `no-cache, no-store, must-revalidate` | No content hash — may change between deploys |

### 13.4 nginx Equivalent

For the nginx strategy (§6.2), set the same headers in the server block:

```nginx
location / {
    root G:/Projects/{app-name}/frontend/dist;
    try_files $uri $uri/ /index.html;

    # SPA shell — never cache
    location = /index.html {
        add_header Cache-Control "no-cache, no-store, must-revalidate";
        add_header Pragma "no-cache";
        add_header Expires "0";
    }

    # Hashed assets — cache forever
    location /assets/ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
}
```
