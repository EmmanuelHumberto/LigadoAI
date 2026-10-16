/** Canonical operational endpoints; no arbitrary URL or catch-all proxy. */
import { timingSafeEqual } from 'node:crypto'
import { Hono } from 'hono'

export function createCognitiveRouter(request: typeof fetch = fetch) {
  const router = new Hono()
  const allowed = [
    ['POST', /^\/knowledge\/index$/], ['GET', /^\/knowledge\/jobs\/[0-9a-f-]{36}$/i],
    ['POST', /^\/v3\/operational\/resolve-capture$/], ['POST', /^\/v3\/diagnosis$/],
    ['POST', /^\/v3\/diagnosis\/[0-9a-f-]{36}\/retry$/i],
    ['GET', /^\/v3\/diagnosis\/[0-9a-f-]{36}$/i],
  ] as const
  router.all('*', async c => {
    const path = c.req.path
    if (!allowed.some(([method, pattern]) => method === c.req.method && pattern.test(path))) return c.json({error: 'not_found'}, 404)
    const expected = process.env.SYSTEMOS_COGNITIVE_TOKEN ?? ''
    const actual = c.req.header('authorization')?.replace(/^Bearer /, '') ?? ''
    if (!expected || Buffer.byteLength(actual) !== Buffer.byteLength(expected) || !timingSafeEqual(Buffer.from(actual), Buffer.from(expected))) return c.json({error: 'unauthorized'}, 401)
    const text = c.req.method === 'POST' ? await c.req.text() : undefined
    if (text && Buffer.byteLength(text) > 160 * 1024) return c.json({error: 'payload_too_large'}, 413)
    const token = path.startsWith('/knowledge/') ? process.env.OPENTRACY_KNOWLEDGE_AUTH_TOKEN
      : (process.env.OPENTRACY_COUS_V3_AUTH_TOKEN || process.env.OPENTRACY_KNOWLEDGE_AUTH_TOKEN)
    try {
      const response = await request((process.env.RUNTIME_URL ?? 'http://127.0.0.1:8001').replace(/\/$/, '') + path, {
        method: c.req.method, headers: {'content-type': 'application/json', ...(token ? {authorization: `Bearer ${token}`} : {})},
        body: text, signal: AbortSignal.timeout(90000), redirect: 'error',
      })
      return new Response(response.body, {status: response.status, headers: {'content-type': 'application/json', 'cache-control': 'no-store'}})
    } catch { return c.json({error: 'runtime_unavailable'}, 502) }
  })
  return router
}

export const cognitiveRouter = createCognitiveRouter()
