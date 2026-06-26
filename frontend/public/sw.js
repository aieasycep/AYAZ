// AYAZ Service Worker — offline shell + static asset caching
// Strategy: cache-first for static assets, network-first for API calls

const CACHE_VERSION = 'ayaz-v1';
const STATIC_CACHE = `${CACHE_VERSION}-static`;
const RUNTIME_CACHE = `${CACHE_VERSION}-runtime`;

// App shell routes to pre-cache (Next.js will bust these on deploy via _next/static)
const SHELL_URLS = [
  '/',
  '/dashboard',
  '/login',
  '/offline',
];

// Patterns that should always go network-first (API calls)
const API_PATTERN = /\/api\//;

// ---- Install ----

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then((cache) => {
      // Cache the manifest and icons eagerly
      return cache.addAll([
        '/manifest.json',
        '/icons/icon-192.png',
        '/icons/icon-512.png',
      ]);
    }).then(() => self.skipWaiting())
  );
});

// ---- Activate ----

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key.startsWith('ayaz-') && key !== STATIC_CACHE && key !== RUNTIME_CACHE)
          .map((key) => caches.delete(key))
      )
    ).then(() => self.clients.claim())
  );
});

// ---- Fetch ----

self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Only handle same-origin and https requests
  if (url.origin !== self.location.origin && !url.protocol.startsWith('http')) {
    return;
  }

  // API calls: network-first, no caching
  if (API_PATTERN.test(url.pathname)) {
    event.respondWith(
      fetch(request).catch(() =>
        new Response(JSON.stringify({ error: 'Çevrimdışısınız. Lütfen bağlantınızı kontrol edin.' }), {
          status: 503,
          headers: { 'Content-Type': 'application/json' },
        })
      )
    );
    return;
  }

  // Next.js static assets (_next/static): cache-first with runtime cache
  if (url.pathname.startsWith('/_next/static/')) {
    event.respondWith(
      caches.open(RUNTIME_CACHE).then((cache) =>
        cache.match(request).then((cached) => {
          if (cached) return cached;
          return fetch(request).then((response) => {
            if (response.ok) {
              cache.put(request, response.clone());
            }
            return response;
          });
        })
      )
    );
    return;
  }

  // Next.js image optimization: network-first
  if (url.pathname.startsWith('/_next/image')) {
    event.respondWith(fetch(request).catch(() => caches.match(request)));
    return;
  }

  // Static files in /public (manifest, icons, etc.): cache-first
  if (
    url.pathname.startsWith('/icons/') ||
    url.pathname === '/manifest.json' ||
    url.pathname === '/favicon.ico'
  ) {
    event.respondWith(
      caches.open(STATIC_CACHE).then((cache) =>
        cache.match(request).then((cached) => {
          if (cached) return cached;
          return fetch(request).then((response) => {
            if (response.ok) cache.put(request, response.clone());
            return response;
          });
        })
      )
    );
    return;
  }

  // HTML navigation: network-first, fall back to offline page
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request).catch(() =>
        caches.match('/offline').then((cached) => cached || new Response(
          '<!DOCTYPE html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Çevrimdışı — AYAZ</title><style>body{font-family:-apple-system,sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;background:#f5f6fa;color:#1a1d2e}.box{text-align:center;padding:2rem}h1{font-size:1.5rem;margin-bottom:.5rem}p{color:#6b7280}</style></head><body><div class="box"><h1>Bağlantı yok</h1><p>İnternet bağlantınızı kontrol edin ve sayfayı yenileyin.</p></div></body></html>',
          { headers: { 'Content-Type': 'text/html' } }
        ))
      )
    );
    return;
  }
});
