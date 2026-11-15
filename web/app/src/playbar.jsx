// The one play bar of the site (UPGRADE_PLAN.md §8, V8): a play/pause button, a frame slider, the frame count and,
// where it applies, the speed. Every player shares the playback loop in play.js; this gives them the same controls.
import { L } from './lib.js'
import { ICON } from './icons.jsx'

/** Play / pause: the primary button with an icon. `bare` drops the text (round bars with little room). */
export function PlayButton({ playing, onClick, small = true, bare = false }) {
  const label = playing ? L('暫停', 'Pause') : L('播放', 'Play')
  return (
    <button type="button" className={`btn primary playbtn ${small ? 'small' : ''} ${bare ? 'icon' : ''}`} onClick={onClick} aria-pressed={playing} aria-label={bare ? label : undefined}>
      {playing ? ICON.pause : ICON.play}{!bare && <span>{label}</span>}
    </button>
  )
}

/**
 * pb      the object usePlayback() returns
 * n       number of frames
 * slider  show the frame slider (false for two or three passes: a "next" button instead)
 * speeds  [values] with hz / setHz: frames-per-second choices
 */
export function PlayBar({ pb, n, slider = true, speeds, hz, setHz, label, children }) {
  return (
    <div className="playbar" role="group" aria-label={label || L('播放', 'Playback')}>
      <PlayButton playing={pb.playing} onClick={pb.toggle} />
      {slider && n > 1
        ? <input type="range" min="0" max={Math.max(0, n - 1)} value={pb.k} onChange={(e) => pb.seek(+e.target.value)} aria-label={L('影像', 'Frame')} />
        : <button type="button" className="btn small" onClick={() => pb.step(1)} disabled={n < 2}>{L('下一張', 'Next')}{ICON.next}</button>}
      <span className="playbar-count num" aria-live="off">{n ? `${pb.k + 1} / ${n}` : '0'}</span>
      {speeds && <div className="seg" role="group" aria-label={L('速度', 'Speed')}>
        {speeds.map((v) => <button key={v} aria-pressed={hz === v} onClick={() => setHz(v)}>{v}/s</button>)}
      </div>}
      {children}
    </div>
  )
}
