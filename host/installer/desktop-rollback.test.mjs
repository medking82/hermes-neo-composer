// File-only installer integration: synthetic shell, no Python/server/cleanup process.
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import os from 'node:os'
import { pathToFileURL } from 'node:url'
import test from 'node:test'
import { desktopFixture as fixture } from './desktop-fixture.mjs'
import { assertPluginPolicy } from './compat.mjs'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
test('preserve policy cannot contain plugin writes or adopt unknown policies', () => {
  assert.equal(assertPluginPolicy({pluginFiles: []}), 'transactional')
  assert.equal(assertPluginPolicy({pluginFiles: [], pluginPolicy: 'preserve'}), 'preserve')
  assert.throws(() => assertPluginPolicy({pluginFiles: [{path:'plugin.js'}], pluginPolicy: 'preserve'}), /Must Not Have A Write Inventory/)
  assert.throws(() => assertPluginPolicy({pluginFiles: [], pluginPolicy: 'force'}), /Unknown Plugin Policy/)
})
test('prepare and install keep a separately managed SDK plugin outside the enhancement write set', t => {
  const f = fixture(t), manifestPath = path.join(f.bundle, 'release.json')
  const seed = JSON.parse(fs.readFileSync(manifestPath, 'utf8'))
  seed.pluginPolicy = 'preserve'; seed.pluginFiles = []
  const plugin = path.join(seed.pluginRoot, 'neo-next-prompt', 'plugin.js')
  fs.writeFileSync(plugin, 'independent SDK baseline')
  fs.unlinkSync(manifestPath)
  f.put(f.bundle, 'release-seed.json', JSON.stringify(seed))
  f.put(f.bundle, 'checkout/'+f.source, 'after source')
  const receipt = JSON.parse(fs.readFileSync(path.join(f.bundle, 'build-receipt.json'), 'utf8'))
  receipt.dirty = receipt.sourcePins
  f.put(f.bundle, 'build-receipt.json', JSON.stringify(receipt))
  const prepared = spawnSync(process.execPath, [fileURLToPath(new URL('./prepare.mjs', import.meta.url)), f.root, f.bundle], {encoding:'utf8'})
  assert.equal(prepared.status, 0, prepared.stderr)
  assert.equal(JSON.parse(fs.readFileSync(manifestPath, 'utf8')).pluginPolicy, 'preserve')
  f.good('apply'); f.good('rollback')
  assert.equal(fs.readFileSync(plugin, 'utf8'), 'independent SDK baseline')
})
test('an independent enhancement preserves the base SDK plugin through install and uninstall', t => {
  const f = fixture(t)
  const manifestPath = path.join(f.bundle, 'release.json')
  const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'))
  const plugin = path.join(manifest.pluginRoot, 'neo-next-prompt', 'plugin.js')
  manifest.pluginPolicy = 'preserve'
  manifest.pluginFiles = []
  fs.writeFileSync(manifestPath, JSON.stringify(manifest))
  fs.writeFileSync(plugin, 'independently installed SDK plugin')
  assert.equal(f.good('apply').state, 'installed')
  assert.equal(fs.readFileSync(plugin, 'utf8'), 'independently installed SDK plugin')
  assert.equal(f.good('rollback').state, 'rolled_back')
  assert.equal(fs.readFileSync(plugin, 'utf8'), 'independently installed SDK plugin')
})
test('installed verification rejects changed generated renderer bytes', t => {
  const f = fixture(t)
  f.good('apply')
  fs.appendFileSync(path.join(f.root, f.renderer, 'assets/owned.js'), '\n// foreign renderer edit\n')
  for (const mode of ['check', 'apply']) {
    const result = f.run(mode)
    assert.notEqual(result.status, 0, `${mode} falsely verified a modified renderer asset`)
    assert.match(result.stderr, /Installed renderer drift/)
  }
})
test('desktop rollback refuses a linked renderer directory without deleting its external asset', t => {
  const f = fixture(t); f.good('apply')
  const assets = path.join(f.root, f.renderer, 'assets'), outside = path.join(f.area, 'outside-assets')
  fs.renameSync(assets, outside); fs.symlinkSync(outside, assets, process.platform === 'win32' ? 'junction' : 'dir')
  const r = f.run('rollback')
  assert.notEqual(r.status, 0, 'Rollback followed the renderer link and deleted external content')
  assert.equal(fs.readFileSync(path.join(outside, 'owned.js'), 'utf8'), 'candidate asset')
  assert.equal(fs.readFileSync(path.join(f.root, f.source), 'utf8'), 'after source')
})
test('desktop partial apply already has a prepared receipt and can roll back', t => {
  const f = fixture(t), fault = path.join(f.area, 'fault.mjs')
  fs.writeFileSync(fault, `import fs from 'node:fs';const copy=fs.copyFileSync;fs.copyFileSync=(a,b,...rest)=>{if(b===${JSON.stringify(path.join(f.root, f.source) + '.neo-new')})throw Error('fixture-copy-failure');return copy(a,b,...rest)}`)
  const r = f.run('apply', ['--import', pathToFileURL(fault).href]); assert.notEqual(r.status, 0); assert.match(r.stderr, /fixture-copy-failure/)
  assert.equal(JSON.parse(fs.readFileSync(path.join(f.bundle, 'receipt.json'))).state, 'prepared')
  assert.equal(f.good('rollback').state, 'rolled_back')
  assert.equal(fs.readFileSync(path.join(f.root, f.source), 'utf8'), 'before source')
  assert.equal(fs.existsSync(path.join(f.root, f.renderer, 'assets/owned.js')), false)
})
