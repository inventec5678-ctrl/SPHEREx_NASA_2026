// Fails the build if files the site depends on are missing from web/app/dist (Analog Atlas lesson:
// anything that only exists in dist/ is wiped by the next `vite build`; keep it in public/).
import { existsSync, readdirSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
const dist = join(dirname(fileURLToPath(import.meta.url)), '..', 'web', 'app', 'dist')
const required = ['index.html', 'media/favicon.svg', 'media/hero_blink.webp', 'media/hero_poster.webp', 'media/step_sky.webp',
  'media/step_diff.webp', 'media/step_ai.webp', 'paper/index.html', 'paper/zh.html', 'paper/paper.html', 'paper/paper-zh.html', 'paper/en.html', 'paper/paper-en.html',
  'paper/paper.css', 'paper/research/evidence.json', 'paper/research/planetx_grid.json', 'paper/research/manifest.json']
const missing = required.filter((f) => !existsSync(join(dist, f)))
const assets = existsSync(join(dist, 'assets')) ? readdirSync(join(dist, 'assets')) : []
if (!assets.some((f) => f.endsWith('.js'))) missing.push('assets/*.js')
if (missing.length) { console.error('check_dist: MISSING\n  ' + missing.join('\n  ')); process.exit(process.env.SX_ALLOW_MISSING ? 0 : 1) }
console.log(`check_dist: ok (${required.length} required files, ${assets.length} assets)`)
