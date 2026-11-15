// One playback loop for every player on the site: the sky viewer, the quick-look player, the lab's blink of survey
// passes, the two-frame blink of a candidate, the object page and the home-page story. Each keeps its own picture
// and controls; the frame counter, the timer, "reduced motion means nothing plays by itself" and the keys live here.
import { useCallback, useEffect, useRef, useState } from 'react'
import { reducedMotion } from './lib.js'

/**
 * n        number of frames (may change while frames stream in)
 * hz       frames per second
 * autoplay start playing (ignored when the system asks for reduced motion)
 * active   false pauses the timer without changing `playing` (a view that is not on screen)
 * loop     wrap around at the end; when false, playback stops on the last frame and onEnd() is called
 * start    first frame
 * Returns { k, setK, playing, setPlaying, toggle, step, seek, onKey }.
 */
export function usePlayback(n, { hz = 2, autoplay = true, active = true, loop = true, onEnd, start = 0 } = {}) {
  const [k, setK] = useState(start)
  const [playing, setPlaying] = useState(() => autoplay && !reducedMotion())
  const end = useRef(onEnd); end.current = onEnd
  useEffect(() => {
    if (!playing || !active || n < 2 || !(hz > 0)) return
    const id = setInterval(() => setK((x) => {
      if (x + 1 < n) return x + 1
      if (loop) return 0
      queueMicrotask(() => { setPlaying(false); end.current?.() })
      return x
    }), 1000 / hz)
    return () => clearInterval(id)
  }, [playing, active, n, hz, loop])
  const cur = n > 0 ? Math.min(Math.max(0, k), n - 1) : 0
  const step = useCallback((d) => { if (n < 1) return; setPlaying(false); setK((x) => ((Math.min(x, n - 1) + d) % n + n) % n) }, [n])
  const seek = useCallback((v) => { setPlaying(false); setK(v) }, [])
  const toggle = useCallback(() => setPlaying((p) => !p), [])
  /** Space plays or pauses, the arrows step, Home / End jump. Returns true when the key was used. */
  const onKey = (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey || n < 1) return false
    if (e.key === ' ') toggle()
    else if (e.key === 'ArrowRight') step(1)
    else if (e.key === 'ArrowLeft') step(-1)
    else if (e.key === 'Home') seek(0)
    else if (e.key === 'End') seek(n - 1)
    else return false
    e.preventDefault()
    return true
  }
  return { k: cur, setK, playing, setPlaying, toggle, step, seek, onKey }
}
