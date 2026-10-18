import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const manifest = JSON.parse(readFileSync(new URL('../desktop-9e01b44-candidate.json', import.meta.url), 'utf8'))
const patch = readFileSync(new URL(`../${manifest.patch}`, import.meta.url))

test('Desktop adaptation remains pinned to the exact split-host contract', () => {
  assert.equal(manifest.desktop_base, '9e01b44dd23978f9ff40b7837467f3a9f1582130')
  assert.equal(manifest.backend_base, 'd923a5eb487a17c0a68801bba9ef0f56c81040a8')
  assert.equal(manifest.backend_change, false)
  assert.equal(manifest.plugin_version, '0.4.5')
  assert.equal(manifest.composer_protocol, 2)
  assert.equal(manifest.strict_steering_protocol, 1)
  assert.equal(manifest.native_multimodal_steering, false)
  assert.equal(createHash('sha256').update(patch).digest('hex'), manifest.patch_sha256)
})

test('the complete source inventory matches a Desktop-only patch', () => {
  const records = [...patch.toString('utf8').matchAll(/^diff --git a\/(\S+) b\/(\S+)$/gm)]
  assert(records.length > 0)
  const paths = records.map(([, before, after]) => {
    assert.equal(before, after, 'No hidden renames')
    assert(!after.split('/').includes('..'))
    assert(
      after.startsWith('apps/desktop/src/') ||
        after === 'apps/shared/src/gateway-contract.generated.ts' ||
        after === 'apps/shared/src/gateway-contract.openrpc.json' ||
        after === 'locales/_keys.desktop.json',
      `Unexpected core/native/backend write: ${after}`
    )
    return after
  })
  assert.equal(new Set(paths).size, paths.length)
  assert.deepEqual(paths.sort(), Object.keys(manifest.source_sha256).sort())
  for (const sha of Object.values(manifest.source_sha256)) assert.match(sha, /^[a-f0-9]{64}$/)
})
