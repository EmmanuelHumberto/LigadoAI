import test from 'node:test'
import assert from 'node:assert/strict'
import { Hono } from 'hono'
import { apiKeyAuth,assertApiKeysConfigured } from './api_key'
test('missing keys fail closed; credential rejection and rotation preserve valid access',async()=>{
 const previous=process.env.BACKEND_API_KEYS
 try{
  const app=new Hono().use('*',apiKeyAuth).get('/',c=>c.text('protected'))
  delete process.env.BACKEND_API_KEYS;assert.throws(assertApiKeysConfigured)
  assert.equal((await app.request('/')).status,503)
  process.env.BACKEND_API_KEYS='old-test-key,new-test-key';assert.doesNotThrow(assertApiKeysConfigured)
  for(const authorization of ['','Basic old-test-key','Bearer bad','Bearer xxx-test-key'])assert.equal((await app.request('/',{headers:{authorization}})).status,401)
  for(const key of ['old-test-key','new-test-key']){
   const r=await app.request('/',{headers:{authorization:'Bearer '+key}})
   assert.equal(r.status,200);assert.equal(await r.text(),'protected')
  }
  process.env.BACKEND_API_KEYS='new-test-key'
  assert.equal((await app.request('/',{headers:{authorization:'Bearer old-test-key'}})).status,401)
 }finally{if(previous===undefined)delete process.env.BACKEND_API_KEYS;else process.env.BACKEND_API_KEYS=previous}
})
