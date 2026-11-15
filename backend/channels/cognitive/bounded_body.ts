/** Bound streaming input before materialization. */
export class BodyLimitError extends Error {}
export class BodyTimeoutError extends Error {}
export async function readBoundedBody(request:Request,limit=160*1024,timeoutMs=10000):Promise<string>{
 const declared=request.headers.get('content-length')
 if(declared && (!/^\d+$/.test(declared)||Number(declared)>limit)){
  await request.body?.cancel();throw new BodyLimitError()
 }
 if(!request.body)return ''
 const reader=request.body.getReader(),chunks:Uint8Array[]=[]
 let size=0,failed=false,timer:ReturnType<typeof setTimeout>|undefined
 const expired=new Promise<never>((_,reject)=>{
  timer=setTimeout(()=>{failed=true;reject(new BodyTimeoutError());void reader.cancel().catch(()=>{})},timeoutMs)
 })
 try{
  while(true){
   const part=await Promise.race([reader.read(),expired])
   if(part.done)break
   size+=part.value.byteLength
   if(size>limit){failed=true;throw new BodyLimitError()}
   chunks.push(part.value)
  }
  if(failed)throw new BodyTimeoutError()
  return Buffer.concat(chunks,size).toString('utf8')
 }finally{
  clearTimeout(timer)
  if(failed)void reader.cancel().catch(()=>{})
  reader.releaseLock()
 }
}
