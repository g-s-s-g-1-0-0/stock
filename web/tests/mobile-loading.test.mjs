import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { afterEach, mock, test } from 'node:test'
import vm from 'node:vm'
import ts from 'typescript'

async function sourceModule(file) {
  const { outputText } = ts.transpileModule(readFileSync(new URL(file, import.meta.url), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2023 },
  })
  return import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)
}
const { readRequest } = await sourceModule('../src/readRequest.ts')
const { createReadRecovery } = await sourceModule('../src/readRecovery.ts')
afterEach(() => mock.restoreAll())
const failedBody = () => new Response(new ReadableStream({ start(controller) { controller.error(new TypeError('Load failed')) } }))
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

test('iOS body transfer fails after headers: automatically retry the complete GET', async () => {
  let calls = 0
  mock.method(globalThis, 'fetch', async () => ++calls === 1 ? failedBody() : Response.json({ready:true}))
  assert.deepEqual(await (await readRequest('/api/app-data')).json(), {ready:true})
  assert.equal(calls, 2)
})

test('production app-data startup recovers a body failure before exposing a loading error', async () => {
  const source = readFileSync(new URL('../src/api.ts', import.meta.url), 'utf8')
    .replace("import { readRequest } from './readRequest'", `const readRequest = ${readRequest.toString()}`)
    .replaceAll('import.meta.env', '({ PROD: true, DEV: false })')
  const { outputText } = ts.transpileModule(source, {compilerOptions:{module:ts.ModuleKind.ESNext}})
  const { fetchAppData } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)
  let calls = 0
  const payload = Object.fromEntries(['stocks','valuation','technical','marketEvents','marketTrends','tradeLogs'].map((key)=>[key,{rows:[]}]))
  mock.method(globalThis,'fetch',async()=>++calls===1 ? failedBody() : Response.json(payload))
  const [a,b] = await Promise.all([fetchAppData(),fetchAppData()])
  assert.deepEqual(a,payload); assert.deepEqual(b,payload); assert.equal(calls,2)
})

test('reads work without the newer AbortSignal.any/timeout APIs', async () => {
  mock.method(AbortSignal, 'any', () => { throw new TypeError('unsupported') })
  mock.method(AbortSignal, 'timeout', () => { throw new TypeError('unsupported') })
  const caller = new AbortController()
  mock.method(globalThis, 'fetch', async () => Response.json({ready:true}))
  assert.deepEqual(await (await readRequest('/account', {signal:caller.signal})).json(), {ready:true})
})

test('timeout covers a stalled response body, not just response headers', async () => {
  let calls = 0
  mock.method(globalThis, 'fetch', async (_url, options) => {
    if (++calls > 1) return Response.json({ready:true})
    return new Response(new ReadableStream({start(controller) {
      options.signal.addEventListener('abort', () => controller.error(options.signal.reason), {once:true})
    }}))
  })
  assert.deepEqual(await (await readRequest('/api/app-data', undefined, 2, 10)).json(), {ready:true})
  assert.equal(calls, 2)
})

test('cancellation does not issue a request and empty responses stay valid', async () => {
  const controller = new AbortController(); controller.abort()
  let calls = 0
  mock.method(globalThis, 'fetch', async () => {calls++; return new Response(null,{status:204})})
  await assert.rejects(readRequest('/account', {signal:controller.signal}), {name:'AbortError'})
  assert.equal(calls,0)
  assert.equal((await readRequest('/account')).status,204)
  assert.equal(calls,1)
})

test('initial failure automatically recovers without reload and shares concurrent reads', async () => {
  let calls = 0
  const success = []
  const errors = []
  const recovery = createReadRecovery({
    load: async () => { if (++calls === 1) throw new TypeError('Load failed'); return {ready:true} },
    onSuccess: (data, force) => success.push([data,force]), onError: (e) => errors.push(e),
    isVisible: () => true, retryDelayMs:1,
  })
  try {
    await Promise.all([recovery.refresh(true),recovery.refresh()])
    await wait(25)
    assert.equal(calls,2); assert.equal(errors.length,1)
    assert.deepEqual(success,[[{ready:true},true]])
    await recovery.refresh()
    assert.equal(calls,3) // No perpetual polling after recovery.
  } finally {recovery.stop()}
})

