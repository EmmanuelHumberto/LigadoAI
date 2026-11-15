import test from 'node:test'
import assert from 'node:assert/strict'
import { createRuntimeFetch, assertRuntimeAuthenticationConfigured } from './runtime_fetch'
test('internal token stays on runtime requests and ignores spoofed input', async () => {
 const old = {...process.env}
 try {
  process.env.OPENTRACY_RUNTIME_SECURITY='required'
  process.env.OPENTRACY_RUNTIME_INTERNAL_TOKEN='private-test-token'
  process.env.RUNTIME_URL='http://127.0.0.1:8001'
  let seen:Headers|undefined
  let redirect:RequestRedirect|undefined
  const transport=createRuntimeFetch((async(_input, init)=>{seen=new Headers(init?.headers);redirect=init?.redirect;return new Response('ok')}) as typeof fetch)
  await transport('http://127.0.0.1:8001/policy',{headers:{authorization:'Bearer public-token','x-opentracy-runtime-key':'spoof'}})
  assert.equal(seen?.get('x-opentracy-runtime-key'),'private-test-token')
  assert.equal(redirect,'error')
  assert.equal(seen?.get('authorization'),'Bearer public-token')
  await transport('https://slack.com/api/chat.postMessage',{headers:{'x-opentracy-runtime-key':'spoof'}})
  assert.equal(seen?.get('x-opentracy-runtime-key'),null)
  delete process.env.OPENTRACY_RUNTIME_INTERNAL_TOKEN
  await assert.rejects(transport('http://127.0.0.1:8001/policy'))
 } finally {
  for(const key of ['OPENTRACY_RUNTIME_SECURITY','OPENTRACY_RUNTIME_INTERNAL_TOKEN','RUNTIME_URL']){
   if(old[key]===undefined)delete process.env[key];else process.env[key]=old[key]
  }
 }
})

test('startup rejects absent, weak or unknown security configuration',()=>{
 const mode=process.env.OPENTRACY_RUNTIME_SECURITY,token=process.env.OPENTRACY_RUNTIME_INTERNAL_TOKEN
 try {
  process.env.OPENTRACY_RUNTIME_SECURITY='required'
  delete process.env.OPENTRACY_RUNTIME_INTERNAL_TOKEN
  assert.throws(assertRuntimeAuthenticationConfigured)
  process.env.OPENTRACY_RUNTIME_INTERNAL_TOKEN='weak';assert.throws(assertRuntimeAuthenticationConfigured)
  process.env.OPENTRACY_RUNTIME_INTERNAL_TOKEN='t'.repeat(32);assert.doesNotThrow(assertRuntimeAuthenticationConfigured)
  process.env.OPENTRACY_RUNTIME_SECURITY='requried';assert.throws(assertRuntimeAuthenticationConfigured)
 }finally{
  if(mode===undefined)delete process.env.OPENTRACY_RUNTIME_SECURITY;else process.env.OPENTRACY_RUNTIME_SECURITY=mode
  if(token===undefined)delete process.env.OPENTRACY_RUNTIME_INTERNAL_TOKEN;else process.env.OPENTRACY_RUNTIME_INTERNAL_TOKEN=token
 }
})

test('real HTTP redirect cannot forward the internal key to another listener',async()=>{
 const {createServer}=await import('node:http')
 const {runtimeFetch}=await import('./runtime_fetch')
 let externalCalls=0
 const external=createServer((_req,res)=>{externalCalls++;res.end('external')})
 const origin=createServer((_req,res)=>{res.writeHead(302,{location:'http://127.0.0.1:'+String((external.address() as import('node:net').AddressInfo).port)+'/outside'});res.end()})
 const previousUrl=process.env.RUNTIME_URL,previousToken=process.env.OPENTRACY_RUNTIME_INTERNAL_TOKEN
 try{
  await new Promise<void>(resolve=>external.listen(0,'127.0.0.1',resolve))
  await new Promise<void>(resolve=>origin.listen(0,'127.0.0.1',resolve))
  process.env.RUNTIME_URL='http://127.0.0.1:'+String((origin.address() as import('node:net').AddressInfo).port)
  process.env.OPENTRACY_RUNTIME_INTERNAL_TOKEN='t'.repeat(32)
  await assert.rejects(runtimeFetch(process.env.RUNTIME_URL+'/policy'))
  assert.equal(externalCalls,0)
 }finally{
  if(previousUrl===undefined)delete process.env.RUNTIME_URL;else process.env.RUNTIME_URL=previousUrl
  if(previousToken===undefined)delete process.env.OPENTRACY_RUNTIME_INTERNAL_TOKEN;else process.env.OPENTRACY_RUNTIME_INTERNAL_TOKEN=previousToken
  origin.closeAllConnections();external.closeAllConnections()
  await Promise.all([new Promise<void>(resolve=>origin.close(()=>resolve())),new Promise<void>(resolve=>external.close(()=>resolve()))])
 }
})
