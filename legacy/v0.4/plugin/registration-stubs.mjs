// Module-hook stubs for the registration contract test.
//
// The test runs the REAL plugin/index.mjs (and the real controller.mjs /
// settings.mjs it imports) under plain node, injecting only the documented
// SDK / React surface. No host code, no bundler, no network.
//
// Works with both node module APIs:
//   - module.registerHooks({ resolve, load })  (node >= 22.15, synchronous)
//   - module.register('./registration-stubs.mjs', import.meta.url)  (async fallback)

const sdk = `
export const host = { composer: undefined, notify: () => {} }
export const ROUTES_AREA = 'routes'
export const SIDEBAR_NAV_AREA = 'sidebar.nav'
export const Button = 'Button'
export const Switch = 'Switch'
export const Checkbox = 'Checkbox'
export const Select = 'Select'
export const SelectContent = 'SelectContent'
export const SelectItem = 'SelectItem'
export const SelectTrigger = 'SelectTrigger'
export const SelectValue = 'SelectValue'
`

const react = `
export const useEffect = () => {}
export const useRef = () => ({ current: 0 })
export const useState = value => [value, () => {}]
`

const jsxRuntime = `
export const jsx = (type, props, key) => ({ type, props, key })
export const jsxs = jsx
export const Fragment = 'Fragment'
`

const STUBS = {
  '@hermes/plugin-sdk': sdk,
  react,
  'react/jsx-runtime': jsxRuntime
}

const PREFIX = 'stub:'

export function resolve(specifier, context, nextResolve) {
  if (Object.hasOwn(STUBS, specifier)) {
    return { url: PREFIX + specifier, shortCircuit: true }
  }
  return nextResolve(specifier, context)
}

export function load(url, context, nextLoad) {
  if (url.startsWith(PREFIX)) {
    const specifier = url.slice(PREFIX.length)
    return { format: 'module', source: STUBS[specifier], shortCircuit: true }
  }
  return nextLoad(url, context)
}
