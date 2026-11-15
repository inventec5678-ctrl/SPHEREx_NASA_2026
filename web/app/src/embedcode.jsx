// "Embed this" box: the iframe snippet and the plain coordinate link for a position or a field.
import { useState } from 'react'
import { L } from './lib.js'
import { hashParams } from './sky.js'

/** Height the embedded player needs at 640 px wide (canvas + controls + footer); measured, with a little slack. */
export const EMBED_H = 860

// the link carries the position and what is on screen now (mode, detector, paused frame), never the viewer's language
const VIEW_KEYS = ['v', 'd', 'k']
const view = () => { const u = hashParams(); return VIEW_KEYS.filter((k) => u.get(k) != null).map((k) => `&${k}=${encodeURIComponent(u.get(k))}`).join('') }
const COPIED_MS = 1500

export function EmbedCode({ ra, dec, fov, target }) {
  const [done, setDone] = useState(null)
  const base = target ? `target=${target}` : `ra=${(+ra).toFixed(4)}&dec=${(+dec).toFixed(4)}${fov ? `&fov=${fov}` : ''}`
  const [extra, setExtra] = useState('')
  const qs = base + extra
  const refresh = () => setExtra(view())
  const link = `${location.origin}/?${qs}`
  const frame = `<iframe src="${location.origin}/?${qs}&embed=1" width="640" height="${EMBED_H}" style="border:0;max-width:100%" loading="lazy" title="SPHEREx Sky Change"></iframe>`
  const copy = (k, v) => { navigator.clipboard?.writeText(v).then(() => { setDone(k); setTimeout(() => setDone(null), COPIED_MS) }) }
  return (
    <div className="embed-code" onMouseEnter={refresh} onFocus={refresh}>
      <h3>{L('分享與嵌入', 'Share and embed')}</h3>
      <p className="hint">{L('座標和目前的畫面（顯示模式、偵測器、暫停時的那一張）都寫在網址裡，任何網站或程式都能直接連結或嵌入這個播放器。', 'The position and the current view (mode, detector, the frame you paused on) are in the URL, so any website or script can link to or embed this player.')}</p>
      <div className="embed-line"><code tabIndex={0} aria-label={L('連結', 'Link')}>{link}</code><button className="btn small" onClick={() => copy('link', link)}>{done === 'link' ? L('已複製', 'Copied') : L('複製連結', 'Copy link')}</button></div>
      <div className="embed-line"><code tabIndex={0} aria-label={L('嵌入碼', 'Embed code')}>{frame}</code><button className="btn small" onClick={() => copy('frame', frame)}>{done === 'frame' ? L('已複製', 'Copied') : L('複製嵌入碼', 'Copy embed code')}</button></div>
      <a className="btn small" href={`${link}&embed=1`} target="_blank" rel="noopener">{L('預覽嵌入版 ↗', 'Preview the embed ↗')}</a>
    </div>
  )
}
