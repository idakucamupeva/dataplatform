/**
 * Headless render test.
 *
 * Renders every route with react-dom/server against a *running* backend. The
 * React Query cache is primed with real API responses first, so pages render
 * their populated state rather than their spinners — a broken import, a bad
 * hook order or a crash on real data fails here instead of in the browser.
 *
 *   npm run smoke            # backend must be listening on :8000
 */
import { renderToString } from 'react-dom/server'
import { StaticRouter } from 'react-router-dom/server'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider } from '../src/lib/auth'
import { App } from '../src/App'

const API = process.env.DMP_API ?? 'http://127.0.0.1:8000'

/* --- minimal browser shims, enough for the modules we import --------- */
const store = new Map<string, string>()
;(globalThis as any).localStorage = {
  getItem: (k: string) => store.get(k) ?? null,
  setItem: (k: string, v: string) => void store.set(k, v),
  removeItem: (k: string) => void store.delete(k),
}
;(globalThis as any).window = {
  location: { href: '/' },
  matchMedia: () => ({ matches: false }),
  localStorage: (globalThis as any).localStorage,
}
;(globalThis as any).document = { documentElement: { dataset: {} }, addEventListener() {}, removeEventListener() {} }
if (!('clipboard' in globalThis.navigator)) {
  Object.defineProperty(globalThis.navigator, 'clipboard', { value: undefined, configurable: true })
}

let token = ''
const get = async (path: string) => {
  const response = await fetch(`${API}/api${path}`, { headers: { authorization: `Bearer ${token}` } })
  if (!response.ok) throw new Error(`GET ${path} -> ${response.status}`)
  return response.json()
}

/** Query keys the pages use, paired with the endpoint that fills them. */
function cacheEntries(dpId: number, publishedId: number): [readonly unknown[], string][] {
  return [
    [['metrics'], '/metrics'],
    [['platform'], '/platform/info'],
    [['events'], '/events?limit=18'],
    [['domains'], '/domains'],
    [['policies'], '/policies'],
    [['lineage'], '/lineage'],
    [['users'], '/users'],
    [['dataproducts', 'mine'], '/dataproducts?scope=mine'],
    [['dataproducts', 'all'], '/dataproducts'],
    [['dataproducts', 'all', '', '', ''], '/dataproducts?scope=all'],
    [['templates', 'dataproduct'], '/templates?type=dataproduct'],
    [['marketplace', '', '', '', ''], '/marketplace'],
    [['access', 'inbox'], '/marketplace/access-requests/inbox'],
    [['access', 'outbox'], '/marketplace/access-requests/outbox'],
    [['access', 'subs'], '/marketplace/me/subscriptions'],
    [['dataproduct', dpId], `/dataproducts/${dpId}`],
    [['dp-events', dpId], `/dataproducts/${dpId}/events?limit=15`],
    [['marketplace', publishedId], `/marketplace/${publishedId}`],
    [['dp-lineage', publishedId], `/dataproducts/${publishedId}/lineage?depth=2`],
  ]
}

async function main() {
  const login = await fetch(`${API}/api/auth/login`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ username: process.env.DMP_USER ?? 'alice', password: 'password123' }),
  }).catch(() => null)
  if (!login?.ok) {
    console.error(`cannot reach the backend at ${API} — start it first`)
    process.exit(2)
  }
  const session = await login.json()
  token = session.accessToken
  store.set('dmp.token', token)

  const products: any[] = await get('/dataproducts')
  const mine = products.find((p) => p.owner?.username === session.user.username) ?? products[0]
  const published = products.find((p) => p.lifecycle === 'published') ?? mine

  const cache = new Map<string, unknown>()
  for (const [key, url] of cacheEntries(mine.id, published.id)) {
    try {
      cache.set(JSON.stringify(key), await get(url))
    } catch (error) {
      console.warn(`  warn priming ${url}: ${(error as Error).message}`)
    }
  }

  const routes = [
    '/', '/products', '/create', '/marketplace', '/access', '/governance', '/domains', '/lineage',
    `/products/${mine.id}`, `/marketplace/${published.id}`,
  ]

  let failures = 0
  for (const route of routes) {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
    for (const [key, value] of cache) queryClient.setQueryData(JSON.parse(key), value)
    try {
      const html = renderToString(
        <QueryClientProvider client={queryClient}>
          <StaticRouter location={route}>
            <AuthProvider initialUser={session.user}>
              <App />
            </AuthProvider>
          </StaticRouter>
        </QueryClientProvider>,
      )
      // enough markup that the page rendered its shell and at least one card
      const populated = html.length > 3000
      console.log(`  ${populated ? 'ok  ' : 'thin'} ${route.padEnd(26)} ${html.length} bytes`)
      if (!populated) failures += 1
    } catch (error) {
      failures += 1
      console.error(`  FAIL ${route}: ${(error as Error).message}`)
    }
  }

  console.log(failures === 0 ? `\nall ${routes.length} routes render with data` : `\n${failures} route(s) failed`)
  process.exit(failures === 0 ? 0 : 1)
}

main()
