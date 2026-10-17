// Keep an initial/resume read recoverable after its short transport retries fail.
// A healthy read still makes exactly one request; refreshes share an in-flight read.
export function createReadRecovery<T>(options: {
  load: () => Promise<T>
  onSuccess: (data: T, force: boolean) => void
  onError: (error: unknown, force: boolean) => void
  isVisible: () => boolean
  retryDelayMs?: number
}) {
  let stopped = false
  let running = false
  let forcePending = false
  let failures = 0
  let timer: ReturnType<typeof setTimeout> | undefined
  const refresh = async (force = false) => {
    if (stopped) return
    if (running) { forcePending ||= force; return }
    if (timer !== undefined) { clearTimeout(timer); timer = undefined }
    running = true
    try {
      const data = await options.load()
      if (stopped) return
      failures = 0
      options.onSuccess(data, force || forcePending)
    } catch (error) {
      if (stopped) return
      failures += 1
      options.onError(error, force || forcePending)
      if (!(error instanceof Error && 'retryable' in error && error.retryable === false)) {
        const delay = Math.min((options.retryDelayMs ?? 2000) * 2 ** Math.min(failures - 1, 3), 15000)
        const retryForce = force || forcePending
        timer = setTimeout(() => {
          timer = undefined
          if (options.isVisible()) void refresh(retryForce)
        }, delay)
      }
    } finally {
      running = false
      forcePending = false
    }
  }
  return {
    refresh,
    stop() { stopped = true; if (timer !== undefined) clearTimeout(timer) },
  }
}
