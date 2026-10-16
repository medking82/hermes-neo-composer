import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { createHash } from 'node:crypto'
import { runtimeFingerprint } from './compat.mjs'

const head = 'd923a5eb487a17c0a68801bba9ef0f56c81040a8'
const prefix = 'apps/desktop/release/win-unpacked/'
const payloads = ['Hermes.exe', 'resources/app.asar', 'resources/install-stamp.json',
  'resources/app.asar.unpacked/dist/electron-main.mjs',
  'resources/app.asar.unpacked/dist/electron-preload.js',
  'resources/app.asar.unpacked/dist/preview-guest-preload.js']
const hash = p => createHash('sha256').update(fs.readFileSync(p)).digest('hex')

function fixture(t, dirty) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'neo-runtime-test-'))
  t.after(() => fs.rmSync(root, { recursive: true, force: true }))
  for (const name of payloads) {
    const target = path.join(root, prefix, name)
    fs.mkdirSync(path.dirname(target), { recursive: true })
    fs.writeFileSync(target, name.endsWith('install-stamp.json')
      ? JSON.stringify({ schemaVersion: 1, commit: head, dirty })
      : 'fixture-native-payload:' + name)
  }
  return { root, expected: { commit: head, pins: Object.fromEntries(payloads.map(n => [prefix + n, hash(path.join(root, prefix, n))])) } }
}

test('unknown dirty runtime is refused without an explicit approved baseline', t => {
  const { root } = fixture(t, true)
  assert.throws(() => runtimeFingerprint(root, [head]), /Unverified dirty/)
})

test('an exact independently approved dirty predecessor is accepted without restamping', t => {
  const { root, expected } = fixture(t, true)
  assert.deepEqual(runtimeFingerprint(root, [head], expected), expected)
  assert.equal(JSON.parse(fs.readFileSync(path.join(root, prefix, 'resources/install-stamp.json'))).dirty, true)
})

test('actual js preload and preview preload are protected on clean runtimes too', t => {
  const { root, expected } = fixture(t, false)
  assert.deepEqual(runtimeFingerprint(root, [head]), expected)
})

for (const name of payloads) test('approved runtime refuses subsequent drift: ' + name, t => {
  const { root, expected } = fixture(t, true)
  const target = path.join(root, prefix, name)
  if (name.endsWith('install-stamp.json')) {
    const stamp = JSON.parse(fs.readFileSync(target)); stamp.builtAt = 'fixture-changed'; fs.writeFileSync(target, JSON.stringify(stamp))
  } else fs.appendFileSync(target, 'fixture-drift')
  assert.throws(() => runtimeFingerprint(root, [head], expected))
})

test('an incomplete approved baseline cannot omit real preload files', t => {
  const { root, expected } = fixture(t, true)
  delete expected.pins[prefix + 'resources/app.asar.unpacked/dist/electron-preload.js']
  assert.throws(() => runtimeFingerprint(root, [head], expected))
})

test('nonboolean stamp dirty flag is refused even with matching hashes', t => {
  const { root, expected } = fixture(t, 'unrecognised')
  assert.throws(() => runtimeFingerprint(root, [head], expected))
})
