// Fixed Neo Composer backend seam only. No service control, updater or configuration writes.
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'

const FILES = ['agent/agent_runtime_helpers.py', 'agent/interrupt_control.py', 'agent/turn_context.py', 'agent/turn_finalizer.py', 'agent/turn_iteration_prep.py', 'agent/steer_requeue.py', 'tui_gateway/contracts/events.py', 'tui_gateway/contracts/sessions.py', 'tui_gateway/methods_session_interrupt.py', 'tui_gateway/steer_images.py']
const sha = bytes => createHash('sha256').update(bytes).digest('hex')
export function ordinary(root, relative) {
  assert(typeof relative === 'string' && relative.split('/').every(p => /^[a-zA-Z0-9_.-]+$/.test(p) && p !== '.' && p !== '..'), 'Unsafe backend path')
  let file = root
  const parts = relative.split('/')
  const base = fs.lstatSync(root)
  assert(base.isDirectory() && !base.isSymbolicLink(), 'Linked backend root')
  for (let i = 0; i < parts.length; i++) {
    file = path.join(file, parts[i])
    const stat = fs.lstatSync(file, { throwIfNoEntry: false })
    if (!stat) continue
    assert(!stat.isSymbolicLink() && (i === parts.length - 1 ? stat.isFile() : stat.isDirectory()), 'Linked or invalid backend path')
  }
  return file
}
const digest = file => fs.existsSync(file) ? sha(fs.readFileSync(file)) : null
const equal = (a, b) => JSON.stringify(a) === JSON.stringify(b)
export function atomic(from, to) {
  const temp = to + '.neo-new'
  // Reserve our scratch file exclusively; never remove a pre-existing file.
  fs.closeSync(fs.openSync(temp, 'wx'))
  try { fs.copyFileSync(from, temp); fs.renameSync(temp, to) }
  finally { if (fs.existsSync(temp)) fs.unlinkSync(temp) }
}

export function backendTransition(mode, root, bundle, manifest, releaseSha, head) {
  assert(['check-backend', 'apply-backend', 'rollback-backend'].includes(mode))
  assert(manifest.roles.backend.heads.includes(head), 'Unsupported backend version; never restore old files over an upgrade')
  const entries = manifest.backendSources
  assert(Array.isArray(entries), 'Missing backend source payload')
  assert.deepEqual(entries.map(e => e.path).sort(), [...FILES].sort(), 'Unexpected backend source set')
  for (const e of entries) {
    assert(e.before === null || /^[a-f0-9]{64}$/.test(e.before), 'Invalid predecessor hash')
    assert(/^[a-f0-9]{64}$/.test(e.after), 'Invalid payload hash')
    assert.equal(manifest.roles.backend.pins[e.path], e.after, 'Stale backend compatibility pin')
    ordinary(root, e.path)
    assert.equal(digest(ordinary(bundle, 'source/' + e.path)), e.after, 'Backend payload drift')
  }
  for (const [name, expected] of Object.entries(manifest.roles.backend.pins)) {
    if (!FILES.includes(name)) assert.equal(digest(ordinary(root, name)), expected, 'Backend interface drift')
  }
  const before = Object.fromEntries(entries.map(e => [e.path, e.before]))
  const after = Object.fromEntries(entries.map(e => [e.path, e.after]))
  const state = () => Object.fromEntries(entries.map(e => [e.path, digest(ordinary(root, e.path))]))
  const current = state(), backup = path.join(bundle, 'backend-backup')
  const receiptFile = ordinary(bundle, 'backend-receipt.json')
  const receipt = fs.existsSync(receiptFile) ? JSON.parse(fs.readFileSync(receiptFile, 'utf8')) : null
  const binding = { releaseSha, root: fs.realpathSync(root), head }
  const verifyBackup = () => {
    assert(receipt, 'Missing backend rollback ownership')
    for (const [k, v] of Object.entries(binding)) assert.equal(receipt[k], v, 'Wrong backend receipt')
    for (const e of entries) if (e.before !== null) assert.equal(digest(ordinary(backup, e.path)), e.before, 'Backend backup drift')
  }
  const save = value => {
    const temp = ordinary(bundle, 'backend-receipt.json.new')
    const fd = fs.openSync(temp, 'wx')
    try {
      try { fs.writeFileSync(fd, JSON.stringify({ ...binding, state: value }, null, 2)) }
      finally { fs.closeSync(fd) }
      fs.renameSync(temp, receiptFile)
    } finally { if (fs.existsSync(temp)) fs.unlinkSync(temp) }
  }
  if (mode !== 'rollback-backend' && equal(current, after)) {
    verifyBackup()
    return { state: 'already_installed', role: 'backend', verified: true, servicesRestarted: false }
  }
  if (mode === 'check-backend') {
    assert.deepEqual(current, before, 'Unknown backend edits')
    if (fs.existsSync(backup) || receipt) verifyBackup()
    return { state: 'ready', role: 'backend', verified: true }
  }
  // Exclusive ownership of this bundle's backup/receipt. No silent stale-lock removal.
  const lock = ordinary(bundle, 'backend-operation.lock')
  const fd = fs.openSync(lock, 'wx')
  try {
    assert.deepEqual(state(), current, 'Backend changed during preflight')
    if (mode === 'rollback-backend') {
      verifyBackup()
      for (const e of entries) assert(current[e.path] === e.before || current[e.path] === e.after, 'Unknown backend edit; refuse rollback')
      for (const e of entries) {
        const target = ordinary(root, e.path)
        if (e.before === null) { if (fs.existsSync(target)) fs.unlinkSync(target) }
        else atomic(ordinary(backup, e.path), target)
      }
      assert.deepEqual(state(), before, 'Backend rollback readback mismatch')
      save('rolled_back')
      return { state: 'rolled_back', role: 'backend', verified: true, servicesRestarted: false }
    }
    assert.deepEqual(current, before, 'Unknown backend edits; refuse overwrite')
    if (fs.existsSync(backup) || receipt) verifyBackup()
    else {
      fs.mkdirSync(backup)
      for (const e of entries) if (e.before !== null) {
        const target = path.join(backup, e.path)
        fs.mkdirSync(path.dirname(target), { recursive: true })
        fs.copyFileSync(ordinary(root, e.path), target, fs.constants.COPYFILE_EXCL)
        assert.equal(digest(target), e.before, 'Backend changed during backup')
      }
    }
    assert.deepEqual(state(), before, 'Backend changed before apply')
    save('prepared')
    for (const e of entries) atomic(ordinary(bundle, 'source/' + e.path), ordinary(root, e.path))
    assert.deepEqual(state(), after, 'Backend install readback mismatch')
    save('installed')
    return { state: 'installed', role: 'backend', verified: true, servicesRestarted: false }
  } finally {
    fs.closeSync(fd)
    fs.unlinkSync(lock)
  }
}
