// Contract test for the registration surface: on hosts with the unified
// settings API, settings live in Settings ▸ Plugins (no sidebar or route row
// of their own); hosts WITHOUT ctx.registerSettingsPage keep the legacy
// route + sidebar entry as a fallback so settings stay reachable. The
// composer seam is gated on host.composer.behaviorVersion === 2 and never
// breaks registration.
import assert from 'node:assert/strict'
import * as nodeModule from 'node:module'
import test from 'node:test'
import { readFileSync } from 'node:fs'

import { load, resolve } from './registration-stubs.mjs'

// The async module.register() path is a documented fallback for older node;
// force it with NEO_REGISTRATION_ASYNC_HOOKS=1 (both paths are verified).
if (process.env.NEO_REGISTRATION_ASYNC_HOOKS === '1' || typeof nodeModule.registerHooks !== 'function') {
  await nodeModule.register('./registration-stubs.mjs', import.meta.url)
} else {
  nodeModule.registerHooks({ resolve, load })
}

const { host } = await import('@hermes/plugin-sdk')
const plugin = (await import('./index.mjs')).default

test('package metadata uses the same Neo Composer release version', () => {
  const manifest = readFileSync(new URL('../plugin.yaml', import.meta.url), 'utf8')
  assert.equal(manifest.match(/^name: (.+)$/m)?.[1], plugin.id)
  assert.equal(manifest.match(/^version: "([^"]+)"$/m)?.[1], plugin.version)
})

const harness = ({ behaviorVersion = 2, strictSteeringVersion = 1, withSettingsPage = true, composer } = {}) => {
  host.composer = composer ?? { behaviorVersion, strictSteeringVersion }
  const registered = []
  const pages = []
  const notices = []
  host.notify = event => notices.push(event)
  const ctx = {
    storage: { get: () => null, set: () => {} },
    register: contribution => {
      registered.push(contribution)
      return () => {}
    }
  }
  if (withSettingsPage) {
    ctx.registerSettingsPage = page => {
      pages.push(page)
      return () => {}
    }
  }
  plugin.register(ctx)
  return { registered, pages, notices }
}

const areas = registered => registered.map(entry => entry.area)

test('missing strict steering leaves native suggestions registered without overriding native keys', () => {
  const { registered, notices } = harness({ strictSteeringVersion: null })
  const contribution = registered.find(item => item.area === 'composer.behavior.v2')
  assert.ok(contribution, 'suggestions must not depend on strict Steering')
  assert.equal(contribution.data.keyAction({ key: 'Enter', busy: true, ctrlKey: true }), undefined)
  assert.equal(contribution.data.keyAction({ key: 'Enter', busy: true }), undefined)
  assert.deepEqual(contribution.data.readOnlyKeys, {})
  assert.ok(!notices.some(item => item.kind === 'error'))
})

test('an official SDK host registers portable suggestions without a private native seam', () => {
  const atom = value => ({ get: () => value, subscribe: () => () => {} })
  host.activeConnectionId = () => 'fixture-connection'
  host.state = {
    focusedSessionId: atom('runtime-fixture'), focusedStoredSessionId: atom('stored-fixture'),
    focusedSessionOwner: atom({ connectionId: 'fixture-connection', profile: 'default' }),
    connectionId: atom('fixture-connection'), profile: atom('default'), busy: atom(false)
  }
  const { registered, pages, notices } = harness({ composer: {
    getDraft: async () => '', insertText: async () => true, focus: () => {}
  } })
  assert.equal(pages.length, 1)
  assert.ok(registered.some(item => item.id === 'portable' && item.area === 'statusBar.right' && typeof item.render === 'function'), 'official SDK keeps a single window-level suggestions preview; slots do not expose a composer owner')
  assert.ok(!areas(registered).includes('composer.behavior.v2'))
  assert.ok(!notices.some(item => item.kind === 'error'))
})

test('settings register under Settings ▸ Plugins with no sidebar or route row', () => {
  const { registered, pages } = harness()
  assert.equal(pages.length, 1)
  assert.equal(pages[0].id, 'settings')
  assert.equal(pages[0].title, 'Neo Composer')
  assert.equal(typeof pages[0].render, 'function')
  assert.deepEqual(areas(registered), ['composer.behavior.v2'])
  assert.equal(registered[0].data.protocol, 2)
  for (const stale of ['routes', 'sidebar.nav']) {
    assert.ok(!areas(registered).includes(stale))
  }
})

test('the settings page render returns the settings view element', () => {
  const { pages } = harness()
  const tree = pages[0].render()
  assert.equal(typeof tree, 'object')
  assert.equal(typeof tree.type, 'function')
  // Shallow-execute the component with the stubbed hooks: it must render its
  // section shell (the loading branch) instead of throwing.
  const shallow = tree.type({ ctx: { rest: async () => ({ settings: null }) } })
  assert.equal(typeof shallow, 'object')
  assert.equal(shallow.type, 'section')
  assert.equal(shallow.props['aria-label'], 'Neo Composer settings')
  const heading = shallow.props.children[0].props.children[0]
  assert.equal(heading.type, 'h2')
  assert.equal(heading.props.children, 'Neo Composer')
  assert.equal(plugin.name, 'Neo Composer')
  assert.equal(plugin.id, 'neo-next-prompt')
  const enhancements = shallow.props.children.filter(child => typeof child?.type === 'function').map(child => child.type(child.props))
  assert.ok(enhancements.some(child => child?.props?.['aria-label'] === 'Native Enhancement'), 'enhancement controls must render before prediction settings load')
})

test('an incompatible host gets the status-bar notice and no composer contribution', () => {
  const { registered, pages, notices } = harness({ behaviorVersion: 1 })
  for (const stale of ['routes', 'sidebar.nav']) {
    assert.ok(!areas(registered).includes(stale))
  }
  assert.deepEqual(areas(registered), ['statusBar.right'])
  assert.equal(notices.length, 1)
  assert.equal(notices[0].kind, 'error')
  assert.equal(pages.length, 1)
})

test('a host without registerSettingsPage keeps the legacy route + sidebar fallback', () => {
  const { registered, pages } = harness({ withSettingsPage: false })
  assert.equal(pages.length, 0)
  assert.deepEqual(areas(registered), ['routes', 'sidebar.nav', 'composer.behavior.v2'])
  assert.equal(registered[0].data.path, '/neo-composer')
  assert.equal(registered[1].data.label, 'Neo Composer')
  assert.equal(registered[1].data.codicon, 'settings-gear')
})
