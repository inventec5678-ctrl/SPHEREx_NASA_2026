// Position parsing (decimal, sexagesimal, names): node scripts/test_sky.mjs   (also: npm test)
import { parseSky } from '../src/sky.js'
const cases = [
  ['133.795 -7.245', [133.795, -7.245]], ['133.795, -7.245', [133.795, -7.245]], ['269.446 +4.768', [269.446, 4.768]],
  ['08h55m10.831s -7d14m42.53s', [133.79513, -7.24515]], ['08:55:10.8 -07:14:42', [133.795, -7.245]],
  ['08 55 10.8 -07 14 42', [133.795, -7.245]], ['12h30m +10d20m', [187.5, 10.3333]], ['12h30m 10d', [187.5, 10]],
  ['12h30m', null], ['10', null], ['400 10', null], ['10 95', null], ['17h57m48.5s +04d41m36s', [269.452, 4.6933]],
  ['12.5h +10', [187.5, 10]], ['0 0', [0, 0]], ['183.2 -1.4', [183.2, -1.4]], ['M31', null], ['12 30 45 10 20 30', [187.6875, 10.3417]],
]
let bad = 0
for (const [q, want] of cases) {
  const v = parseSky(q)
  const ok = want === null ? v === null : v && Math.abs(v.ra - want[0]) < 2e-3 && Math.abs(v.dec - want[1]) < 2e-3
  if (!ok) { bad++; console.log('FAIL', JSON.stringify(q), v, want) }
}
for (const [q, id] of [['barnard', 'barnard'], ["Barnard's Star", 'barnard'], ['eps ind b', 'epsindi'], ['WISE 0855', 'wise0855'], ['RW Aur', 'rwaur'], ['R Dra', 'rdra'], ['R Draconis', 'rdra']]) {
  if (parseSky(q)?.id !== id) { bad++; console.log('FAIL name', q, parseSky(q)) }
}
console.log(bad ? `${bad} failed` : "all parse cases pass"); process.exit(bad ? 1 : 0)
