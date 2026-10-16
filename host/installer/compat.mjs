import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { createHash } from 'node:crypto'

// A narrow source allowlist; installation still checks paths and every hash.
export function isComposerSource(name) {
  return typeof name === 'string' && !path.isAbsolute(name) && !name.split(/[\\/]/).includes('..') &&
    (name.startsWith('apps/desktop/src/') || ['apps/shared/src/gateway-contract.generated.ts', 'apps/shared/src/gateway-contract.openrpc.json'].includes(name))
}

// The source HEAD alone says nothing about an older packaged Electron shell.
export function runtimeFingerprint(root, heads, approvedBaseline) {
  const prefix='apps/desktop/release/win-unpacked/'
  const stampPath=prefix+'resources/install-stamp.json'
  const stamp=JSON.parse(fs.readFileSync(path.join(root,stampPath),'utf8'))
  assert.equal(stamp.schemaVersion,1,'Unknown packaged runtime stamp')
  assert(heads.includes(stamp.commit),'Packaged runtime commit is not supported')
  assert.equal(typeof stamp.dirty,'boolean','Unknown packaged runtime dirty flag')
  const files=[prefix+'Hermes.exe',prefix+'resources/app.asar',stampPath,
    ...['electron-main.mjs','electron-preload.js','preview-guest-preload.js'].map(name=>prefix+'resources/app.asar.unpacked/dist/'+name)]
  for(const name of ['electron-preload.mjs','electron-preload.cjs']) {
    const file=prefix+'resources/app.asar.unpacked/dist/'+name
    if(fs.existsSync(path.join(root,file))) files.push(file)
  }
  const actual={commit:stamp.commit,pins:Object.fromEntries(files.map(file=>{
    const full=path.join(root,file),stat=fs.lstatSync(full)
    assert(stat.isFile()&&!stat.isSymbolicLink(),'Linked or non-file packaged runtime payload')
    return [file,createHash('sha256').update(fs.readFileSync(full)).digest('hex')]
  }))}
  // Operator-owned release input, frozen only after independent provenance checks.
  // Never infer this approval from the current target or rewrite its dirty stamp.
  if(approvedBaseline!==undefined)assert.deepEqual(actual,approvedBaseline,'Packaged Electron runtime drift; unapproved predecessor')
  else assert.equal(stamp.dirty,false,'Unverified dirty packaged runtime')
  return actual
}

export function assertPluginBaseline(directory, entries) {
  const names = entries.map(entry => {
    assert(/^[a-zA-Z0-9][a-zA-Z0-9._-]*$/.test(entry.path), 'Invalid plugin baseline path')
    return entry.path
  })
  assert.equal(new Set(names).size, names.length, 'Duplicate plugin baseline')
  if (!fs.existsSync(directory)) {
    assert(entries.every(entry => entry.before === null), 'Pinned predecessor plugin is missing')
    return
  }
  assert(entries.length > 0 && entries.every(entry => /^[a-f0-9]{64}$/.test(entry.before || '')), 'Existing plugin has no pinned predecessor')
  assert(fs.lstatSync(directory).isDirectory() && !fs.lstatSync(directory).isSymbolicLink(), 'Linked plugin directory')
  assert.deepEqual(fs.readdirSync(directory).sort(), [...names].sort(), 'Unknown predecessor plugin files')
  for (const entry of entries) {
    const file = path.join(directory, entry.path)
    assert(fs.lstatSync(file).isFile() && !fs.lstatSync(file).isSymbolicLink(), 'Linked or non-file plugin payload')
    assert.equal(createHash('sha256').update(fs.readFileSync(file)).digest('hex'), entry.before, 'Predecessor plugin drift: ' + entry.path)
  }
}

export function assertCompatible(role, head, actualPins, manifest) {
  const expected = manifest.roles?.[role]
  assert(expected && /^[a-f0-9]{40}$/.test(head), 'Unknown host role/version format')
  assert(expected.heads.includes(head), `Unsupported ${role} version ${head}; no force override`)
  assert(Object.keys(expected.pins).length > 0, 'Missing compatibility fingerprints')
  for (const [file, sha] of Object.entries(expected.pins)) {
    assert(/^[a-f0-9]{64}$/.test(sha) && actualPins[file] === sha, `Incompatible ${role} interface: ${file}`)
  }
  return { compatible: true, role, head }
}
