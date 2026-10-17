const CACHE_VERSION = 'gongsu-pwa-v10'
const APP_SHELL_CACHE = `${CACHE_VERSION}-shell`
const DATA_CACHE = `${CACHE_VERSION}-data`
const APP_SHELL = ['/']
const FRESH_ASSET_PATHS = new Set([
  '/apple-touch-icon.png',
  '/favicon.ico',
  '/favicon.svg',
  '/gongsu-logo.png',
  '/manifest.webmanifest',
  '/pwa-icon-192.png',
  '/pwa-icon-512.png',
])

self.addEventListener('install', (event) => {
  event.waitUntil(
    Promise.resolve().then(() => caches.open(APP_SHELL_CACHE))
      .then((cache) => cache.addAll(APP_SHELL))
      .catch(() => undefined)
      .then(() => self.skipWaiting()),
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    Promise.resolve().then(() => caches.keys())
      .then((keys) => Promise.all(
        keys
          .filter((key) => key.startsWith('gongsu-pwa-') && !key.startsWith(CACHE_VERSION))
          .map((key) => caches.delete(key)),
      ))
      .catch(() => undefined)
      .then(() => self.clients.claim()),
  )
})

self.addEventListener('fetch', (event) => {
  const { request } = event
  if (request.method !== 'GET') return

  const url = new URL(request.url)
  if (url.origin !== self.location.origin) return

  if (url.pathname.startsWith('/api/cache/') || url.pathname === '/api/app-data') {
    event.respondWith(fetch(request, { cache: 'no-store' }))
    return
  }

  if (url.pathname.startsWith('/api/')) {
    event.respondWith(networkFirst(request, DATA_CACHE, undefined, event))
    return
  }

  if (FRESH_ASSET_PATHS.has(url.pathname)) {
    event.respondWith(networkFirst(request, APP_SHELL_CACHE, undefined, event))
    return
  }

  if (request.mode === 'navigate') {
    // 홈 화면에 설치한 PWA도 새로고침/재진입 시 최신 앱 셸을 먼저 확인한다.
    event.respondWith(networkFirst(request, APP_SHELL_CACHE, { cache: 'reload' }, event))
    return
  }

  event.respondWith(cacheFirst(request, APP_SHELL_CACHE, event))
})

// CacheStorage can be unavailable or full in an installed mobile web app.
// Cache failures must never reject an otherwise successful network response.
async function cachedResponse(request, cacheName) {
  try { return await (await caches.open(cacheName)).match(request) }
  catch { return undefined }
}

async function storeResponse(request, response, cacheName) {
  try { await (await caches.open(cacheName)).put(request, response) }
  catch { /* Storage is best effort; the network response remains usable. */ }
}

function retainCacheWrite(event, operation) {
  try { event.waitUntil(operation) }
  catch { /* An expiring worker must still deliver the network response. */ }
}

async function networkFirst(request, cacheName, fetchOptions, event) {
  try {
    const response = await fetch(request, fetchOptions)
    if (response.ok) retainCacheWrite(event, storeResponse(request, response.clone(), cacheName))
    return response
  } catch (error) {
    const cached = await cachedResponse(request, cacheName)
    if (cached) return cached
    throw error
  }
}

async function cacheFirst(request, cacheName, event) {
  const cached = await cachedResponse(request, cacheName)
  if (cached) return cached
  const response = await fetch(request)
  if (response.ok) retainCacheWrite(event, storeResponse(request, response.clone(), cacheName))
  return response
}
