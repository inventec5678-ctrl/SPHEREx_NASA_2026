// The one search box of the site: type a position (decimal or sexagesimal) or an object name, press Enter, and the
// image sequence of that patch of sky plays. Used at the top of the home page, in the top bar and above the sky map.
import { useEffect, useState } from 'react'
import { useLanguage } from '@sx/i18n/language.jsx'
import { L, api } from './lib.js'
import { COORD_CHARS, DEFAULT_FOV, EXAMPLES, TARGET_IDS, parseSky, skyHash } from './sky.js'

export const FOVS = [0.15, DEFAULT_FOV, 0.6]
const N_TARGETS = TARGET_IDS.length          // the examples start with the challenge targets; the rest fold under "more"
const FOLLOW_DELAY_MS = 500
const followAsked = new Map()                 // name -> the resolver's answer (a promise), so retyping a name asks once
/** Where a query leads: a challenge target's own page, or the sky page (which resolves names and coordinates). */
export function openSky(q, fov) {
  const v = parseSky(q)
  location.hash = v?.id ? `#/target/${v.id}` : skyHash(v ? `${+v.ra.toFixed(5)} ${+v.dec.toFixed(5)}` : q, fov)
}

/** A name JPL's Small-Body Database knows (an asteroid or a comet, which SIMBAD does not list): offer to follow it
 *  through every SPHEREx image (#/follow). Asked 0.5 s after typing stops; on the "name not found" page the name in the
 *  address is asked. */
function FollowHint({ q }) {
  const [hit, setHit] = useState(null)
  useEffect(() => {
    setHit(null)
    const s = q.trim()
    if (s.length < 2 || s.length > 60 || parseSky(s) || COORD_CHARS.test(s)) return
    let live = true
    const id = setTimeout(() => {
      if (!followAsked.has(s)) followAsked.set(s, api(`/api/follow/resolve?q=${encodeURIComponent(s)}`).catch((e) => { followAsked.delete(s); throw e }))
      followAsked.get(s).then((r) => live && r.status === 'ok' && setHit(r)).catch(() => {})
    }, FOLLOW_DELAY_MS)
    return () => { live = false; clearTimeout(id) }
  }, [q])
  if (!hit) return null
  const what = hit.kind === 'comet' ? L('彗星', 'a comet') : L('小行星', 'an asteroid')
  return <p className="ss-hint" role="status"><a className="chip" href={`#/follow/${encodeURIComponent(hit.short || hit.name)}`}>{L(`${hit.name} 是一顆${what}：看 SPHEREx 拍到它的每一張影像 →`, `${hit.name} is ${what}: follow it through every SPHEREx image →`)}</a></p>
}

export function SkySearch({ compact, value, onValue, id = 'sky-q', examples = true, autoFocus, label }) {
  useLanguage()
  const [own, setOwn] = useState('')
  const q = value ?? own, setQ = onValue ?? setOwn
  const [fov, setFov] = useState(DEFAULT_FOV)
  const [err, setErr] = useState(null)
  const [more, setMore] = useState(false)
  useEffect(() => { setErr(null) }, [q])
  function submit(e) {
    e.preventDefault()
    const s = q.trim()
    if (!s) { setErr(L('請輸入座標或天體名稱。', 'Type a position or an object name.')); return }
    // only digits and coordinate marks, yet not a position: say what is wrong instead of asking the name resolver
    if (!parseSky(s) && COORD_CHARS.test(s)) {
      setErr(L('看不懂這個座標。需要赤經和赤緯兩個值，例如 133.795 -7.245 或 08h55m10.8s -07d14m42s。', 'That is not a position. Give both RA and Dec, e.g. 133.795 -7.245 or 08h55m10.8s -07d14m42s.'))
      return
    }
    openSky(s, fov)
  }
  return (
    <div className={`skysearch ${compact ? 'compact' : ''}`}>
      <form onSubmit={submit} role="search" aria-label={label || L('看任何一片天空', 'Look at any patch of sky')}>
        <label className="sr-only" htmlFor={id}>{L('座標或天體名稱', 'Position or object name')}</label>
        <input id={id} type="search" enterKeyHint="go" autoComplete="off" spellCheck="false" autoFocus={autoFocus} value={q} onChange={(e) => setQ(e.target.value)}
          aria-invalid={err ? 'true' : undefined} aria-describedby={err ? `${id}-err` : undefined}
          placeholder={compact ? L('座標或天體名稱', 'Position or object name') : L('輸入赤經赤緯或天體名稱，例如 133.795 -7.245', 'RA Dec or an object name, e.g. 133.795 -7.245')} />
        {!compact && (
          <label className="ss-fov">{L('視野', 'Field')}
            <select value={fov} onChange={(e) => setFov(+e.target.value)} aria-label={L('視野大小', 'Field of view')}>
              {FOVS.map((z) => <option key={z} value={z}>{z}° ({Math.round(z * 60)}′)</option>)}
            </select>
          </label>
        )}
        <button className="btn primary" type="submit">{compact ? L('看', 'Go') : L('播放這片天空', 'Play this sky')}</button>
      </form>
      {err && <p id={`${id}-err`} className="ss-err" role="alert">{err}</p>}
      {!compact && <FollowHint q={q.trim() || (location.hash.startsWith('#/sky/') ? decodeURIComponent(location.hash.slice(6).split('?')[0]) : '')} />}
      {examples && !compact && (
        <div className="ss-ex">
          <span>{L('試試：', 'Try: ')}</span>
          {/* the five challenge targets; the finished quick looks behind "more" (one row, not two) */}
          {EXAMPLES.slice(0, more ? EXAMPLES.length : N_TARGETS).map((x) => <button key={x.q} type="button" className="chip" onClick={() => openSky(x.q, x.fov)}>{L(x.zh, x.en)}</button>)}
          {!more && <button type="button" className="chip ghost" aria-expanded="false" onClick={() => setMore(true)}>{L(`更多 ${EXAMPLES.length - 5}`, `${EXAMPLES.length - 5} more`)}</button>}
        </div>
      )}
      {!compact && <p className="ss-hint">{L('十進位度數（133.795 -7.245）、時分秒（08h55m10.8s -07d14m42s），或 SIMBAD 認得的名稱（Kapteyn’s star、M31）。第一批影像約一分鐘內開始播放。', 'Decimal degrees (133.795 -7.245), sexagesimal (08h55m10.8s -07d14m42s), or any name SIMBAD knows (Kapteyn’s star, M31). The first frames play within about a minute.')}</p>}
    </div>
  )
}
