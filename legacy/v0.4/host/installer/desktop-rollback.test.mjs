// File-only installer integration: synthetic shell, no Python/server/cleanup process.
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import os from 'node:os'
import { createHash } from 'node:crypto'
import { execFileSync, spawnSync } from 'node:child_process'
import { fileURLToPath, pathToFileURL } from 'node:url'
import test from 'node:test'
import { runtimeFingerprint } from './compat.mjs'
const installer = fileURLToPath(new URL('./install.mjs', import.meta.url))
const sha = data => createHash('sha256').update(data).digest('hex')
function fixture(t) {
  const area = fs.mkdtempSync(path.join(os.tmpdir(), 'neo-desktop-files-'))
  t.after(() => fs.rmSync(area, { recursive: true, force: true }))
  const root = path.join(area, 'root'), bundle = path.join(area, 'bundle'), home = path.join(area, 'home')
  const renderer = 'apps/desktop/release/win-unpacked/resources/app.asar.unpacked/dist/'
  const source = 'apps/desktop/src/sdk/composer.ts'
  const put = (base, name, text) => { const f = path.join(base, name); fs.mkdirSync(path.dirname(f), { recursive: true }); fs.writeFileSync(f, text) }
  fs.mkdirSync(bundle); fs.mkdirSync(home)
  put(root, '.gitignore', 'apps/desktop/release/\n')
  put(root, source, 'before source')
  put(root, 'apps/desktop/electron/data-paths.mjs', `export const resolveDesktopHermesHome = () => ${JSON.stringify(home)}`)
  put(root, 'apps/desktop/electron/renderer-bundle.ts', 'export const missingRendererAssets = () => []')
  const git = (...a) => execFileSync('git', ['-C', root, ...a], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim()
  git('init', '-q'); git('config', 'user.email', 'fixture@example.invalid'); git('config', 'user.name', 'Fixture'); git('add', '.'); git('commit', '-qm', 'synthetic baseline')
  const head = git('rev-parse', 'HEAD')
  put(root, 'apps/desktop/release/win-unpacked/resources/install-stamp.json', JSON.stringify({ schemaVersion: 1, commit: head, dirty: false }))
  for (const name of ['Hermes.exe', 'resources/app.asar', ...['electron-main.mjs', 'electron-preload.js', 'preview-guest-preload.js'].map(n => 'resources/app.asar.unpacked/dist/' + n)]) put(root, 'apps/desktop/release/win-unpacked/' + name, 'synthetic shell ' + name)
  const controls = ['index.html', 'renderer-manifest.json'], beforeControls = {}, rendered = {}
  for (const name of controls) { put(root, renderer + name, 'before ' + name); put(bundle, 'candidate-renderer/' + name, 'after ' + name); beforeControls[name] = sha('before ' + name); rendered[name] = sha('after ' + name) }
  put(bundle, 'candidate-renderer/assets/owned.js', 'candidate asset'); rendered['assets/owned.js'] = sha('candidate asset')
  put(bundle, 'source/' + source, 'after source'); put(bundle, 'dist/plugin.js', 'after plugin'); put(home, 'desktop-plugins/neo-next-prompt/plugin.js', 'before plugin')
  const manifest = { roles: { desktop: { heads: [head], pins: {} } }, runtime: runtimeFingerprint(root, [head]), sources: [{ path: source, before: sha('before source'), after: sha('after source') }], pluginRoot: path.join(home, 'desktop-plugins'), pluginFiles: [{ path: 'plugin.js', before: sha('before plugin'), after: sha('after plugin') }], renderer: rendered, beforeControls, introducedRenderer: ['assets/owned.js'] }
  put(bundle, 'release.json', JSON.stringify(manifest))
  const run = (mode, extra = []) => spawnSync(process.execPath, [...extra, installer, mode, root, bundle], { encoding: 'utf8' })
  const good = mode => { const r = run(mode); assert.equal(r.status, 0, r.stderr); return JSON.parse(r.stdout) }
  return { area, root, bundle, renderer, source, put, run, good }
}
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
