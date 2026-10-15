import { host, ROUTES_AREA, SIDEBAR_NAV_AREA, Button, Switch, Checkbox, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@hermes/plugin-sdk'
import { useEffect, useRef, useState } from 'react'
import { jsx } from 'react/jsx-runtime'
import { createController, keyAction, profileLifecycle, readOnlyKeys } from './controller.mjs'
import { createSettingsView } from './settings.mjs'

const Settings = createSettingsView({ jsx, useEffect, useRef, useState, Button, Switch, Checkbox, Select, SelectContent, SelectItem, SelectTrigger, SelectValue })
export default {
  id: 'neo-next-prompt',
  name: 'Neo Composer',
  version: '0.4.0',
  defaultEnabled: true,
  register(ctx) {
    ctx.register({ id: 'settings', area: ROUTES_AREA, data: { path: '/neo-composer' }, render: () => jsx(Settings, { ctx }) })
    ctx.register({ id: 'settings-nav', area: SIDEBAR_NAV_AREA, data: { path: '/neo-composer', label: 'Neo Composer', codicon: 'settings-gear' } })
    if (host.composer?.behaviorVersion !== 2) {
      ctx.register({ id: 'compatibility', area: 'statusBar.right', render: () => jsx('span', { title: 'Neo Composer requires composer behavior interface v2. No host files were changed.', children: 'Neo Composer · incompatible host' }) })
      host.notify({ kind: 'error', message: 'Neo Composer is disabled on this host. Install a compatible interface; no core files were changed by the plugin.' })
      return
    }
    ctx.register({ id: 'composer', area: 'composer.behavior.v2', data: {
      protocol: 2,
      create: env => createController(env, ctx.storage),
      keyAction,
      readOnlyKeys,
      lifecycle: event => profileLifecycle(ctx.storage, event)
    } })
  }
}
