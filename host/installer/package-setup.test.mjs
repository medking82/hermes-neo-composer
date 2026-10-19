import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { desktopFixture } from './desktop-fixture.mjs'
import { assembleSetupPackage } from './package-setup.mjs'
import { runSetup } from './setup.mjs'

test('standalone packaging copies only pinned payloads and executes the existing transaction',t=>{
 const f=desktopFixture(t),destination=path.join(f.area,'standalone')
 f.put(f.bundle,'unrelated-private.txt','fixture-not-for-distribution')
 const result=assembleSetupPackage({destination,desktopRoot:f.root,packages:[{id:'fixture',bundle:f.bundle}]})
 assert.equal(result.packages,1)
 assert.equal(fs.existsSync(path.join(destination,'packages/fixture/unrelated-private.txt')),false)
 assert.equal(fs.existsSync(path.join(destination,'packages/fixture/receipt.json')),false)
 assert.equal(runSetup({setupDir:destination,lockDir:path.join(f.area,'locks'),mode:'apply'}).state,'installed')
 assert.equal(runSetup({setupDir:destination,lockDir:path.join(f.area,'locks'),mode:'rollback'}).state,'rolled_back')
 assert.throws(()=>assembleSetupPackage({destination,desktopRoot:f.root,packages:[]}),/Destination Already Exists/)
})
test('package assembly refuses changed build provenance rather than adopting its new hash',t=>{
 const f=desktopFixture(t),destination=path.join(f.area,'standalone')
 fs.appendFileSync(path.join(f.bundle,'build-receipt.json'),' ')
 assert.throws(()=>assembleSetupPackage({destination,desktopRoot:f.root,packages:[{id:'fixture',bundle:f.bundle}]}),/Build Receipt Changed/)
 assert.equal(fs.existsSync(destination),false)
})
