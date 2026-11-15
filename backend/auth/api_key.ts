import { timingSafeEqual } from 'node:crypto'
import type { MiddlewareHandler } from 'hono'
function loadKeys(): string[] {
 return (process.env.BACKEND_API_KEYS ?? '').split(',').map(key=>key.trim()).filter(Boolean)
}
export function assertApiKeysConfigured(): void {
 if(loadKeys().length===0)throw new Error('BACKEND_API_KEYS must be configured')
}
export const apiKeyAuth: MiddlewareHandler=async(c,next)=>{
 const keys=loadKeys()
 if(keys.length===0)return c.json({error:'authentication_unavailable'},503)
 const match=/^Bearer\s+(.+)$/i.exec(c.req.header('Authorization')??'')
 if(!match)return c.json({error:'unauthorized'},401)
 const actual=Buffer.from(match[1].trim())
 let accepted=false
 for(const key of keys){
  const expected=Buffer.from(key)
  if(actual.length===expected.length && timingSafeEqual(actual,expected))accepted=true
 }
 if(!accepted)return c.json({error:'unauthorized'},401)
 c.header('x-auth-mode','api-key');return next()
}
