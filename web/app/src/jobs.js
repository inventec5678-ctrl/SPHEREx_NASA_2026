// Server jobs in one place: starting a full analysis, saying why it was refused, and polling any status endpoint
// (a full analysis, a field refresh, a quick look) until it is done.
import { L, api } from './lib.js'

/** POST a JSON body to an API path; resolves to the JSON answer (rejects with "<path>: <status>" like api()). */
export const postJson = (path, body) =>
  api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

/** POST a full analysis of a position. Resolves to the job record ({id, status, position, log}). */
export const startAnalysis = (ra, dec, size) => postJson('/api/jobs', { ra, dec, size })

/** Why the server refused a job, in the visitor's language. */
export function jobError(e) {
  const m = String(e)
  return m.includes('queue_full') ? L('目前排隊的工作已滿，請稍後再試。', 'The queue is full right now; try again later.')
    : m.includes('bad_size') ? L('視野只能選 0.15°、0.3° 或 0.6°。', 'The field of view must be 0.15°, 0.3° or 0.6°.')
    : m.includes('per_ip_limit') ? L('每人每天最多送出 2 個天區，請明天再試。', 'Two fields per person per day; try again tomorrow.')
    : m.includes('cooldown') ? L('這片天空剛分析失敗，請一小時後再試。', 'This field just failed; try again in an hour.')
    : m.includes('disk_full') || m.includes('jobs_disabled') ? L('伺服器目前暫停接受新的分析。', 'The server is not taking new analyses right now.')
    : m.includes('429') ? L('目前排隊已滿或已達每日上限，請稍後再試。', 'The queue is full or you reached the daily limit; try later.')
    : L('送出失敗，請稍後再試。', 'Could not submit; try again later.')
}

/**
 * Poll `url` every `every` ms. onUpdate(record) is called with each answer; polling stops when done(record) is true,
 * after maxMs, or when the returned function is called. A 404 means the server forgot the job: onMissing() is called.
 */
export function poll(url, { every = 2500, retry = 5000, maxMs = 90 * 60e3, onUpdate, done, onMissing } = {}) {
  let live = true, timer = 0
  const t0 = Date.now()
  const tick = () => api(url).then((r) => {
    if (!live) return
    onUpdate?.(r)
    if (done?.(r) || Date.now() - t0 > maxMs) return
    timer = setTimeout(tick, every)
  }).catch((e) => {
    if (!live) return
    if (String(e).includes('404') && onMissing) { onMissing(); return }
    timer = setTimeout(tick, retry)
  })
  tick()
  return () => { live = false; clearTimeout(timer) }
}
export const jobFinished = (j) => j.status === 'done' || j.status === 'error'
