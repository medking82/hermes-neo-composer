import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { execFileSync, spawnSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import test from 'node:test'

const installer = fileURLToPath(new URL('./install.mjs', import.meta.url))
const names = ['agent/agent_runtime_helpers.py', 'agent/interrupt_control.py', 'agent/turn_context.py', 'agent/turn_finalizer.py', 'agent/turn_iteration_prep.py', 'agent/steer_requeue.py', 'tui_gateway/contracts/events.py', 'tui_gateway/contracts/sessions.py', 'tui_gateway/methods_session_interrupt.py', 'tui_gateway/steer_images.py']
const hash = value => createHash('sha256').update(value).digest('hex')
function fixture(t) {
  const area = fs.mkdtempSync(path.join(os.tmpdir(), 'neo-backend-test-'))
  t.after(() => fs.rmSync(area, { recursive: true, force: true }))
  const root = path.join(area, 'root'), bundle = path.join(area, 'bundle')
  fs.mkdirSync(root); fs.mkdirSync(bundle)
  const git = args => execFileSync('git', ['-C', root, ...args], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim()
  git(['init', '-q']); git(['config', 'user.email', 'fixture@example.invalid']); git(['config', 'user.name', 'Fixture'])
  const entries = names.map((name, i) => {
    const before = (name.endsWith('/steer_requeue.py') || name.endsWith('/steer_images.py')) ? null : `# original ${i}\n`
    const after = `# candidate ${i}\n`
    const target = path.join(root, name), payload = path.join(bundle, 'source', name)
    fs.mkdirSync(path.dirname(target), { recursive: true }); fs.mkdirSync(path.dirname(payload), { recursive: true })
    if (before !== null) fs.writeFileSync(target, before)
    fs.writeFileSync(payload, after)
    return { path: name, before: before === null ? null : hash(before), after: hash(after) }
  })
  git(['add', '.']); git(['commit', '-qm', 'fixture baseline'])
  const head = git(['rev-parse', 'HEAD'])
  fs.writeFileSync(path.join(root, 'unrelated.txt'), 'keep unrelated edits\n')
  const manifest = { backendSources: entries, roles: { backend: { heads: [head], pins: Object.fromEntries(entries.map(e => [e.path, e.after])) } } }
  fs.writeFileSync(path.join(bundle, 'release.json'), JSON.stringify(manifest))
  const run = (mode, extra = []) => spawnSync(process.execPath, [...extra, installer, mode, root, bundle], { encoding: 'utf8' })
  const good = mode => { const r = run(mode); assert.equal(r.status, 0, r.stderr); return JSON.parse(r.stdout) }
  return { root, bundle, entries, git, run, good }
}

test('backend patch installs, preserves unrelated edits and uninstalls to its exact baseline', t => {
  const f = fixture(t)
  assert.equal(f.good('check-backend').state, 'ready')
  assert.equal(f.good('apply-backend').state, 'installed')
  assert.equal(f.good('apply-backend').state, 'already_installed')
  for (const e of f.entries) assert.equal(hash(fs.readFileSync(path.join(f.root, e.path))), e.after)
  assert.equal(f.good('rollback-backend').state, 'rolled_back')
  assert.equal(f.good('rollback-backend').state, 'rolled_back')
  for (const e of f.entries) {
    const p = path.join(f.root, e.path)
    if (e.before === null) assert.equal(fs.existsSync(p), false)
    else assert.equal(hash(fs.readFileSync(p)), e.before)
  }
  assert.equal(fs.readFileSync(path.join(f.root, 'unrelated.txt'), 'utf8'), 'keep unrelated edits\n')
  assert.equal(f.git(['diff', '--name-only']), '')
})

test('backend mixed-state apply failure remains recoverable by rollback', t => {
  const f = fixture(t), fault = path.join(f.bundle, 'fault.mjs')
  const target = path.join(f.root, names[2]) + '.neo-new'
  fs.writeFileSync(fault, `import fs from 'node:fs';const copy=fs.copyFileSync;fs.copyFileSync=(a,b,...rest)=>{if(b===${JSON.stringify(target)})throw Error('fixture-copy-failure');return copy(a,b,...rest)}`)
  const r = f.run('apply-backend', ['--import', pathToFileURL(fault).href]); assert.notEqual(r.status, 0); assert.match(r.stderr, /fixture-copy-failure/)
  assert.equal(hash(fs.readFileSync(path.join(f.root, names[0]))), f.entries[0].after)
  assert.equal(JSON.parse(fs.readFileSync(path.join(f.bundle, 'backend-receipt.json'))).state, 'prepared')
  assert.equal(f.good('rollback-backend').state, 'rolled_back')
})

test('backend failed rename cleans its scratch file so rollback is not wedged', t => {
  const f = fixture(t), fault = path.join(f.bundle, 'fault.mjs'), target = path.join(f.root, names[2])
  fs.writeFileSync(fault, `import fs from 'node:fs';const rename=fs.renameSync;fs.renameSync=(a,b)=>{if(b===${JSON.stringify(target)})throw Error('fixture-rename-failure');return rename(a,b)}`)
  const r = f.run('apply-backend', ['--import', pathToFileURL(fault).href]); assert.notEqual(r.status, 0); assert.match(r.stderr, /fixture-rename-failure/)
  assert.equal(f.good('rollback-backend').state, 'rolled_back')
  assert.equal(fs.existsSync(target + '.neo-new'), false)
})

test('backend receipt rename failure keeps prepared rollback usable', t => {
  const f = fixture(t), fault = path.join(f.bundle, 'fault.mjs'), target = path.join(f.bundle, 'backend-receipt.json')
  fs.writeFileSync(fault, `import fs from 'node:fs';const rename=fs.renameSync;fs.renameSync=(a,b)=>{if(b===${JSON.stringify(target)}&&JSON.parse(fs.readFileSync(a)).state==='installed')throw Error('fixture-receipt-failure');return rename(a,b)}`)
  const r = f.run('apply-backend', ['--import', pathToFileURL(fault).href]); assert.notEqual(r.status, 0); assert.match(r.stderr, /fixture-receipt-failure/)
  assert.equal(JSON.parse(fs.readFileSync(target)).state, 'prepared')
  assert.equal(f.good('rollback-backend').state, 'rolled_back')
  assert.equal(fs.existsSync(target + '.new'), false)
})

test('backup-stage failure leaves source unchanged and a fresh bundle can install safely', t => {
  const f = fixture(t), fault = path.join(f.bundle, 'fault.mjs')
  const target = path.join(f.bundle, 'backend-backup', names[2])
  fs.writeFileSync(fault, `import fs from 'node:fs';const copy=fs.copyFileSync;fs.copyFileSync=(a,b,...rest)=>{if(b===${JSON.stringify(target)})throw Error('fixture-backup-failure');return copy(a,b,...rest)}`)
  const r = f.run('apply-backend', ['--import', pathToFileURL(fault).href]); assert.notEqual(r.status, 0); assert.match(r.stderr, /fixture-backup-failure/)
  for (const e of f.entries) assert.equal(fs.existsSync(path.join(f.root, e.path)) ? hash(fs.readFileSync(path.join(f.root, e.path))) : null, e.before)
  assert.equal(fs.existsSync(path.join(f.bundle, 'backend-receipt.json')), false)
  const fresh = path.join(f.bundle, 'fresh'); fs.mkdirSync(fresh)
  fs.copyFileSync(path.join(f.bundle, 'release.json'), path.join(fresh, 'release.json')); fs.cpSync(path.join(f.bundle, 'source'), path.join(fresh, 'source'), { recursive: true })
  for (const mode of ['apply-backend', 'rollback-backend']) {
    const r = spawnSync(process.execPath, [installer, mode, f.root, fresh], { encoding: 'utf8' }); assert.equal(r.status, 0, r.stderr)
  }
})

test('backend refuses foreign edits before install and before rollback', t => {
  const f = fixture(t), file = path.join(f.root, names[0]), original = fs.readFileSync(path.join(f.root, names[0]))
  fs.writeFileSync(file, 'foreign edit')
  assert.notEqual(f.run('apply-backend').status, 0)
  assert.equal(fs.existsSync(path.join(f.bundle, 'backend-backup')), false)
  fs.writeFileSync(file, original); f.good('apply-backend')
  fs.writeFileSync(file, 'later edit')
  assert.notEqual(f.run('rollback-backend').status, 0)
  assert.equal(fs.readFileSync(file, 'utf8'), 'later edit')
})

test('backend will not restore an old backup after an official-version change', t => {
  const f = fixture(t); f.good('apply-backend'); f.good('rollback-backend')
  fs.writeFileSync(path.join(f.root, names[0]), '# newer official source\n')
  f.git(['add', names[0]]); f.git(['commit', '-qm', 'version-change fixture'])
  assert.notEqual(f.run('rollback-backend').status, 0)
  assert.notEqual(f.run('apply-backend').status, 0)
  assert.equal(fs.readFileSync(path.join(f.root, names[0]), 'utf8'), '# newer official source\n')
})

test('backend validates every backup before restoring any file', t => {
  const f = fixture(t); f.good('apply-backend')
  fs.writeFileSync(path.join(f.bundle, 'backend-backup', names[0]), 'corrupt backup')
  assert.notEqual(f.run('rollback-backend').status, 0)
  for (const e of f.entries) assert.equal(hash(fs.readFileSync(path.join(f.root, e.path))), e.after)
})

test('backend refuses stale compatibility pins before writing source', t => {
  const f = fixture(t), file = path.join(f.bundle, 'release.json')
  const manifest = JSON.parse(fs.readFileSync(file, 'utf8'))
  manifest.roles.backend.pins[names[0]] = '0'.repeat(64)
  fs.writeFileSync(file, JSON.stringify(manifest))
  const result = f.run('apply-backend')
  assert.notEqual(result.status, 0, 'Inconsistent compatibility pins were installed')
  assert.equal(fs.existsSync(path.join(f.bundle, 'backend-backup')), false)
})

test('backend refuses payload drift and parent symlinks', t => {
  const f = fixture(t), payload = path.join(f.bundle, 'source', names[0])
  const original = fs.readFileSync(payload); fs.writeFileSync(payload, 'changed payload')
  assert.notEqual(f.run('apply-backend').status, 0); fs.writeFileSync(payload, original)
  fs.renameSync(path.join(f.root, 'agent'), path.join(f.root, 'outside-agent'))
  fs.symlinkSync(path.join(f.root, 'outside-agent'), path.join(f.root, 'agent'), process.platform === 'win32' ? 'junction' : 'dir')
  assert.notEqual(f.run('apply-backend').status, 0)
  assert.equal(fs.existsSync(path.join(f.bundle, 'backend-backup')), false)
})
