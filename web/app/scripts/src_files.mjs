// Shared by the source audits (check_refs, audit_i18n): list src/ script files, and print paths the same way on
// every platform (Windows paths use backslashes; new URL(...).pathname would give "/D:/..." there).
import { readdirSync, statSync } from 'node:fs'
import { join, relative, sep } from 'node:path'
import { fileURLToPath } from 'node:url'

export const SRC = fileURLToPath(new URL('../src', import.meta.url))

/** Every .js/.jsx file under src/, skipping directory names in `skip`. */
export function srcFiles(skip = []) {
  const out = []
  const walk = (d) => {
    for (const f of readdirSync(d)) {
      const p = join(d, f)
      if (statSync(p).isDirectory()) { if (!skip.includes(f)) walk(p) } else if (/\.jsx?$/.test(f)) out.push(p)
    }
  }
  walk(SRC)
  return out
}

/** "src/viewer.jsx" for a file under src/ (forward slashes everywhere). */
export const shortName = (p) => 'src/' + relative(SRC, p).split(sep).join('/')