test('hidden app defers retry until resume and unmount cancels retries', async () => {
  let visible = false, calls = 0
  const recovery = createReadRecovery({load: async () => {calls++; throw new TypeError('Load failed')},
    onSuccess: () => {}, onError: () => {}, isVisible: () => visible, retryDelayMs:1})
  await recovery.refresh(); await wait(20); assert.equal(calls,1)
  visible = true
  await recovery.refresh(); assert.equal(calls,2)
  recovery.stop(); await wait(20); assert.equal(calls,2)
})

test('old account read cannot apply its result after a session change', async () => {
  let complete
  let applied = false
  const recovery = createReadRecovery({load: () => new Promise((resolve) => {complete=resolve}),
    onSuccess: () => {applied=true}, onError: () => {}, isVisible: () => true})
  const request = recovery.refresh()
  recovery.stop(); complete({oldAccount:true}); await request
  assert.equal(applied,false)
})

test('permanent read failures do not start an automatic retry loop', async () => {
  let calls = 0
  const recovery = createReadRecovery({load: async () => {calls++; throw Object.assign(new Error('Forbidden'),{retryable:false})},
    onSuccess: () => {}, onError: () => {}, isVisible: () => true, retryDelayMs:1})
  try {await recovery.refresh(); await wait(20); assert.equal(calls,1)} finally {recovery.stop()}
})

function worker(caches, fetcher) {
  const listeners = {}
  const context = {URL, caches, fetch:fetcher,
    self:{location:{origin:'https://app.example'},addEventListener:(name,fn)=>{listeners[name]=fn},
      clients:{claim:async()=>{}},skipWaiting:async()=>{}},
  }
  vm.runInNewContext(readFileSync(new URL('../public/sw.js',import.meta.url),'utf8'),context)
  const read = async (path,mode='cors') => {
    let response
    const tasks = []
    listeners.fetch({request:{method:'GET',url:`https://app.example${path}`,mode},
      respondWith:(value)=>{response=value},waitUntil:(task)=>tasks.push(task)})
    const result = await response
    await Promise.all(tasks)
    return result
  }
  read.lifecycle = async (name) => {
    const tasks = []
    listeners[name]({waitUntil:(task)=>tasks.push(task)})
    await Promise.all(tasks)
  }
  return read
}

for (const failure of ['unavailable','quota']) {
  test(`PWA ${failure} cache never breaks a healthy page or asset response`, async () => {
    const caches = {open:async()=>{
      if (failure==='unavailable') throw new Error('CacheStorage unavailable')
      return {match:async()=>undefined,put:async()=>{throw new Error('QuotaExceededError')}}
    }}
    const read = worker(caches,async()=>new Response('network data'))
    assert.equal(await (await read('/','navigate')).text(),'network data')
    assert.equal(await (await read('/assets/app.js')).text(),'network data')
  })
}

test('PWA live-data failures never substitute a stale cached market snapshot', async () => {
  let cacheReads = 0
  const read = worker({open:async()=>{cacheReads++;return {match:async()=>Response.json({stale:true})}}},
    async()=>{throw new TypeError('Load failed')})
  await assert.rejects(read('/api/app-data'),/Load failed/)
  assert.equal(cacheReads,0)
})

test('PWA installs and activates even when CacheStorage synchronously throws', async () => {
  const read=worker({open:()=>{throw new Error('Storage unavailable')},keys:()=>{throw new Error('Storage unavailable')}},async()=>new Response('fresh'))
  await read.lifecycle('install')
  await read.lifecycle('activate')
  assert.equal(await (await read('/','navigate')).text(),'fresh')
})
