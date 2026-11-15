// The viewer's default "3D universe" mode: the field as a universe of bodies built from their spectra,
// with asteroids (and the simulated planet) moving to where they were at the current time of the player.
// Click a body to select it; click empty sky to check whether that point could be a planet.
// `labels` ([{ key, node }]) are HTML name tags the scene keeps over the matching bodies every frame.
import { useEffect, useMemo, useRef, useState } from 'react'
import { api, reducedMotion } from './lib.js'
import { UniverseScene } from './universe/scene.js'
import { TYPE_LABEL, bodyTitle, toBodies } from './universe/Universe.jsx'

export default function Sky3D({ field, mjd, sel, labels = [], frame, onPickTrack, onPickSource, onPlane, onReady }) {
  const cv = useRef(), scene = useRef(null), cbs = useRef({}), tags = useRef(new Map())
  cbs.current = { onPickTrack, onPickSource, onPlane }
  const [hover, setHover] = useState(null)
  const [state, setState] = useState('loading')
  useEffect(() => {
    let dead = false
    try {
      scene.current = new UniverseScene(cv.current, {
        reducedMotion: reducedMotion(), noShift: true,
        onPick: (d) => { if (!d) return; if (d.group === 'mover') cbs.current.onPickTrack(d.src.track); else cbs.current.onPickSource(d.src) },
        onHover: (h) => setHover(h && h.data.group !== 'mover' ? h : null),   // movers carry their own name tags
        onPlane: (p) => cbs.current.onPlane(p),
      })
      scene.current.setLabels(tags.current)
    } catch { setState('nogl'); return }
    api(`/data/fields/${encodeURIComponent(field.id)}/universe.json`).then((uni) => {
      if (dead) return
      const bs = toBodies(uni, field)
      scene.current.load({ W: uni.shape[1], H: uni.shape[0], imageUrl: `/data/fields/${field.id}/deep_rgb.webp`, bodies: bs })
      scene.current.setTime(mjd); scene.current.expand(true); setState('ready'); onReady?.()
      window.__sxScene = scene.current     // test hook: the viewer's 3D scene is built
    }).catch(() => setState('error'))
    return () => { dead = true; scene.current?.destroy(); scene.current = null }
  }, [field]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { scene.current?.setTime(mjd) }, [mjd])
  useEffect(() => { if (frame) scene.current?.setFrame(frame) }, [frame?.l, frame?.t, frame?.r, frame?.b, state]) // eslint-disable-line react-hooks/exhaustive-deps
  // the name tags, rebuilt only when the labels change (stable elements keep their refs attached)
  const tagEls = useMemo(() => state === 'ready' && labels.map(({ key, node }) => (
    <div key={key} className="tag3d" style={{ visibility: 'hidden' }} ref={(el) => { if (el) tags.current.set(key, el); else tags.current.delete(key) }}>{node}</div>
  )), [labels, state])
  useEffect(() => {
    const sc = scene.current; if (!sc || state !== 'ready') return
    if (sel == null) { sc.select(null); return }
    const it = sc.items.find((x) => x.data.key === `m${sel}`)
    if (it) sc.select(it)
  }, [sel, state])
  return (
    <div className="sky3d">
      <canvas ref={cv} aria-label="這片天空的 3D 宇宙：拖曳旋轉、滾輪縮放；點一顆星或小行星看它的資料，點空白處檢查那裡是不是行星" />
      {tagEls}
      {state === 'loading' && <p className="st-load">正在建構這片天空…</p>}
      {state === 'nogl' && <p className="st-load">這個瀏覽器不支援 WebGL，請改用「影像」。</p>}
      {hover && <div className="u-tip" style={{ left: hover.x + 14, top: hover.y + 14 }}><b>{bodyTitle(hover.data)}</b><span>{TYPE_LABEL[hover.data.type]}</span></div>}
    </div>
  )
}
