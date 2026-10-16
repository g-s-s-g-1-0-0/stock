export async function readRequest(url: RequestInfo | URL, options?: RequestInit, attempts = 3): Promise<Response> {
  const method = options?.method ?? (url instanceof Request ? url.method : 'GET')
  if (method.toUpperCase() !== 'GET') return fetch(url, options)
  for (let attempt = 0; ; attempt += 1) {
    try {
      const timeout = AbortSignal.timeout(12000)
      const originalSignal = options?.signal ?? (url instanceof Request ? url.signal : undefined)
      const signal = originalSignal ? AbortSignal.any([originalSignal, timeout]) : timeout
      const response = await fetch(url, { ...options, cache: 'no-store', signal })
      if (response.ok || ![408, 429, 500, 502, 503, 504].includes(response.status) || attempt + 1 >= attempts) return response
    } catch (error) {
      if (options?.signal?.aborted || (url instanceof Request && url.signal.aborted)) throw error
      if (attempt + 1 >= attempts) throw error
    }
    await new Promise((resolve) => setTimeout(resolve, 300 * 2 ** attempt))
  }
}
