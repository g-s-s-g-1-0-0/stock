const CACHE_VERSION = 'gongsu-pwa-v4'
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
    caches.open(APP_SHELL_CACHE)
      .then((cache) => cache.addAll(APP_SHELL))
      .then(() => self.skipWaiting()),
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys
          .filter((key) => key.startsWith('gongsu-pwa-') && !key.startsWith(CACHE_VERSION))
          .map((key) => caches.delete(key)),
      ))
      .then(() => self.clients.claim()),
  )
})

self.addEventListener('fetch', (event) => {
  const { request } = event
  if (request.method !== 'GET') return

  const url = new URL(request.url)
  if (url.origin !== self.location.origin) return

  if (url.pathname.startsWith('/api/')) {
    event.respondWith(networkFirst(request, DATA_CACHE))
    return
  }

  if (FRESH_ASSET_PATHS.has(url.pathname)) {
    event.respondWith(networkFirst(request, APP_SHELL_CACHE))
    return
  }

  if (request.mode === 'navigate') {
    // 캐시된 앱 셸(인라인 스피너 포함)을 즉시 보여주고 백그라운드에서 갱신한다.
    // networkFirst는 네트워크 응답을 기다리느라 첫 화면(흰 화면)이 지연되므로 사용하지 않는다.
    event.respondWith(staleWhileRevalidate(request, APP_SHELL_CACHE))
    return
  }

  event.respondWith(cacheFirst(request, APP_SHELL_CACHE))
})

async function staleWhileRevalidate(request, cacheName) {
  const cache = await caches.open(cacheName)
  const cached = await cache.match(request)
  const networkPromise = fetch(request)
    .then((response) => {
      if (response && response.ok) {
        void cache.put(request, response.clone())
      }
      return response
    })
    .catch(() => null)
  return cached || (await networkPromise) || fetch(request)
}

async function networkFirst(request, cacheName) {
  const cache = await caches.open(cacheName)
  try {
    const response = await fetch(request)
    if (response.ok) {
      await cache.put(request, response.clone())
    }
    return response
  } catch (error) {
    const cached = await cache.match(request)
    if (cached) return cached
    throw error
  }
}

async function cacheFirst(request, cacheName) {
  const cache = await caches.open(cacheName)
  const cached = await cache.match(request)
  if (cached) return cached

  const response = await fetch(request)
  if (response.ok) {
    await cache.put(request, response.clone())
  }
  return response
}
