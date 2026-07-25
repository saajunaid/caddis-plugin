# PWA Checklist

Full Progressive Web App setup for a responsive web app that behaves like a
native app on iOS and Android — including "Add to Home Screen", splash screen,
status bar theming, and offline resilience.

---

## Minimum Viable PWA (Always Apply)

These are required for any mobile web app, even if full offline support isn't needed.

### 1. Viewport Meta (in `<head>`)

```html
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
```

### 2. Theme and App Meta Tags (in `<head>`)

```html
<!-- Android Chrome theme colour (status bar, address bar) -->
<meta name="theme-color" content="#E10A0A" />

<!-- iOS: enable standalone mode (hides browser chrome) -->
<meta name="apple-mobile-web-app-capable" content="yes" />
<meta name="apple-mobile-web-app-status-bar-style" content="default" />
<!-- Options: default | black | black-translucent -->

<!-- iOS: app name on home screen -->
<meta name="apple-mobile-web-app-title" content="App Name" />

<!-- Android: enable standalone mode -->
<meta name="mobile-web-app-capable" content="yes" />

<!-- Manifest link -->
<link rel="manifest" href="/manifest.json" />
```

### 3. Web App Manifest (`/public/manifest.json`)

```json
{
  "name": "Appointment Assist",
  "short_name": "Appt Assist",
  "description": "Truck roll screening and dispatch intelligence",
  "start_url": "/",
  "scope": "/",
  "display": "standalone",
  "orientation": "any",
  "background_color": "#F8F7F5",
  "theme_color": "#E10A0A",
  "icons": [
    {
      "src": "/icons/icon-192.png",
      "sizes": "192x192",
      "type": "image/png",
      "purpose": "any maskable"
    },
    {
      "src": "/icons/icon-512.png",
      "sizes": "512x512",
      "type": "image/png",
      "purpose": "any maskable"
    }
  ]
}
```

**`display` options**:
- `standalone` — hides browser URL bar, back button. Feels most native.
- `minimal-ui` — shows minimal browser UI (back button). Safer if navigation needs browser back.
- `browser` — normal browser tab. Defeats the purpose.

Use `standalone` for internal tools. Use `minimal-ui` if the app has complex
routing where users might need the browser back button as fallback.

### 4. Icons

Minimum required icon sizes:
- 192×192 (Android home screen, Chrome)
- 512×512 (Android splash screen, PWA install prompt)

Recommended additional sizes for full coverage:
- 180×180 (iOS "apple-touch-icon")
- 32×32 (browser favicon)
- 16×16 (browser tab)

```html
<!-- iOS home screen icon (place in <head>) -->
<link rel="apple-touch-icon" sizes="180x180" href="/icons/icon-180.png" />
<link rel="icon" type="image/png" sizes="32x32" href="/icons/icon-32.png" />
```

Icons should use `"purpose": "maskable"` in the manifest so Android can apply
its adaptive icon mask (rounded square, circle, etc.) without clipping the design.
Ensure the icon's safe zone occupies the inner 80% of the canvas.

---

## Splash Screen

iOS generates a splash screen automatically if you provide correctly-sized
"apple-touch-startup-image" assets. The minimum approach is to let the browser
generate it from `background_color` + the app icon.

For a branded splash screen with precise control, provide device-specific images:

```html
<!-- iPhone 14 Pro Max -->
<link rel="apple-touch-startup-image"
  href="/splash/splash-1290x2796.png"
  media="(device-width: 430px) and (device-height: 932px) and (-webkit-device-pixel-ratio: 3)" />
<!-- Add entries for each target device size -->
```

This is optional for internal tools. The auto-generated splash (colour + icon)
is acceptable and requires no additional work.

---

## Service Worker (Optional but Recommended)

A service worker enables offline resilience — the app loads even with no network,
and API failures degrade gracefully instead of showing a blank screen.

### When to add a service worker

**Add it if**: The app is used in the field (engineers, field workers) where
mobile data connectivity may be unreliable.

**Skip it if**: The app is always used on a reliable network (office, VPN).

### Minimal service worker (cache-first for static assets)

Register in your app entry point:

```js
// main.js or index.js
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js')
      .catch(err => console.warn('SW registration failed:', err));
  });
}
```

```js
// /public/sw.js — cache shell assets, network-first for API calls
const CACHE_NAME = 'app-shell-v1';
const SHELL_ASSETS = ['/', '/index.html', '/manifest.json'];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(SHELL_ASSETS))
  );
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);

  // Network-first for API calls
  if (url.pathname.startsWith('/api/')) {
    e.respondWith(
      fetch(e.request).catch(() => new Response('{"error":"offline"}',
        { headers: { 'Content-Type': 'application/json' } }))
    );
    return;
  }

  // Cache-first for static assets
  e.respondWith(
    caches.match(e.request).then(cached => cached || fetch(e.request))
  );
});
```

### Using a build tool plugin (recommended)

If the project uses Vite, use `vite-plugin-pwa`. If using Create React App / Webpack,
use `workbox-webpack-plugin`. These handle cache versioning, asset fingerprinting,
and update notifications automatically — do not write a service worker by hand
unless the project has no build tooling.

```js
// vite.config.js
import { VitePWA } from 'vite-plugin-pwa'

export default {
  plugins: [
    VitePWA({
      registerType: 'autoUpdate',
      manifest: { /* same as manifest.json above */ }
    })
  ]
}
```

---

## Installability Checklist

For "Add to Home Screen" / install prompt to appear on Android Chrome, the app must:

- [ ] Be served over HTTPS (or localhost for dev)
- [ ] Have a valid `manifest.json` with `name`, `short_name`, `start_url`, `display: standalone`, `icons` (192 + 512)
- [ ] Have a registered service worker
- [ ] The service worker must have fetched and cached at least one resource

iOS Safari does not show an install prompt — users must manually use
"Share → Add to Home Screen". This is a platform limitation, not a fixable bug.

---

## Status Bar Colour on iOS

The `apple-mobile-web-app-status-bar-style` meta tag controls the iOS status bar:

| Value | Effect |
|---|---|
| `default` | White status bar background, dark text/icons |
| `black` | Black status bar background, white text/icons |
| `black-translucent` | Content renders behind status bar, status bar is transparent with white text. Requires `padding-top: env(safe-area-inset-top)` on your layout. |

For most apps, use `default` unless your app has a dark header where `black` looks better.
`black-translucent` gives the most immersive look but requires careful layout handling.
