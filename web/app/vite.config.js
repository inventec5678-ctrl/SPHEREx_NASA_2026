import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve, relative, join } from 'node:path'
import { cpSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'

const SRC = resolve(import.meta.dirname, 'src')

// Build-time helpers for index.html and dist/ (see UPGRADE_PLAN.md §8, T1/T5/T8):
//  - preload the one Latin font every page uses (Manrope, Latin subset);
//  - a tiny inline script that looks at the URL and starts downloading that page's code (and its field data)
//    at the same time as the entry chunk, instead of entry → page chunk → data one after another;
//  - keep the previous build's /assets next to the new one, so a tab opened before a redeploy can still
//    fetch the lazy chunk it asks for (main.jsx also reloads once on a failed chunk import).
function sxBuild() {
  let outDir, cacheDir
  const keepList = () => join(outDir, '.sx-build-files.json')
  return {
    name: 'sx-build',
    apply: 'build',
    configResolved(c) { outDir = resolve(c.root, c.build.outDir); cacheDir = resolve(c.root, 'node_modules/.cache/sx-prev-assets') },
    buildStart() {
      // copy only the files the last build itself emitted (one generation back, not an ever-growing pile)
      rmSync(cacheDir, { recursive: true, force: true })
      if (!existsSync(keepList())) return
      mkdirSync(cacheDir, { recursive: true })
      for (const f of JSON.parse(readFileSync(keepList(), 'utf8'))) {
        const p = join(outDir, f)
        if (existsSync(p)) cpSync(p, join(cacheDir, f), { recursive: false })
      }
    },
    transformIndexHtml: {
      order: 'post',
      handler(html, ctx) {
        const bundle = ctx.bundle
        if (!bundle) return html
        const chunks = Object.values(bundle).filter((c) => c.type === 'chunk')
        const byFile = new Map(chunks.map((c) => [c.fileName, c]))
        // everything the entry already loads statically (index.html links it) is left out of the per-page lists
        const entries = new Set()
        const walk = (f) => { if (entries.has(f) || !byFile.has(f)) return; entries.add(f); byFile.get(f).imports.forEach(walk) }
        chunks.filter((c) => c.isEntry).forEach((c) => walk(c.fileName))
        const deps = (c, seen = new Set()) => {
          for (const f of [c.fileName, ...c.imports]) {
            if (seen.has(f) || entries.has(f)) continue
            seen.add(f)
            if (f !== c.fileName && byFile.has(f)) deps(byFile.get(f), seen)
          }
          return seen
        }
        const map = {}
        for (const c of chunks) {
          if (!c.isDynamicEntry || !c.facadeModuleId) continue
          const name = relative(SRC, c.facadeModuleId).replaceAll('\\', '/')
          const js = [...deps(c)]
          const css = [...new Set(js.flatMap((f) => [...(byFile.get(f)?.viteMetadata?.importedCss || [])]))]
          map[name] = { j: js.map((f) => '/' + f), c: css.map((f) => '/' + f) }
        }
        const font = Object.keys(bundle).find((f) => /manrope-latin-wght-normal-[^/]*\.woff2$/.test(f))
        const script = `(function(){try{var M=${JSON.stringify(map)},d=document,P=function(r,h,a){var l=d.createElement('link');l.rel=r;l.href=h;if(a)l.as=a;if(a==='fetch')l.crossOrigin='anonymous';d.head.appendChild(l)},`
          + `G=function(n){var m=M[n];if(!m)return;m.j.forEach(function(h){P('modulepreload',h)});m.c.forEach(function(h){P('preload',h,'style')})},`
          + `h=location.hash.replace(/^#\\/?/,'').split('?')[0].split('/'),q=new URLSearchParams(location.search),s=h[0]||'',`
          + `R={field:h[2]==='track'?'object.jsx':'viewer.jsx',lab:'lab.jsx',target:'target.jsx',targets:'target.jsx',sky:'skyresolve.jsx',embed:'embed.jsx',movers:'movers.jsx',guide:'guide.jsx',story:'storypage.jsx',features:'features.jsx',discovery:'discovery.jsx',follow:'follow.jsx',comet:'comet.jsx',credits:'credits.jsx',universe:'universe/UniversePage.jsx'},`
          + `k=(q.get('ra')||q.get('target')||q.get('q'))?(q.has('embed')?'embed.jsx':'skyresolve.jsx'):R[s];if(k)G(k);`
          + `if(/^(field|lab|target)$/.test(s)&&h[1])P('preload','/api/field/'+encodeURIComponent(decodeURIComponent(h[1])),'fetch');`
          + `var L=q.get('lang'),en=true;try{en=L?L==='en':localStorage.getItem('sx:language:v1')!=='zh-Hant'}catch(e){}if(en)G('i18n/catalog.js')}catch(e){}})()`
        const tags = [{ tag: 'script', children: script, injectTo: 'head' }]
        if (font) tags.unshift({ tag: 'link', attrs: { rel: 'preload', href: '/' + font, as: 'font', type: 'font/woff2', crossorigin: '' }, injectTo: 'head' })
        return { html, tags }
      },
    },
    writeBundle(_, bundle) {
      writeFileSync(keepList(), JSON.stringify(Object.keys(bundle).filter((f) => f.startsWith('assets/'))))
    },
    closeBundle() {
      if (!existsSync(cacheDir)) return
      cpSync(cacheDir, outDir, { recursive: true, force: false, errorOnExist: false })
      rmSync(cacheDir, { recursive: true, force: true })
    },
  }
}

export default defineConfig({
  plugins: [react({ jsxImportSource: '@sx/i18n' }), sxBuild()],
  resolve: { alias: { '@sx/i18n': resolve(import.meta.dirname, 'src/i18n') } },
  // the dev server forwards data and API calls to a running web app (SX_API picks another one, e.g. a test instance)
  server: { proxy: Object.fromEntries(['/api', '/data', '/models'].map((k) => [k, process.env.SX_API || 'http://127.0.0.1:8791'])) },
  build: {
    target: 'es2022',
    sourcemap: false,
    rollupOptions: {
      output: {
        // React changes far less often than the site: its own file stays cached across redeploys
        manualChunks: (id) => (/node_modules\/(react|react-dom|scheduler)\//.test(id) ? 'react' : undefined),
      },
    },
  },
})
