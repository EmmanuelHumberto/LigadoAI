import test from 'node:test'
import assert from 'node:assert/strict'
import {mkdtempSync, mkdirSync, writeFileSync, unlinkSync, rmdirSync, readFileSync} from 'node:fs'
import {tmpdir} from 'node:os'
import {join, resolve} from 'node:path'
import {spawnSync} from 'node:child_process'

test('startup loads private parent env; missing env fails before starting a listener', () => {
  const root=mkdtempSync(join(tmpdir(),'opentracy-start-env-'))
  const cwd=join(root,'backend');mkdirSync(cwd)
  const packageJson=JSON.parse(readFileSync(new URL('../package.json',import.meta.url),'utf8'))
  const args=packageJson.scripts.start.split(' ')
  assert.equal(args[0],'node');assert.equal(args.at(-1),'api/server.ts')
  const flags=args.slice(1,-1)
  const importAt=flags.indexOf('--import');assert.ok(importAt>=0)
  flags[importAt+1]=import.meta.resolve('tsx')
  const env={...process.env};delete env.SYSTEMOS_COGNITIVE_TOKEN
  const file=join(root,'.env')
  try {
    writeFileSync(file,'SYSTEMOS_COGNITIVE_TOKEN=synthetic-startup-only\n',{mode:0o600})
    const result=spawnSync(process.execPath,[...flags,'--eval',"if(process.env.SYSTEMOS_COGNITIVE_TOKEN!=='synthetic-startup-only')process.exit(1);console.log('CONFIG_LOADED')"],{cwd,env,encoding:'utf8'})
    assert.equal(result.status,0,result.stderr);assert.match(result.stdout,/CONFIG_LOADED/)
    assert.equal((result.stdout+result.stderr).includes('synthetic-startup-only'),false)
    unlinkSync(file)
    const missing=spawnSync(process.execPath,[...flags,'--eval',"console.log('LISTENER_STARTED')"],{cwd,env,encoding:'utf8'})
    assert.notEqual(missing.status,0);assert.equal(missing.stdout.includes('LISTENER_STARTED'),false)
  }finally{rmdirSync(cwd);rmdirSync(root)}
})
