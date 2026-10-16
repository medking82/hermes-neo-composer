import assert from 'node:assert/strict'
import { test } from 'node:test'
import * as compat from './compat.mjs'

test('source allowlist admits only composer files and the two generated public contracts', () => {
  assert.equal(typeof compat.isComposerSource, 'function')
  for (const path of ['apps/desktop/src/sdk/composer.ts', 'apps/shared/src/gateway-contract.generated.ts', 'apps/shared/src/gateway-contract.openrpc.json']) {
    assert.equal(compat.isComposerSource(path), true, path)
  }
  for (const path of ['.env', 'apps/shared/src/credentials.ts', 'apps/shared/src/gateway-contract.generated.ts.extra', 'apps/desktop/src/../private.ts', '/apps/desktop/src/sdk/composer.ts']) {
    assert.equal(compat.isComposerSource(path), false, path)
  }
})
