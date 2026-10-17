import { host, ROUTES_AREA, SIDEBAR_NAV_AREA, Button, Switch, Checkbox, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@hermes/plugin-sdk'
import { useEffect, useRef, useState } from 'react'
import { jsx } from 'react/jsx-runtime'
import { createController, keyAction, profileLifecycle, readOnlyKeys } from './controller.mjs'
import { createSettingsView } from './settings.mjs'

const Settings = createSettingsView({ jsx, useEffect, useRef, useState, Button, Switch, Checkbox, Select, SelectContent, SelectItem, SelectTrigger, SelectValue })
export default {
  id: 'neo-next-prompt',
  name: 'Neo Composer',
  version: '0.4.5-rc.1',
  defaultEnabled: true,
  register(ctx) {
    if (typeof ctx.registerSettingsPage === 'function') {
      // Settings live in Settings ▸ Plugins (the host's unified plugin home); no sidebar row of its own.
      ctx.registerSettingsPage({ id: 'settings', title: 'Neo Composer', icon: 'settings-gear', render: () => jsx(Settings, { ctx }) })
    } else {
      // Hosts without the unified settings surface keep the legacy page + sidebar row,
      // so the prediction settings stay reachable instead of silently disappearing.
      ctx.register({ id: 'settings', area: ROUTES_AREA, data: { path: '/neo-composer' }, render: () => jsx(Settings, { ctx }) })
      ctx.register({ id: 'settings-nav', area: SIDEBAR_NAV_AREA, data: { path: '/neo-composer', label: 'Neo Composer', codicon: 'settings-gear' } })
    }
    if (host.composer?.behaviorVersion !== 2 || host.composer?.strictSteeringVersion !== 1) {
      ctx.register({ id: 'compatibility', area: 'statusBar.right', render: () => jsx('span', { title: 'Neo Composer requires composer behavior v2 with strict steering v1. No host files were changed.', children: 'Neo Composer · incompatible host' }) })
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
