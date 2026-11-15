// Undefined-identifier check for src/ (the bundler does not report a name that is used but never imported or
// declared; it only fails at run time, on the page that uses it):  node scripts/check_refs.mjs   (also: npm test)
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { srcFiles, shortName } from './src_files.mjs'
const require = createRequire(import.meta.url)
const parser = require('@babel/parser')
const traverse = require('@babel/traverse').default
const GLOBALS = new Set(`window document location history navigator localStorage sessionStorage console performance fetch URL URLSearchParams Blob Image ImageData
  Math JSON Date Object Array Map Set WeakMap Promise Number String Boolean Symbol Error RegExp Infinity NaN undefined isFinite isNaN parseFloat parseInt
  Float32Array Float64Array Uint8Array Uint8ClampedArray Uint16Array Int32Array Int16Array ArrayBuffer DataView
  setTimeout clearTimeout setInterval clearInterval requestAnimationFrame cancelAnimationFrame queueMicrotask
  IntersectionObserver MutationObserver ResizeObserver NodeFilter getComputedStyle matchMedia innerWidth innerHeight scrollY scrollX devicePixelRatio
  encodeURIComponent decodeURIComponent alert confirm globalThis structuredClone CustomEvent Event AbortController TextDecoder TextEncoder Intl WebGLRenderingContext
  Element HTMLElement HTMLCanvasElement OffscreenCanvas createImageBitmap process arguments`.split(/\s+/))
const files = srcFiles()
const bad = []
for (const f of files) {
  const ast = parser.parse(readFileSync(f, 'utf8'), { sourceType: 'module', plugins: ['jsx'] })
  traverse(ast, {
    ReferencedIdentifier(path) {
      const n = path.node.name
      if (path.node.type === 'JSXIdentifier' && /^[a-z]/.test(n)) return           // an HTML tag
      if (GLOBALS.has(n) || path.scope.hasBinding(n)) return
      bad.push(`${shortName(f)}:${path.node.loc.start.line} ${n}`)
    },
  })
}
if (bad.length) { console.error(`check_refs: ${bad.length} names used but not defined\n  ` + [...new Set(bad)].join('\n  ')); process.exit(1) }
console.log(`check_refs: ${files.length} files, every name is defined`)
