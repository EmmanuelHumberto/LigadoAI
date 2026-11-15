import test from 'node:test'
import assert from 'node:assert/strict'
import { readBoundedBody,BodyLimitError,BodyTimeoutError } from './bounded_body'
function request(body:ReadableStream<Uint8Array>){return new Request('http://local/',{method:'POST',body,duplex:'half'} as RequestInit)}
test('exact byte boundary preserves UTF8; rejects declared oversize',async()=>{
 const text='a'+String.fromCodePoint(231)+'ao'
 assert.equal(await readBoundedBody(new Request('http://local/',{method:'POST',body:text}),5),text)
 await assert.rejects(readBoundedBody(new Request('http://local/',{method:'POST',body:'abc',headers:{'content-length':'99'}}),5),BodyLimitError)
})
test('chunked oversized input cancelled before full accumulation',async()=>{
 let sent=0,cancelled=false
 const body=new ReadableStream<Uint8Array>({pull(c){sent++;c.enqueue(new Uint8Array(4))},cancel(){cancelled=true}})
 await assert.rejects(readBoundedBody(request(body),8),BodyLimitError);assert.ok(cancelled);assert.ok(sent<=4)
})
test('stalled input times out and cancels',async()=>{
 let cancelled=false
 const body=new ReadableStream<Uint8Array>({cancel(){cancelled=true}})
 await assert.rejects(readBoundedBody(request(body),8,15),BodyTimeoutError);assert.ok(cancelled)
})
