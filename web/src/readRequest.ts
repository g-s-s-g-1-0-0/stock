// Buffer GET bodies inside the retry/timeout boundary. Safari can reject a body
// read with "Load failed" after fetch itself has already returned successfully.
export async function readRequest(url: RequestInfo | URL, options?: RequestInit, attempts = 3, timeoutMs = 20000): Promise<Response> {
  const method = options?.method ?? (url instanceof Request ? url.method : 'GET')
  if (method.toUpperCase() !== 'GET') return fetch(url, options)
  const originalSignal = options?.signal ?? (url instanceof Request ? url.signal : undefined)
  for (let attempt = 0; ; attempt += 1) {
    if (originalSignal?.aborted) throw originalSignal.reason ?? new DOMException('Read cancelled', 'AbortError')
    const controller = new AbortController()
    const abort = () => controller.abort(originalSignal?.reason)
    if (originalSignal?.aborted) abort()
    else originalSignal?.addEventListener('abort', abort, { once: true })
    // AbortSignal.any/timeout are unavailable in some installed iOS web apps.
    const timer = setTimeout(() => controller.abort(new DOMException('Read timed out', 'TimeoutError')), timeoutMs)
    try {
      const response = await fetch(url, { ...options, cache: 'no-store', signal: controller.signal })
      if ([408, 429, 500, 502, 503, 504].includes(response.status) && attempt + 1 < attempts) {
        void response.body?.cancel().catch(() => undefined)
      } else {
        const body = await response.arrayBuffer()
        const buffered = new Response([204, 205, 304].includes(response.status) ? null : body, {
          status: response.status, statusText: response.statusText, headers: response.headers,
        })
        for (const key of ['url', 'redirected', 'type'] as const) {
          Object.defineProperty(buffered, key, { value: response[key] })
        }
        return buffered
      }
    } catch (error) {
      if (originalSignal?.aborted || attempt + 1 >= attempts) throw error
    } finally {
      clearTimeout(timer)
      originalSignal?.removeEventListener('abort', abort)
    }
    await new Promise((resolve) => setTimeout(resolve, 500 * 2 ** attempt))
  }
}
