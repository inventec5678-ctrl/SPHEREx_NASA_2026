import { ICON } from './icons.jsx'
import { evidenceChecks } from './lib.js'

/** Three plain checks: why we believe (or doubt) this object. */
export function Checks({ field, tr, compact }) {
  return (
    <ul className={`checks ${compact ? 'compact' : ''}`}>
      {evidenceChecks(field, tr).map((c) => (
        <li key={c.key} className={c.ok === true ? 'ok' : c.ok === false ? 'no' : 'na'}>
          <i aria-hidden="true">{c.ok === true ? ICON.check : c.ok === false ? ICON.alert : ICON.dot}</i>
          <span><b>{c.label}</b>{!compact && <small>{c.note}</small>}</span>
        </li>
      ))}
    </ul>
  )
}

