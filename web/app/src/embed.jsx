// #/embed/<query>[?fov=0.3]: a chrome-less player for iframes on other websites.
// <query> is a field id, a challenge target name, or coordinates (decimal or sexagesimal). An analysed field plays its
// own frames (images, differences, pass stacks); any other position starts a quick look.
//   <iframe src="https://<host>/?ra=133.795&dec=-7.245&embed=1" width="640" height="760"></iframe>
import { useEffect, useMemo, useState } from 'react'
import { useLanguage } from '@sx/i18n/language.jsx'
import { L, api, frameUrl, getField } from './lib.js'
import { parseSky, sep } from './sky.js'
import { Player, QuickLook } from './quick.jsx'
import { fieldName } from './fields_text.js'
import { targetName } from './targets_meta.jsx'

const DETS = [1, 2, 3, 4, 5, 6]
const titleOf = (f) => (f.target ? targetName(f.target) : fieldName(f))

function FieldPlayer({ field }) {
  // contamination flags: the per-exposure overlay and the share of each SPHEREx flag (older fields: three groups)
  const frames = useMemo(() => field.exposures.map((e) => ({
    sci: frameUrl(field, 'sci', e.i), diff: frameUrl(field, 'diff', e.i), mjd: e.mjd, iso: e.iso, det: e.detector, lam: e.lam_um, rel: e.release,
    flag: field.products?.flags ? `/data/fields/${field.id}/flag/${String(e.i).padStart(4, '0')}.webp` : null,
    fl: e.flag_frac || (e.flags && { UNUSABLE: e.flags.bad, GHOST: e.flags.ghost, OUTLIER: e.flags.outlier }),
  })), [field])
  const stacks = useMemo(() => (field.products?.passes || []).flatMap((p) => DETS.filter((d) => p.dets.includes(d)).map((d) => ({
    url: `/data/fields/${field.id}/pass/p${p.k}_d${d}.webp`, pass: p.k, det: d, n: p.n_det[d - 1],
  }))), [field])
  // the challenge targets: mark where the target is in each pass
  const marks = useMemo(() => (field.target?.passes || []).map((p) => ({ x: p.x, y: p.y, k: p.k, mjd0: p.mjd0, mjd1: p.mjd1, c: '#ffb547' })), [field])
  return <Player frames={frames} stacks={stacks} geo={field} compact marks={marks}
    title={titleOf(field)} />
}

export default function Embed({ q, fov }) {
  useLanguage()
  const [st, setSt] = useState({ s: 'look' })
  useEffect(() => {
    document.documentElement.classList.add('embed-mode')
    return () => document.documentElement.classList.remove('embed-mode')
  }, [])
  useEffect(() => {
    let live = true
    api('/api/fields').then(async (fs) => {
      const byId = fs.find((f) => f.id === q)
      let v = byId ? { id: q } : parseSky(q)
      if (!v && /[a-z]/i.test(q)) v = await api(`/api/resolve?q=${encodeURIComponent(q.trim())}`).then((r) => ({ ra: r.ra, dec: r.dec })).catch(() => null)
      if (!v) return live && setSt({ s: 'bad' })
      let id = v.id
      if (!id && fov == null) {
        const hit = fs.map((f) => ({ f, d: sep(v.ra, v.dec, f.ra, f.dec) })).filter((x) => x.d < x.f.size_deg * 0.45).sort((a, b) => a.d - b.d)[0]
        id = hit?.f.id
      }
      if (id) { const f = await getField(id); if (live) setSt({ s: 'field', f }) }
      else if (live) setSt({ s: 'quick', ...v })
    }).catch(() => live && setSt({ s: 'err' }))
    return () => { live = false }
  }, [q, fov])
  useEffect(() => { document.title = `SPHEREx Sky Change · ${st.s === 'field' ? titleOf(st.f) : q}` }, [st, q])
  const site = `${location.origin}/#/sky/${encodeURIComponent(q)}`
  return (
    <div className="embed">
      {st.s === 'look' && <div className="route-loading" role="status"><i aria-hidden="true" /></div>}
      {st.s === 'bad' && <p className="note">{L('看不懂這個座標。', 'Could not read that position.')}</p>}
      {st.s === 'err' && <p className="note">{L('暫時連不上伺服器。', 'Cannot reach the server.')}</p>}
      {st.s === 'field' && <FieldPlayer field={st.f} />}
      {st.s === 'quick' && <QuickLook ra={st.ra} dec={st.dec} size={fov || 0.3} compact />}
      <a className="embed-foot" href={site} target="_blank" rel="noopener">SPHEREx Sky Change ↗</a>
    </div>
  )
}
