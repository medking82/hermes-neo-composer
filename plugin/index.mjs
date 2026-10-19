import { host, useValue, Popover, PopoverTrigger, PopoverContent, ROUTES_AREA, SIDEBAR_NAV_AREA, Button, Switch, Checkbox, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@hermes/plugin-sdk'
import { useEffect, useRef, useState } from 'react'
import { jsx } from 'react/jsx-runtime'
import { createController, keyAction, profileLifecycle, readOnlyKeys } from './controller.mjs'
import { createSettingsView } from './settings.mjs'
import { createPortableWidget, portableSupported } from './portable.mjs'
import { createEnhancementView } from './enhancement.mjs'

const Enhancement = createEnhancementView({ host, jsx, useRef, useState, Button, portableSupported })
const PortableSuggestions = createPortableWidget({ host, jsx, useValue, useEffect, useRef, useState, Button, Popover, PopoverTrigger, PopoverContent, createController })
const Settings = createSettingsView({ jsx, useEffect, useRef, useState, Button, Switch, Checkbox, Select, SelectContent, SelectItem, SelectTrigger, SelectValue, Enhancement })
export default {
  id: 'neo-next-prompt',
  name: 'Neo Composer',
  version: '0.5.0-rc.1',
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
    if (host.composer?.behaviorVersion !== 2) {
      if (portableSupported(host)) {
        ctx.register({ id: 'portable', area: 'statusBar.right', render: () => jsx(PortableSuggestions, { ctx }) })
      } else {
        ctx.register({ id: 'compatibility', area: 'statusBar.right', render: () => jsx('span', { title: 'Native enhancement or owner-aware draft SDK is required. Settings and enhancement setup remain available.', children: 'Neo Composer · Suggestions Unavailable' }) })
        host.notify({ kind: 'error', message: 'Neo Composer suggestions require a compatible draft SDK or native enhancement. Settings remain available; no core files were changed.' })
      }
      return
    }
    const strict = host.composer.strictSteeringVersion === 1
    ctx.register({ id: 'composer', area: 'composer.behavior.v2', data: {
      protocol: 2,
      create: env => createController(env, ctx.storage),
      keyAction: strict ? keyAction : () => undefined,
      readOnlyKeys: strict ? readOnlyKeys : {},
      lifecycle: event => profileLifecycle(ctx.storage, event)
    } })
    if (!strict) ctx.register({ id: 'steering-unavailable', area: 'statusBar.right', render: () => jsx('span', { title: 'Suggestions are enabled. Strict Steering and Neo key overrides are unavailable; native shortcuts are unchanged.', children: 'Neo Composer · Suggestions Only' }) })
  }
}
