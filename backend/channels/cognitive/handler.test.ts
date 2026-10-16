import test from 'node:test'
import assert from 'node:assert/strict'
import { createCognitiveRouter } from './handler'

test('proxy requires auth, only forwards canonical routes and bounds input', async () => {
  process.env.SYSTEMOS_COGNITIVE_TOKEN = 'test-token'
  process.env.OPENTRACY_KNOWLEDGE_AUTH_TOKEN = 'runtime-test-token'
  let calls = 0
  const router = createCognitiveRouter((async (url, options) => {
    calls++
    assert.match(String(url), /\/knowledge\/index$/)
    assert.equal((options?.headers as Record<string,string>).authorization, 'Bearer runtime-test-token')
    return new Response(JSON.stringify({job_id:'test-job'}), {status:200})
  }) as typeof fetch)
  assert.equal((await router.request('/knowledge/index', {method:'POST'})).status, 401)
  const headers = {authorization:'Bearer test-token'}
  assert.equal((await router.request('/knowledge/documents', {headers})).status, 404)
  assert.equal((await router.request('/knowledge/index', {method:'POST',headers,body:'x'.repeat(164000)})).status, 413)
  const response = await router.request('/knowledge/index', {method:'POST',headers,body:'{}'})
  assert.equal(response.status, 200)
  assert.equal(calls, 1)
})
