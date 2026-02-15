// Chess Trainer — Service Worker (offline static asset caching)

const CACHE_NAME = 'chess-trainer-v1';

const PRECACHE_URLS = [
    '/',
    '/static/css/style.css',
    '/static/js/training.js',
    '/static/vendor/chess.min.js',
    '/static/vendor/chessboard-1.0.0.min.js',
    '/static/vendor/chessboard-1.0.0.min.css',
    '/static/icons/icon.svg',
    '/static/icons/icon-192.png',
    '/manifest.json',
];

// Install: pre-cache static assets
self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            return cache.addAll(PRECACHE_URLS);
        })
    );
    self.skipWaiting();
});

// Activate: purge old caches
self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((cacheNames) => {
            return Promise.all(
                cacheNames
                    .filter((name) => name !== CACHE_NAME)
                    .map((name) => caches.delete(name))
            );
        })
    );
    self.clients.claim();
});

// Fetch: cache-first for static, network-first for pages, network-only for API
self.addEventListener('fetch', (event) => {
    const url = new URL(event.request.url);

    // Network-only for API requests
    if (url.pathname.startsWith('/api/')) {
        return;
    }

    // Cache-first for static assets
    if (url.pathname.startsWith('/static/') || url.pathname === '/manifest.json') {
        event.respondWith(
            caches.match(event.request).then((cached) => {
                return cached || fetch(event.request).then((response) => {
                    if (response.ok) {
                        const clone = response.clone();
                        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
                    }
                    return response;
                });
            })
        );
        return;
    }

    // Network-first for HTML pages (fallback to cache)
    if (event.request.mode === 'navigate') {
        event.respondWith(
            fetch(event.request).then((response) => {
                if (response.ok) {
                    const clone = response.clone();
                    caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
                }
                return response;
            }).catch(() => {
                return caches.match(event.request);
            })
        );
    }
});
