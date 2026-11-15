// Offline shell and image cache (UPGRADE_PLAN.md §8, T13). The site runs through a tunnel that can drop for a few
// seconds; a page already open keeps working, and images already seen show again without the network.
//   pages (navigation)       network first, the last copy of the shell when offline
//   /assets/*, /media/*      cache first (file names carry a content hash, or never change)
//   /data/** images, .bin    stale-while-revalidate, at most ~800 entries
//   /api/*, everything else  network only (never cached here)
const V = 'sx-v1', SHELL = `${V}-shell`, STATIC = `${V}-static`, DATA = `${V}-data`
self.addEventListener('install', (e) => { self.skipWaiting(); e.waitUntil(caches.open(SHELL).then((c) => c.add('/')).catch(() => {})) })
self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => !k.startsWith(V)).map((k) => caches.delete(k)))).then(() => self.clients.claim()))
})
async function trim(name, max) {
  const c = await caches.open(name), ks = await c.keys()
  for (let i = 0; i < ks.length - max; i++) await c.delete(ks[i])
}
self.addEventListener('fetch', (e) => {
  const r = e.request
  if (r.method !== 'GET') return
  const u = new URL(r.url)
  if (u.origin !== location.origin || u.pathname.startsWith('/api/')) return
  if (r.mode === 'navigate') {
    e.respondWith(fetch(r).then((res) => { if (res.ok && u.pathname === '/') { const cp = res.clone(); caches.open(SHELL).then((c) => c.put('/', cp)) } return res })
      .catch(() => caches.match('/', { ignoreSearch: true }).then((m) => m || Response.error())))
    return
  }
  if (u.pathname.startsWith('/assets/') || u.pathname.startsWith('/media/')) {
    e.respondWith(caches.match(r).then((m) => m || fetch(r).then((res) => { if (res.ok) { const cp = res.clone(); caches.open(STATIC).then((c) => c.put(r, cp)) } return res })))
    return
  }
  if (u.pathname.startsWith('/data/') && /\.(webp|png|jpg|bin)$/.test(u.pathname) && !r.headers.has('range')) {
    e.respondWith(caches.open(DATA).then((c) => c.match(r).then((m) => {
      const net = fetch(r).then((res) => { if (res.ok && res.status === 200) { c.put(r, res.clone()); trim(DATA, 800) } return res }).catch(() => m || Response.error())
      return m || net
    })))
  }
})
